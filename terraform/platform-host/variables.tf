variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "vpc_id" {
  description = "VPC ID from the shared AWS bootstrap (terraform/modules/networking)"
  type        = string
}

variable "public_subnet_id" {
  description = "Public subnet ID (must route to an Internet Gateway) from the shared bootstrap"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for the platform API host"
  type        = string
  default     = "t3.micro"
}

variable "root_volume_size_gb" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 20
}

variable "name_prefix" {
  description = "Prefix applied to resource names/tags"
  type        = string
  default     = "outpost-platform"
}
