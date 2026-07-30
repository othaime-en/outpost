variable "env_id" {
  description = "Unique environment identifier."
  type        = string
}

variable "region" {
  description = "AWS region (used for the CloudWatch log driver config)."
  type        = string
}

variable "subnet_id" {
  description = "Subnet the ECS service's tasks run in."
  type        = string
}

variable "security_group_id" {
  type = string
}

variable "rds_secret_arn" {
  description = "ARN of the Secrets Manager secret holding RDS credentials."
  type        = string
}

variable "container_image" {
  type    = string
  default = "public.ecr.aws/nginx/nginx:latest"
}

variable "common_tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
