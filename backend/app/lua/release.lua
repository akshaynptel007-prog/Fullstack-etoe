-- Compensating action: give a reservation back to the pool.
-- Used when the API could not hand the order to RabbitMQ, or when the worker
-- permanently failed to persist it. Only releases if the user still holds
-- exactly this order, so a double release can never inflate stock.
--
-- KEYS[1] sale:{id}:stock
-- KEYS[2] sale:{id}:buyers
-- ARGV[1] user_id
-- ARGV[2] order_id
--
-- Returns the new stock, or -1 if nothing was released.

if redis.call('HGET', KEYS[2], ARGV[1]) == ARGV[2] then
  redis.call('HDEL', KEYS[2], ARGV[1])
  return redis.call('INCR', KEYS[1])
end
return -1
