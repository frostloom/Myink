"""Host-only cooperative cancellation and immutable execution/cleanup clocks."""
from contextlib import contextmanager
import signal
from threading import Event, RLock, Thread, current_thread, main_thread
import time


class _Cancellation(Event):
    # Signal handlers cannot take Event's non-reentrant condition lock.
    signal_requested = False

    def is_set(self):
        return self.signal_requested or super().is_set()


class Lifecycle:
    def __init__(self, deadline):
        self.deadline = deadline
        self._end = time.monotonic() + max(0, deadline - time.time())
        self.cancel = _Cancellation()
        self._reasons = []
        self._lock = RLock()
        self._cleanup_end = None
        self._cleanup_wall = None

    @property
    def reason(self):
        return self._reasons[0] if self._reasons else None

    def interrupt(self):
        if not self._reasons:
            self._reasons.append('interrupted')
        self.cancel.signal_requested = True

    def remaining(self):
        return min(self.deadline - time.time(), self._end - time.monotonic())

    def stop(self, reason):
        with self._lock:
            if self.reason is None:
                self._reasons.append(reason)
            self.cancel.set()

    def check(self):
        if self.remaining() <= 0:
            self.stop('deadline_exceeded')
        if self.cancel.is_set():
            raise TimeoutError('analysis execution stopped')
        return self.remaining()

    def begin_cleanup(self):
        with self._lock:
            if self._cleanup_end is None:
                self.cancel.set()
                self._cleanup_end = min(time.monotonic() + 120, self._end + 120)
                self._cleanup_wall = min(time.time() + 120, self.deadline + 120)

    def shutdown_server(self, server, thread):
        remaining = self.cleanup_remaining if self._cleanup_end is not None else self.check
        available = remaining()
        finished = Event()
        errors = []
        def shutdown():
            try:
                server.shutdown()
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()
        Thread(target=shutdown, daemon=True).start()
        if not finished.wait(min(2, available)):
            raise TimeoutError('analysis server shutdown wait expired')
        if errors:
            raise errors[0]
        thread.join(min(2, remaining()))
        if thread.is_alive():
            raise TimeoutError('analysis server join expired')

    def cleanup_remaining(self):
        self.begin_cleanup()
        remaining = min(self._cleanup_end - time.monotonic(), self._cleanup_wall - time.time())
        if remaining <= 0:
            raise TimeoutError('analysis cleanup wait expired')
        return remaining


@contextmanager
def signal_scope(lifecycle):
    """CLI opt-in only; library threads never change process signal handlers."""
    if current_thread() is not main_thread():
        yield
        return
    previous = {}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.getsignal(sig)
            signal.signal(sig, lambda *_: lifecycle.interrupt())
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
