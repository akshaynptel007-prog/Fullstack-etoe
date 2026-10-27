output "app_url" {
  description = "Public URL (CloudFront)."
  value       = "https://${module.edge.domain_name}"
}

output "ecr_repository_url" {
  value = module.ecr.repository_url
}

output "ecs_cluster_name" {
  value = module.compute.cluster_name
}

output "api_service_name" {
  value = module.compute.api_service_name
}

output "worker_service_name" {
  value = module.compute.worker_service_name
}

output "migrate_task_definition" {
  value = module.compute.migrate_task_definition
}

# Network settings deploy.sh needs for `aws ecs run-task` (migrations).
output "app_subnet_ids_csv" {
  value = join(",", module.network.app_subnet_ids)
}

output "app_security_group_id" {
  value = module.network.app_security_group_id
}

output "assign_public_ip" {
  value = module.network.assign_public_ip ? "ENABLED" : "DISABLED"
}

output "frontend_bucket" {
  value = module.edge.bucket_name
}

output "cloudfront_distribution_id" {
  value = module.edge.distribution_id
}

output "app_secret_arn" {
  description = "Secrets Manager secret holding DB/Redis/RabbitMQ URLs, JWT secret and ADMIN_API_KEY."
  value       = module.data.secret_arn
}

output "rabbitmq_console_url" {
  value = module.data.mq_console_url
}

output "alb_dns_name" {
  description = "Origin only — direct requests get 403 (must come through CloudFront)."
  value       = module.compute.alb_dns_name
}

output "log_groups" {
  value = module.compute.log_groups
}
