output "subnet_id" {
  description = "Primary subnet ID, used by the ECS service."
  value       = aws_subnet.env_a.id
}

output "subnet_ids" {
  description = "Both subnets. Needed by resources (like the RDS DB subnet group) that require >= 2 AZs."
  value       = [aws_subnet.env_a.id, aws_subnet.env_b.id]
}

output "security_group_id" {
  description = "Security group shared by ECS and RDS for this environment."
  value       = aws_security_group.env.id
}
