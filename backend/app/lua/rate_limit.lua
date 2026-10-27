-- Sliding-window-log rate limiter over one or more identities (e.g. the
-- client IP AND the user), checked atomically in a single round trip: the
-- request is admitted only if EVERY window has room, and is then recorded in
-- all of them. Rejected requests are not recorded, so each sorted set holds
-- at most `limit` members — memory stays bounded even under a flood.
--
-- KEYS[i]   rl:{group}:<scope>:<identity>   (shared hash tag: cluster safe)
-- ARGV[1]   window in milliseconds
-- ARGV[2]   unique member for this request
-- ARGV[2+i] limit for KEYS[i]
--
-- Returns {allowed (1|0), denied_index (0 = none), remaining, retry_after_ms}

local window = tonumber(ARGV[1])
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local remaining = nil

for i, key in ipairs(KEYS) do
  local limit = tonumber(ARGV[2 + i])
  redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
  local count = redis.call('ZCARD', key)
  if count >= limit then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = window
    if oldest[2] then
      retry_after = math.max(1, tonumber(oldest[2]) + window - now)
    end
    return {0, i, 0, retry_after}
  end
  local left = limit - count - 1
  if remaining == nil or left < remaining then
    remaining = left
  end
end

for _, key in ipairs(KEYS) do
  redis.call('ZADD', key, now, ARGV[2])
  redis.call('PEXPIRE', key, window)
end
return {1, 0, remaining, 0}
