-- 入队补偿：gates.lua 通过但 RabbitMQ 发布"确定失败"（发送前错误 / broker nack）时，
-- 回滚闸门副作用（配额扣减 + 并发占位）。结果不确定（confirm 超时/连接中断）不调本脚本
-- ——消息可能已入队，worker 幂等兜底（book 锁 + tasks.status）。
-- bookcnt 不反悔：撤销配额/并发即够，罕见多计一天书数可接受（次日自然清零，安全方向）。
-- KEYS[1] = rate:quota:{uid}:{date}      (String)
-- KEYS[2] = rate:bookquota:{uid}:{pid}:{date}  (String)
-- KEYS[3] = rate:inflight:{uid}:{pid}    (Set)
-- ARGV[1] = quota_deduct_n, ARGV[2] = task_id
redis.call('DECRBY', KEYS[1], tonumber(ARGV[1]))
redis.call('DECRBY', KEYS[2], tonumber(ARGV[1]))
redis.call('SREM', KEYS[3], ARGV[2])
return 1
