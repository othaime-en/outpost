variable "env_id" {
  description = "Unique environment identifier."
  type        = string
}

variable "rds_address" {
  description = "RDS hostname (no port)."
  type        = string
}

variable "rds_port" {
  description = "RDS port."
  type        = number
  default     = 5432
}

variable "rds_username" {
  type = string
}

variable "rds_password" {
  type      = string
  sensitive = true
}

variable "common_tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
