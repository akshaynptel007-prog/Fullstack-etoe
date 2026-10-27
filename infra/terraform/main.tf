locals {
  name = "${var.project_name}-${var.environment}"
  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Shared secret between CloudFront and the ALB: requests that bypass
# CloudFront (and therefore WAF) are rejected at the load balancer.
resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

module "network" {
  source             = "./modules/network"
  name               = local.name
  vpc_cidr           = var.vpc_cidr
  az_count           = var.az_count
  enable_nat_gateway = var.enable_nat_gateway
}

module "ecr" {
  source = "./modules/ecr"
  name   = local.name
}

module "data" {
  source                       = "./modules/data"
  name                         = local.name
  private_subnet_ids           = module.network.private_subnet_ids
  postgres_security_group_id   = module.network.postgres_security_group_id
  redis_security_group_id      = module.network.redis_security_group_id
  rabbitmq_security_group_id   = module.network.rabbitmq_security_group_id
  db                           = var.db
  redis                        = var.redis
  mq                           = var.mq
  rabbitmq_external_url        = var.rabbitmq_external_url
  secrets_recovery_window_days = var.secrets_recovery_window_days
}

module "compute" {
  source                = "./modules/compute"
  name                  = local.name
  aws_region            = var.aws_region
  vpc_id                = module.network.vpc_id
  public_subnet_ids     = module.network.public_subnet_ids
  app_subnet_ids        = module.network.app_subnet_ids
  assign_public_ip      = module.network.assign_public_ip
  alb_security_group_id = module.network.alb_security_group_id
  app_security_group_id = module.network.app_security_group_id
  image                 = "${module.ecr.repository_url}:${var.image_tag}"
  cpu_architecture      = var.cpu_architecture
  secret_arn            = module.data.secret_arn
  origin_verify_secret  = random_password.origin_verify.result
  api                   = var.api
  worker                = var.worker
  prewarm_schedules     = var.prewarm_schedules
  app_env               = var.app_env
  mq_broker_name        = module.data.mq_broker_name
  db_identifier         = module.data.db_identifier
  log_retention_days    = var.log_retention_days
  alarm_email           = var.alarm_email
}

module "edge" {
  source = "./modules/edge"
  providers = {
    aws           = aws
    aws.us_east_1 = aws.us_east_1
  }
  name                           = local.name
  alb_dns_name                   = module.compute.alb_dns_name
  origin_verify_secret           = random_password.origin_verify.result
  price_class                    = var.cloudfront_price_class
  enable_waf                     = var.enable_waf
  enable_bot_control             = var.enable_bot_control
  waf_rate_limit_per_ip          = var.waf_rate_limit_per_ip
  waf_checkout_rate_limit_per_ip = var.waf_checkout_rate_limit_per_ip
}
