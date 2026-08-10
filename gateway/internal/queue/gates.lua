-- 三层闸门 + 入队原子脚本（§13，消灭 TOCTOU）。
-- 消息格式与 worker 侧对齐：queue:tasks 单字段 body = 整条任务 JSON（consumer 读 fields["body"]）。
-- KEYS[1] = queue:tasks stream
-- KEYS[2] = rate:quota:{uid}:{date}     (String, 每用户日配额已用)
-- KEYS[3] = rate:inflight:{uid}:{pid}   (Set, 每书进行中任务；异书并行、同书串行 §13)
-- KEYS[4] = rate:cost:{date}            (String, 全局日成本已用, worker 终态累计)
-- KEYS[5] = rate:bookquota:{uid}:{pid}:{date}  (String, 每书日配额已用；多书写书上限双层限制)
-- KEYS[6] = rate:bookcnt:{uid}:{date}  (Set, 每用户每天碰过的去重书数；一天最多 N 本书)
-- ARGV[1] = task_id, [2] = body_json（整条任务字典 JSON）
-- ARGV[3] = quota_deduct_n (单章=1, 批次=N), [4] = cost_est
-- ARGV[5] = quota_max, [6] = cost_budget, [7] = book_quota_max, [8] = books_per_day_max
-- ARGV[9] = project_id（bookcnt 集合成员，按书去重）
local quota_used = tonumber(redis.call('GET', KEYS[2]) or '0')
local quota_deduct = tonumber(ARGV[3])
if quota_used + quota_deduct > tonumber(ARGV[5]) then
  return {-1, 'QUOTA_EXCEEDED', tostring(quota_used), tostring(quota_deduct)}
end
local book_quota_used = tonumber(redis.call('GET', KEYS[5]) or '0')
if book_quota_used + quota_deduct > tonumber(ARGV[7]) then
  return {-1, 'BOOK_QUOTA_EXCEEDED', tostring(book_quota_used), tostring(quota_deduct)}
end
-- 每天最多 N 本不同书：SISMEMBER 判断是否新书（写命令 SADD 只能在全部检查通过后执行，
-- 否则拒绝时集合已加成员，副作用残留）；对未加入的新书按 SCARD+1 预判超限。
local is_new_book = redis.call('SISMEMBER', KEYS[6], ARGV[9])
local book_cnt = redis.call('SCARD', KEYS[6])
if is_new_book == 0 and book_cnt + 1 > tonumber(ARGV[8]) then
  return {-4, 'BOOK_CNT_EXCEEDED', tostring(book_cnt)}
end
local inflight = redis.call('SCARD', KEYS[3])
if inflight > 0 then
  return {-2, 'CONCURRENCY_LIMIT', tostring(inflight)}
end
local cost_used = tonumber(redis.call('GET', KEYS[4]) or '0')
local cost_est = tonumber(ARGV[4])
if cost_used + cost_est > tonumber(ARGV[6]) then
  return {-3, 'DAILY_BUDGET_EXCEEDED', tostring(cost_used), tostring(cost_est)}
end
-- 通过：扣配额（用户 + 每书）、记书数（新书才加）、占并发、入队（body 单字段）
redis.call('INCRBY', KEYS[2], quota_deduct)
if quota_deduct > 0 then redis.call('EXPIRE', KEYS[2], 86400) end
redis.call('INCRBY', KEYS[5], quota_deduct)
if quota_deduct > 0 then redis.call('EXPIRE', KEYS[5], 86400) end
redis.call('SADD', KEYS[6], ARGV[9])
redis.call('EXPIRE', KEYS[6], 86400)
redis.call('SADD', KEYS[3], ARGV[1])
-- 并发闸门 TTL 安全网：worker 只在终态 SREM，retry→DLQ 泄漏/异常崩溃时
-- 不释放会永久锁死本书（评审 A1）；1h 兜底过期，闸门让位书锁（worker 侧权威串行）。
redis.call('EXPIRE', KEYS[3], 3600)
redis.call('XADD', KEYS[1], '*', 'body', ARGV[2])
return {1, ARGV[1]}
