# ADR-0002: RabbitMQ (not Kafka) for the order queue

- **Status:** accepted

## Context

Reserved orders must be handed from the API to workers durably, processed at least once, retried on
transient failures and quarantined when poisonous. Volume is small (≈ stock messages per sale), but
the hand-off must never lose an accepted order.

## Decision

RabbitMQ with durable exchanges/queues, persistent messages, **publisher confirms**, `mandatory`
publishing, per-consumer **prefetch**, a **TTL retry queue** (delayed retry without plugins) and a
**dead-letter queue**.

## Why not Kafka

| Need | RabbitMQ | Kafka |
|---|---|---|
| Per-message ack/retry/dead-letter | built in | built by hand (retry topics, offsets) |
| Delayed retry | TTL + DLX | extra topics/consumers |
| Work-queue semantics (competing consumers) | native | partitions cap consumer parallelism |
| Ops footprint for a few hundred messages | one small broker (Amazon MQ, CloudAMQP free) | MSK/Confluent cluster, much heavier |
| Replay / event sourcing / analytics fan-out | limited | excellent |

Kafka would be the better choice if checkout events also fed analytics, recommendations or an audit
log that must be replayed. For a transactional work queue, RabbitMQ is simpler and safer.

## Consequences

- Single-instance brokers (local, `mq.t3.micro`) are a durability SPOF. Production should use a
  3-node cluster with quorum queues (`RABBITMQ_QUEUE_TYPE=quorum`).
- Queue depth is a first-class scaling signal (Amazon MQ `MessageReadyCount` → worker step scaling).
