-- Sliding-window-log rate limiter.
--
-- Rejected requests are NOT recorded, so the sorted set never holds more than
-- `limit` members: memory per key is bounded even under a flood.
--
-- KEYS[1] rl:<scope>:<identity>
-- ARGV[1] limit (requests per window)
-- ARGV[2] window in milliseconds
-- ARGV[3] unique member for this request (request id)
--
-- Returns {allowed (1|0), remaining, retry_after_ms}

local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])

if count < limit then
  redis.call('ZADD', KEYS[1], now, ARGV[3])
  redis.call('PEXPIRE', KEYS[1], window)
  return {1, limit - count - 1, 0}
end

local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
local retry_after = window
if oldest[2] then
  retry_after = math.max(1, tonumber(oldest[2]) + window - now)
end
return {0, 0, retry_after}
