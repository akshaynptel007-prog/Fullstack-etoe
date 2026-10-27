variable "name" {
  type = string
}

variable "alb_dns_name" {
  type = string
}

variable "origin_verify_secret" {
  type      = string
  sensitive = true
}

variable "price_class" {
  type = string
}

variable "enable_waf" {
  type = bool
}

variable "enable_bot_control" {
  type = bool
}

variable "waf_rate_limit_per_ip" {
  type = number
}

variable "waf_checkout_rate_limit_per_ip" {
  type = number
}
