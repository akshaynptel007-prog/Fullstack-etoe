variable "name" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "app_subnet_ids" {
  type = list(string)
}

variable "assign_public_ip" {
  type = bool
}

variable "alb_security_group_id" {
  type = string
}

variable "app_security_group_id" {
  type = string
}

variable "image" {
  description = "Full backend image reference (repository_url:tag)."
  type        = string
}

variable "cpu_architecture" {
  type = string
}

variable "secret_arn" {
  type = string
}

variable "origin_verify_secret" {
  description = "Shared secret CloudFront sends in X-Origin-Verify; the ALB rejects requests without it."
  type        = string
  sensitive   = true
}

variable "api" {
  type = object({
    cpu                 = number
    memory              = number
    min_count           = number
    max_count           = number
    target_cpu_percent  = number
    requests_per_target = number
  })
}

variable "worker" {
  type = object({
    cpu       = number
    memory    = number
    min_count = number
    max_count = number
    use_spot  = bool
    prefetch  = number
  })
}

variable "prewarm_schedules" {
  type = list(object({
    name       = string
    schedule   = string
    timezone   = optional(string, "Asia/Kolkata")
    api_min    = number
    api_max    = number
    worker_min = number
    worker_max = number
  }))
}

variable "app_env" {
  type = map(string)
}

variable "mq_broker_name" {
  description = "Amazon MQ broker name for queue-depth autoscaling/alarms (null for an external broker)."
  type        = string
  default     = null
}

variable "db_identifier" {
  type = string
}

variable "log_retention_days" {
  type = number
}

variable "alarm_email" {
  type = string
}
