output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "api_service_name" {
  value = aws_ecs_service.api.name
}

output "worker_service_name" {
  value = aws_ecs_service.worker.name
}

output "migrate_task_definition" {
  value = aws_ecs_task_definition.migrate.family
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "log_groups" {
  value = { for k, g in aws_cloudwatch_log_group.this : k => g.name }
}
