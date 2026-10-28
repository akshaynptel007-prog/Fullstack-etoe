variable "aws_region" {
  description = "AWS region for the demo."
  type        = string
  default     = "ap-south-1"
}

variable "source_zip_path" {
  description = "Temporary source archive created by deploy-free-demo.ps1."
  type        = string
}

variable "instance_type" {
  description = "Single-host demo size; usage is paid from the active Free plan credits."
  type        = string
  default     = "c7i-flex.large"
}

variable "root_volume_gib" {
  description = "Encrypted EC2 root volume size."
  type        = number
  default     = 30
}
