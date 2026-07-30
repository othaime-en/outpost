output "endpoint" {
  description = "host:port endpoint."
  value       = aws_db_instance.env.endpoint
}

output "address" {
  description = "Hostname only (no port) -- used by the secrets module so the port isn't embedded twice."
  value       = aws_db_instance.env.address
}

output "username" {
  value = aws_db_instance.env.username
}

output "password" {
  value     = random_password.db.result
  sensitive = true
}
