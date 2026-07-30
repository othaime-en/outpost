output "service_arn" {
  value = aws_ecs_service.env.id
}

output "cluster_arn" {
  value = data.aws_ecs_cluster.shared.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.env.name
}
