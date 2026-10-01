"""第 6 道闸门：内置密钥的**终身**章数上限（`gates.lua` KEYS[6] / ARGV[9]）。

与其余五项的区别只有一处：它不过期。所以这里要钉住的不只是「拦不拦得住」，还有
「什么时候根本不计数」——计数一旦混进用户自备 Key 写的章节，他后来把 Key 删掉就会被判定
「免费章节已写完」，而他从没花过部署方一分钱。

真跑 Redis + 真 Lua（测试栈自带）：KEYS 顺序或 ARGV 个数写错只有真脚本抓得住。
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pika
import pytest
from sqlalchemy import select

from myink.db import new_session
from myink.models import Project
from myink.worker import enqueue as enq
from myink.worker.enqueue import EnqueueUnavailable, GateError
from myink.worker.redis_client import (
    book_cnt_key,
    book_quota_key,
    cost_key,
    get_redis,
    inflight_key,
    platform_book_key,
    quota_key,
)


@pytest.fixture
def quiet_publish(monkeypatch):
    """不真发消息：这几条验的是闸门，不是 RabbitMQ。"""
    monkeypatch.setattr(enq.amqp, "publish", lambda *a, **kw: None)


@pytest.fixture
def book(temp_project):
    """temp_project 那本书 + 车主；用完把本用例碰过的 Redis 键清干净。"""
    pid = temp_project
    with new_session() as db:
        uid = str(db.scalar(select(Project.user_id).where(Project.id == uuid.UUID(pid))))
    today = date.today().isoformat()
    r = get_redis()
    before = set(r.scan_iter("queue:task-owner:*")) | set(r.scan_iter("queue:sse:*"))
    fixed = [quota_key(uid, today), inflight_key(uid, pid), cost_key(today),
             book_quota_key(uid, pid, today), book_cnt_key(uid, today),
             platform_book_key(uid, pid)]
    try:
        yield SimpleNamespace(pid=pid, uid=uid, r=r, key=platform_book_key(uid, pid))
    finally:
        r.delete(*fixed)
        stale = (set(r.scan_iter("queue:task-owner:*")) | set(r.scan_iter("queue:sse:*"))) - before
        if stale:
            r.delete(*stale)


def _enqueue(book, *, quota_n: int = 1, max_chapters: int = 0) -> dict:
    """入队一次，随即把并发位让出来。

    闸门里 `inflight > 0` 是**硬编码的同书串行**（`enqueue.py` docstring 说过不要去"修"它），
    worker 要到任务终态才 SREM。同一本书连入两次不释放就必然是 CONCURRENCY_LIMIT，
    测不到这里真正想测的章数闸门。
    """
    result = enq.enqueue(user_id=book.uid, project_id=book.pid, task_type="chapter_generate",
                         payload={"seq": 1}, quota_n=quota_n, cost_est=0.0, priority=0,
                         platform_chapter_max=max_chapters)
    book.r.srem(inflight_key(book.uid, book.pid), result["task_id"])
    return result


def _gate_keys(book) -> list[str]:
    """独立重建 `enqueue()` 里那份 KEYS——布局写错在这里就暴露。"""
    today = date.today().isoformat()
    return [quota_key(book.uid, today), inflight_key(book.uid, book.pid), cost_key(today),
            book_quota_key(book.uid, book.pid, today), book_cnt_key(book.uid, today),
            platform_book_key(book.uid, book.pid)]


def test_zero_means_unlimited_and_the_key_is_never_even_created(book, quiet_publish):
    """max=0（不吃平台密钥）→ 不拦，而且计数器根本不出现。

    这条是「不计数」那一半的意义所在：零自备连接的用户写满额度之后配了自己的 Key，
    之前用自备 Key 写的章节不该把免费额度提前耗光。
    """
    for _ in range(3):
        assert _enqueue(book)["status"] == "queued"
    assert book.r.exists(book.key) == 0


def test_the_chapter_that_would_exceed_the_limit_is_refused(book, quiet_publish):
    """上限 2：前两章过，第三章拒，且拒绝不留副作用（计数停在 2、不占并发、不扣配额）。"""
    assert _enqueue(book, max_chapters=2)["status"] == "queued"
    assert _enqueue(book, max_chapters=2)["status"] == "queued"
    assert book.r.get(book.key) == "2"

    with pytest.raises(GateError) as exc:
        _enqueue(book, max_chapters=2)

    assert exc.value.code == "PLATFORM_CHAPTER_EXCEEDED"
    assert book.r.get(book.key) == "2"


def test_the_refusal_is_a_read_not_a_write(book, quiet_publish):
    """拒绝那次在 Redis 里什么都没留下——直接调闸门，才拿得到用来断言的 task_id。

    `enqueue()` 拒了就抛，task_id 出不来；只有把闸门单独跑一次才能证明「集合里没有它」。
    顺带独立钉住 KEYS 布局（这里的键是照着 `enqueue()` 重建的，顺序错就红）。
    """
    _enqueue(book, max_chapters=2)
    _enqueue(book, max_chapters=2)
    today = date.today().isoformat()

    code, reason = enq._run_gates(book.r, _gate_keys(book), task_id="refused-probe",
                                  quota_n=1, cost_est=0.0, project_id=book.pid,
                                  platform_chapter_max=2)

    assert (code, reason) == (-5, "PLATFORM_CHAPTER_EXCEEDED")
    assert book.r.get(book.key) == "2"
    assert book.r.sismember(inflight_key(book.uid, book.pid), "refused-probe") == 0
    assert book.r.get(quota_key(book.uid, today)) == "2"
    assert book.r.get(book_quota_key(book.uid, book.pid, today)) == "2"


def test_the_counter_never_expires(book, quiet_publish):
    """终身计数：`EXPIRE` 一挂上去，第二天额度就自己回来了。"""
    _enqueue(book, max_chapters=30)
    assert book.r.ttl(book.key) == -1


def test_a_batch_is_charged_its_whole_size(book, quiet_publish):
    """批次扣的是 size：上限 5 时一次 4 章过、还剩 1 章，再来 2 章就被拒。"""
    assert _enqueue(book, quota_n=4, max_chapters=5)["status"] == "queued"
    assert book.r.get(book.key) == "4"
    with pytest.raises(GateError):
        _enqueue(book, quota_n=2, max_chapters=5)
    assert book.r.get(book.key) == "4"


def test_a_batch_larger_than_the_whole_limit_is_refused_outright(book, quiet_publish):
    """一次就超过总额度：整批判拒，计数不动（不是先扣后拦）。"""
    with pytest.raises(GateError) as exc:
        _enqueue(book, quota_n=6, max_chapters=5)
    assert exc.value.code == "PLATFORM_CHAPTER_EXCEEDED"
    assert book.r.exists(book.key) == 0


def test_definite_publish_failure_gives_the_chapter_back(book, monkeypatch):
    """发布确定失败 → 补偿脚本要把这一章还回去（同 quota / bookquota / 并发）。"""
    def _nack(*_args, **_kwargs):
        raise pika.exceptions.NackError([])

    assert _enqueue(book, max_chapters=2)["status"] == "queued"
    monkeypatch.setattr(enq.amqp, "publish", _nack)

    with pytest.raises(EnqueueUnavailable):
        _enqueue(book, max_chapters=2)

    assert book.r.get(book.key) == "1"


def test_compensation_leaves_the_counter_alone_when_it_was_never_counted(book, monkeypatch):
    """max=0 时 gates.lua 没有 INCRBY，补偿就不能 DECRBY——否则凭空多出一个 -1 的键。"""
    def _nack(*_args, **_kwargs):
        raise pika.exceptions.NackError([])

    monkeypatch.setattr(enq.amqp, "publish", _nack)
    with pytest.raises(EnqueueUnavailable):
        _enqueue(book, max_chapters=0)

    assert book.r.exists(book.key) == 0