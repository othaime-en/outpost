output "instance_id" {
  description = "EC2 instance ID — connect with: aws ssm start-session --target <id>"
  value       = aws_instance.api_host.id
}

output "elastic_ip" {
  description = "Public IP — point outpost-api.othaimeen.dev's A record here"
  value       = aws_eip.api_host.public_ip
}

output "security_group_id" {
  value = aws_security_group.api_host.id
}
