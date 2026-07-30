output "ecs_service_arn" {
  description = "ARN of the ECS service. Written back to environments.outputs by the callback."
  value       = module.ecs.service_arn
}

output "ecs_cluster_arn" {
  description = "ARN of the shared ECS cluster this service runs on."
  value       = module.ecs.cluster_arn
}

output "rds_endpoint" {
  description = "host:port endpoint of the RDS instance."
  value       = module.rds.endpoint
}

output "rds_secret_arn" {
  description = "ARN of the Secrets Manager secret holding RDS credentials."
  value       = module.secrets.secret_arn
}

output "subnet_id" {
  description = "Primary subnet ID (used by the ECS service)."
  value       = module.networking.subnet_id
}

output "security_group_id" {
  description = "Security group ID shared by ECS and RDS for this environment."
  value       = module.networking.security_group_id
}

output "log_group_name" {
  description = "CloudWatch log group for the environment's ECS tasks."
  value       = module.ecs.log_group_name
}
