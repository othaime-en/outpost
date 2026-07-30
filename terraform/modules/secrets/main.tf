resource "aws_secretsmanager_secret" "rds" {
  name        = "idp-lite/${var.env_id}/rds"
  description = "RDS credentials for environment ${var.env_id}"
  tags        = var.common_tags
}

resource "aws_secretsmanager_secret_version" "rds" {
  secret_id = aws_secretsmanager_secret.rds.id
  secret_string = jsonencode({
    host     = var.rds_address
    port     = var.rds_port
    dbname   = "appdb"
    username = var.rds_username
    password = var.rds_password
    # DEVIATION FROM PLAN: the plan's ECS module injected this whole secret
    # directly as DATABASE_URL (`valueFrom = var.rds_secret_arn`), which
    # would hand the container the entire JSON blob, not a connection
    # string. The `url` key here is the one the ECS module actually
    # references via the `secret-arn:json-key::` syntax.
    url = "postgresql://${var.rds_username}:${var.rds_password}@${var.rds_address}:${var.rds_port}/appdb"
  })
}
