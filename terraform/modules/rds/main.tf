resource "random_password" "db" {
  length  = 32
  special = false # avoid characters that need extra escaping in connection URLs / shell
}

resource "aws_db_subnet_group" "env" {
  name       = "outpost-${var.env_id}"
  subnet_ids = var.subnet_ids
  tags       = var.common_tags
}

resource "aws_db_instance" "env" {
  identifier     = "outpost-${substr(var.env_id, 0, 8)}"
  engine         = "postgres"
  engine_version = "15.4"
  instance_class = "db.t3.micro"

  allocated_storage = 20
  db_name           = "appdb"
  username          = "appuser"
  password          = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.env.name
  vpc_security_group_ids = [var.security_group_id]
  publicly_accessible    = false

  # Ephemeral, disposable environments -- no snapshot to manage/clean up,
  # and destroy must be able to remove the instance without manual steps.
  skip_final_snapshot = true
  deletion_protection = false

  tags = var.common_tags
}
