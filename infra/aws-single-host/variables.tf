variable "aws_region" {
  description = "AWS region for the single-host deployment."
  type        = string
  default     = "ap-south-1"
}

variable "resource_name_prefix" {
  description = "Prefix for resources created by this deployment."
  type        = string
  default     = "flashsale-single-host"
}

variable "bootstrap_log_file" {
  description = "Filename for the EC2 bootstrap log under /var/log."
  type        = string
  default     = "flashsale-bootstrap.log"
}

variable "source_zip_path" {
  description = "Path to the source archive uploaded for EC2 bootstrap."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for the single-host deployment. AWS charges depend on the account and region."
  type        = string
  default     = "c7i-flex.large"
}

variable "root_volume_gib" {
  description = "Encrypted EC2 root volume size."
  type        = number
  default     = 30
}
