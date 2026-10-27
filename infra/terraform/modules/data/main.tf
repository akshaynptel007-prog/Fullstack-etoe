locals {
  use_amazon_mq = var.rabbitmq_external_url == ""
  db_name       = "flashsale"
  db_user       = "flashsale"
  mq_user       = "flashsale"
}

# Generated credentials. They live in the (encrypted, versioned) Terraform
# state and in Secrets Manager; tasks read them from Secrets Manager only.
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "redis" {
  length  = 32
  special = false
}

resource "random_password" "mq" {
  length  = 32
  special = false
}

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "admin" {
  length  = 40
  special = false
}

# --- PostgreSQL (source of truth) ---------------------------------------------
resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.private_subnet_ids
}

resource "aws_db_parameter_group" "this" {
  name   = "${var.name}-pg${split(".", var.db.engine_version)[0]}"
  family = "postgres${split(".", var.db.engine_version)[0]}"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_lock_waits"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
}

resource "aws_db_instance" "this" {
  identifier                      = var.name
  engine                          = "postgres"
  engine_version                  = var.db.engine_version
  instance_class                  = var.db.instance_class
  allocated_storage               = var.db.allocated_storage
  max_allocated_storage           = var.db.allocated_storage * 5
  storage_type                    = "gp3"
  storage_encrypted               = true
  db_name                         = local.db_name
  username                        = local.db_user
  password                        = random_password.db.result
  db_subnet_group_name            = aws_db_subnet_group.this.name
  vpc_security_group_ids          = [var.postgres_security_group_id]
  parameter_group_name            = aws_db_parameter_group.this.name
  multi_az                        = var.db.multi_az
  publicly_accessible             = false
  backup_retention_period         = 1
  deletion_protection             = var.db.deletion_protection
  skip_final_snapshot             = var.db.skip_final_snapshot
  final_snapshot_identifier       = var.db.skip_final_snapshot ? null : "${var.name}-final"
  auto_minor_version_upgrade      = true
  apply_immediately               = true
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = ["postgresql"]
}

# --- Redis (inventory tokens, rate limits, order status) ----------------------
resource "aws_elasticache_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id       = var.name
  description                = "Flash-sale inventory gate and rate limiter"
  engine                     = "redis"
  engine_version             = var.redis.engine_version
  node_type                  = var.redis.node_type
  num_cache_clusters         = var.redis.num_nodes
  automatic_failover_enabled = var.redis.num_nodes > 1
  multi_az_enabled           = var.redis.num_nodes > 1
  port                       = 6379
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [var.redis_security_group_id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = random_password.redis.result
  apply_immediately          = true
  # Never evict the inventory counter under memory pressure.
  parameter_group_name = aws_elasticache_parameter_group.this.name
}

resource "aws_elasticache_parameter_group" "this" {
  name   = "${var.name}-redis7"
  family = "redis7"

  parameter {
    name  = "maxmemory-policy"
    value = "noeviction"
  }
}

# --- RabbitMQ (Amazon MQ) unless an external broker URL is provided ------------
resource "aws_mq_broker" "this" {
  count                      = local.use_amazon_mq ? 1 : 0
  broker_name                = var.name
  engine_type                = "RabbitMQ"
  engine_version             = var.mq.engine_version
  host_instance_type         = var.mq.instance_type
  deployment_mode            = "SINGLE_INSTANCE"
  publicly_accessible        = false
  subnet_ids                 = [var.private_subnet_ids[0]]
  security_groups            = [var.rabbitmq_security_group_id]
  auto_minor_version_upgrade = true
  apply_immediately          = true

  user {
    username = local.mq_user
    password = random_password.mq.result
  }

  logs {
    general = true
  }
}

locals {
  # e.g. amqps://b-1234.mq.us-east-1.amazonaws.com:5671
  mq_endpoint = local.use_amazon_mq ? aws_mq_broker.this[0].instances[0].endpoints[0] : ""
  rabbitmq_url = (
    local.use_amazon_mq
    ? replace(local.mq_endpoint, "amqps://", "amqps://${local.mq_user}:${random_password.mq.result}@")
    : var.rabbitmq_external_url
  )
}

# --- One secret, many keys: injected into tasks by ECS ---------------------------
resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name}/app"
  description             = "Flash-sale runtime secrets (DB/Redis/RabbitMQ URLs, JWT, admin key)"
  recovery_window_in_days = var.secrets_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    DATABASE_URL  = "postgresql+asyncpg://${local.db_user}:${random_password.db.result}@${aws_db_instance.this.address}:5432/${local.db_name}?ssl=require"
    REDIS_URL     = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.this.primary_endpoint_address}:6379/0"
    RABBITMQ_URL  = local.rabbitmq_url
    JWT_SECRET    = random_password.jwt.result
    ADMIN_API_KEY = random_password.admin.result
  })
}
