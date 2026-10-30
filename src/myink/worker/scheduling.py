"""Weighted dispatch without prefetch and durable chapter-boundary yielding."""
from contextlib import contextmanager
from contextvars import ContextVar

from myink.worker import amqp

_batch_slicing = ContextVar('batch_slicing', default=False)


@contextmanager
def slice_batches():
    token = _batch_slicing.set(True)
    try:
        yield
    finally:
        _batch_slicing.reset(token)


def batch_slicing():
    return _batch_slicing.get()


def invoke_batch_slice(graph, state, config):
    # The advanced position is durable before the delivery is handed back.
    result = graph.invoke(state, config=config, interrupt_after=['bridge'], durability='sync')
    snap = graph.get_state(config)
    if snap.next == ('chapter',) and not any(task.interrupts for task in snap.tasks):
        return {**result, 'scheduler_yield': True}
    return result


class FairScheduler:
    """Per-worker weights measure dispatch opportunities, not execution time."""

    def __init__(self):
        self.position = 0

    def take(self, channel, weights):
        vip, normal = weights['vip'], weights['normal']
        slot = self.position % (vip + normal)
        self.position = (slot + 1) % (vip + normal)
        queues = ((amqp.vip_queue(), amqp.main_queue()) if slot < vip
                  else (amqp.main_queue(), amqp.vip_queue()))
        for queue in queues:
            delivery = channel.basic_get(queue=queue, auto_ack=False)
            if delivery[0] is not None:
                return delivery
        return None
