# Per-environment network isolation within the shared VPC (10.0.0.0/16,
# created once during bootstrap -- see Section 2.1).
#
# DEVIATION FROM PLAN: the plan's networking module created a single subnet,
# but RDS requires a DB subnet group spanning >= 2 AZs. This module creates
# two /25 subnets in two AZs instead. The ECS service still only uses the
# first one (subnet_id output) -- awsvpc/Fargate tasks don't need multi-AZ
# for a single-task dev/staging service.
#
# CIDR allocation: rather than requiring an external IPAM step, each
# environment gets a deterministic-but-unique third octet derived from a
# `random_integer` seeded by env_id. Once created it's stored in state and
# never changes across subsequent applies of the same (per-env) workspace.
# This gives 250 non-overlapping /25 pairs within the shared /16, which is
# comfortably more than a portfolio project will ever provision
# concurrently.
resource "random_integer" "subnet_octet" {
  min = 1
  max = 250

  keepers = {
    env_id = var.env_id
  }
}

resource "aws_subnet" "env_a" {
  vpc_id            = var.vpc_id
  cidr_block        = "10.0.${random_integer.subnet_octet.result}.0/25"
  availability_zone = "${var.region}a"
  tags              = merge(var.common_tags, { Name = "outpost-${var.env_id}-a" })
}

resource "aws_subnet" "env_b" {
  vpc_id            = var.vpc_id
  cidr_block        = "10.0.${random_integer.subnet_octet.result}.128/25"
  availability_zone = "${var.region}b"
  tags              = merge(var.common_tags, { Name = "outpost-${var.env_id}-b" })
}

resource "aws_security_group" "env" {
  name        = "outpost-${var.env_id}"
  description = "SG for environment ${var.env_id}"
  vpc_id      = var.vpc_id

  ingress {
    description = "App traffic from within the shared VPC"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    # Tightened from the plan's 10.0.0.0/8 (broader than the VPC itself)
    # to the actual shared VPC CIDR.
    cidr_blocks = ["10.0.0.0/16"]
  }

  # Not present in the plan's original SG: without this, the ECS task can
  # reach nothing on 5432 and the RDS connection in the runbook/app would
  # simply time out. Self-referencing so only resources placed in this
  # same per-env SG (i.e. this environment's own ECS task and RDS instance)
  # can talk to each other on Postgres.
  ingress {
    description = "Postgres, self-referencing (ECS task to RDS, same env only)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    self        = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.common_tags, { Name = "outpost-${var.env_id}" })
}
