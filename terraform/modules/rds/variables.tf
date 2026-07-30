variable "env_id" {
  description = "Unique environment identifier."
  type        = string
}

variable "subnet_ids" {
  description = "At least two subnet IDs in different AZs, for the DB subnet group."
  type        = list(string)

  validation {
    condition     = length(var.subnet_ids) >= 2
    error_message = "RDS requires a DB subnet group spanning at least 2 subnets in different AZs."
  }
}

variable "security_group_id" {
  description = "Security group to attach to the RDS instance."
  type        = string
}

variable "common_tags" {
  description = "Tags applied to every resource."
  type        = map(string)
}
