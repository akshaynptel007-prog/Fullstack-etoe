# --- Identity ------------------------------------------------------------------
variable "project_name" {
  description = "Short name used as a prefix for every resource."
  type        = string
  default     = "flashsale"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project_name))
    error_message = "Lowercase letters, digits and dashes, 2-21 chars."
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)."
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "Region for everything except the CloudFront WAF (always us-east-1)."
  type        = string
  default     = "us-east-1"
}

variable "image_tag" {
  description = "Backend image tag in ECR (deploy.sh passes the git SHA)."
  type        = string
  default     = "latest"
}

# --- Network -------------------------------------------------------------------
variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "az_count" {
  description = "Availability zones to spread subnets across (>= 2 for the ALB/RDS)."
  type        = number
  default     = 2
}

variable "enable_nat_gateway" {
  description = "Private subnets + one NAT gateway (~$32/mo). false = tasks get public IPs in public subnets (cheaper, still SG-locked)."
  type        = bool
  default     = true
}

# --- Compute -------------------------------------------------------------------
variable "cpu_architecture" {
  description = "X86_64 or ARM64 (Graviton, ~20% cheaper; deploy.sh builds the matching image)."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "api" {
  description = "API service sizing and autoscaling."
  type = object({
    cpu                 = number
    memory              = number
    min_count           = number
    max_count           = number
    target_cpu_percent  = number
    requests_per_target = number
  })
  default = {
    cpu                 = 512
    memory              = 1024
    min_count           = 2
    max_count           = 10
    target_cpu_percent  = 55
    requests_per_target = 1000
  }
}

variable "worker" {
  description = "Order worker sizing and autoscaling."
  type = object({
    cpu       = number
    memory    = number
    min_count = number
    max_count = number
    use_spot  = bool
    prefetch  = number
  })
  default = {
    cpu       = 256
    memory    = 512
    min_count = 1
    max_count = 4
    use_spot  = true
    prefetch  = 16
  }
}

variable "prewarm_schedules" {
  description = <<-EOT
    Scheduled scale-out ahead of a known sale. Autoscaling reacts in minutes;
    a 10-second spike at 8:00 PM needs capacity already running at 7:50 PM.
    schedule: "cron(50 19 * * ? *)" or "at(2026-11-01T19:50:00)".
  EOT
  type = list(object({
    name       = string
    schedule   = string
    timezone   = optional(string, "Asia/Kolkata")
    api_min    = number
    api_max    = number
    worker_min = number
    worker_max = number
  }))
  default = []
}

variable "app_env" {
  description = "Extra non-secret environment variables for API/worker containers."
  type        = map(string)
  default = {
    LOG_LEVEL                    = "INFO"
    RATE_LIMIT_CHECKOUT_PER_USER = "5"
    RATE_LIMIT_CHECKOUT_PER_IP   = "200"
    RATE_LIMIT_AUTH_PER_IP       = "30"
    SEED_SALE_STOCK              = "500"
    SEED_SALE_STARTS_IN_SECONDS  = "900"
    SEED_SALE_DURATION_MINUTES   = "120"
  }
}

# --- Data stores ---------------------------------------------------------------
variable "db" {
  type = object({
    instance_class      = string
    engine_version      = string
    allocated_storage   = number
    multi_az            = bool
    deletion_protection = bool
    skip_final_snapshot = bool
  })
  default = {
    instance_class      = "db.t4g.micro"
    engine_version      = "16"
    allocated_storage   = 20
    multi_az            = false
    deletion_protection = false
    skip_final_snapshot = true
  }
}

variable "redis" {
  type = object({
    node_type      = string
    engine_version = string
    num_nodes      = number
  })
  default = {
    node_type      = "cache.t4g.micro"
    engine_version = "7.1"
    num_nodes      = 1
  }
}

variable "mq" {
  description = "Amazon MQ for RabbitMQ (ignored when rabbitmq_external_url is set)."
  type = object({
    instance_type  = string
    engine_version = string
  })
  default = {
    instance_type  = "mq.t3.micro"
    engine_version = "3.13"
  }
}

variable "rabbitmq_external_url" {
  description = "Use an external hosted broker instead of Amazon MQ: amqps://user:pass@host/vhost"
  type        = string
  default     = ""
  sensitive   = true
}

variable "secrets_recovery_window_days" {
  description = "0 = delete immediately on destroy (lets you re-create the stack right away)."
  type        = number
  default     = 0
}

# --- Edge ----------------------------------------------------------------------
variable "enable_waf" {
  type    = bool
  default = true
}

variable "enable_bot_control" {
  description = "AWS WAF Bot Control managed rules (~$10/mo + per-request fees)."
  type        = bool
  default     = false
}

variable "waf_rate_limit_per_ip" {
  description = "Max requests per IP per minute across the site before WAF blocks."
  type        = number
  default     = 600
}

variable "waf_checkout_rate_limit_per_ip" {
  description = "Max checkout requests per IP per minute."
  type        = number
  default     = 60
}

variable "cloudfront_price_class" {
  type    = string
  default = "PriceClass_200" # includes India edge locations
}

# --- Ops -----------------------------------------------------------------------
variable "log_retention_days" {
  type    = number
  default = 14
}

variable "alarm_email" {
  description = "Optional email for CloudWatch alarm notifications (confirm the SNS subscription)."
  type        = string
  default     = ""
}
