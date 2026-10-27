output "secret_arn" {
  value = aws_secretsmanager_secret.app.arn
}

output "db_identifier" {
  value = aws_db_instance.this.identifier
}

output "db_address" {
  value = aws_db_instance.this.address
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "redis_replication_group_id" {
  value = aws_elasticache_replication_group.this.id
}

output "mq_broker_name" {
  description = "null when an external RabbitMQ URL is used."
  value       = local.use_amazon_mq ? aws_mq_broker.this[0].broker_name : null
}

output "mq_console_url" {
  description = "RabbitMQ management UI (reachable from inside the VPC only)."
  value       = local.use_amazon_mq ? aws_mq_broker.this[0].instances[0].console_url : null
}
