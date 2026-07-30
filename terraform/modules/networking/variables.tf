variable "env_id" {
  description = "Unique environment identifier."
  type        = string
}

variable "vpc_id" {
  description = "ID of the pre-existing shared VPC."
  type        = string
}

variable "region" {
  description = "AWS region (used to pick two distinct AZs)."
  type        = string
}

variable "common_tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
