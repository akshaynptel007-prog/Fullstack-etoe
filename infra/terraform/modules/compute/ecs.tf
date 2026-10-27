resource "aws_ecs_cluster" "this" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

resource "aws_cloudwatch_log_group" "this" {
  for_each          = toset(["api", "worker", "migrate"])
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = var.log_retention_days
}

locals {
  secret_keys = ["DATABASE_URL", "REDIS_URL", "RABBITMQ_URL", "JWT_SECRET", "ADMIN_API_KEY"]

  base_env = merge(
    {
      APP_ENV = "production"
      # CloudFront appends the viewer IP to X-Forwarded-For, the ALB appends
      # CloudFront's: the real client is 2 hops from the right.
      CLIENT_IP_TRUSTED_HOPS = "2"
      WEB_CONCURRENCY        = "1"
      WORKER_PREFETCH        = tostring(var.worker.prefetch)
      RABBITMQ_NAMESPACE     = "flashsale"
    },
    var.app_env,
  )

  environment = [for k, v in local.base_env : { name = k, value = v }]
  secrets     = [for k in local.secret_keys : { name = k, valueFrom = "${var.secret_arn}:${k}::" }]

  container_common = {
    image                  = var.image
    essential              = true
    environment            = local.environment
    secrets                = local.secrets
    readonlyRootFilesystem = false
    linuxParameters        = { initProcessEnabled = true }
    ulimits                = [{ name = "nofile", softLimit = 65536, hardLimit = 65536 }]
  }

  python_http_check = "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:%d%s', timeout=2).status != 200)"
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api.cpu
  memory                   = var.api.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container_common, {
    name         = "api"
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    stopTimeout  = 30
    healthCheck = {
      command     = ["CMD", "python", "-c", format(local.python_http_check, 8000, "/healthz")]
      interval    = 10
      timeout     = 5
      retries     = 3
      startPeriod = 15
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this["api"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "api"
        mode                  = "non-blocking"
        max-buffer-size       = "4m"
      }
    }
  })])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker.cpu
  memory                   = var.worker.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container_common, {
    name    = "worker"
    command = ["python", "-m", "app.worker"]
    # Spot interruption / deploy: SIGTERM -> stop consuming -> drain -> exit.
    stopTimeout = 60
    healthCheck = {
      command     = ["CMD", "python", "-c", format(local.python_http_check, 9100, "/metrics")]
      interval    = 15
      timeout     = 5
      retries     = 3
      startPeriod = 15
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this["worker"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "worker"
      }
    }
  })])
}

# One-off task run by deploy.sh before rolling out new code.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([merge(local.container_common, {
    name    = "migrate"
    command = ["sh", "-c", "alembic upgrade head && python -m app.cli seed"]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.this["migrate"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "migrate"
      }
    }
  })])
}

resource "aws_ecs_service" "api" {
  name                              = "api"
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = var.api.min_count
  launch_type                       = "FARGATE"
  enable_execute_command            = true
  propagate_tags                    = "SERVICE"
  health_check_grace_period_seconds = 30

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.app_subnet_ids
    security_groups  = [var.app_security_group_id]
    assign_public_ip = var.assign_public_ip
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  lifecycle {
    ignore_changes = [desired_count] # owned by autoscaling
  }

  depends_on = [aws_lb_listener_rule.from_cloudfront]
}

resource "aws_ecs_service" "worker" {
  name                   = "worker"
  cluster                = aws_ecs_cluster.this.id
  task_definition        = aws_ecs_task_definition.worker.arn
  desired_count          = var.worker.min_count
  enable_execute_command = true
  propagate_tags         = "SERVICE"

  # Workers are interruption-tolerant (unacked messages are redelivered), so
  # Spot is a safe ~70% saving; keep one on-demand task as a floor.
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = var.worker.use_spot ? 1 : 0
    weight            = var.worker.use_spot ? 0 : 1
  }

  dynamic "capacity_provider_strategy" {
    for_each = var.worker.use_spot ? [1] : []
    content {
      capacity_provider = "FARGATE_SPOT"
      weight            = 1
    }
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.app_subnet_ids
    security_groups  = [var.app_security_group_id]
    assign_public_ip = var.assign_public_ip
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}
