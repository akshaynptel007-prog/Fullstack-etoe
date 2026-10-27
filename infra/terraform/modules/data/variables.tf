variable "name" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "postgres_security_group_id" {
  type = string
}

variable "redis_security_group_id" {
  type = string
}

variable "rabbitmq_security_group_id" {
  type = string
}

variable "db" {
  type = object({
    instance_class      = string
    engine_version      = string
    allocated_storage   = number
    multi_az            = bool
    deletion_protection = bool
    skip_final_snapshot = bool
  })
}

variable "redis" {
  type = object({
    node_type      = string
    engine_version = string
    num_nodes      = number
  })
}

variable "mq" {
  type = object({
    instance_type  = string
    engine_version = string
  })
}

variable "rabbitmq_external_url" {
  type      = string
  sensitive = true
}

variable "secrets_recovery_window_days" {
  type = number
}
