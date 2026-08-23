# References the shared ECS cluster, created once during bootstrap
# (Section 2.1: `aws ecs create-cluster --cluster-name outpost-shared`).
# One cluster hosts every environment's service, namespaced by env_id.
data "aws_ecs_cluster" "shared" {
  cluster_name = "outpost-shared"
}

resource "aws_cloudwatch_log_group" "env" {
  name              = "/outpost/${var.env_id}"
  retention_in_days = 7
  tags              = var.common_tags
}

resource "aws_iam_role" "task" {
  name = "outpost-task-${var.env_id}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })

  tags = var.common_tags
}

# DEVIATION FROM PLAN: the plan attached only the custom secrets policy
# below to this role and used it as both the execution role and task role.
# Without base execution permissions (ECR pull, CloudWatch Logs
# CreateLogStream/PutLogEvents), the Fargate task would never successfully
# start -- it would sit in a pull/log-config failure loop. This attaches
# AWS's managed execution policy to cover that, while keeping the plan's
# single-role-for-both approach (simple, and fine for a dev/staging
# workload with no need to separate task vs execution permissions).
resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_secrets" {
  name = "secrets-access"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = [var.rds_secret_arn] # scoped to this env's secret only
    }]
  })
}

resource "aws_ecs_task_definition" "env" {
  family                   = "outpost-${var.env_id}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name  = "app"
    image = var.container_image
    portMappings = [{
      containerPort = 8080
      protocol      = "tcp"
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.env.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "app"
      }
    }
    secrets = [{
      name = "DATABASE_URL"
      # DEVIATION FROM PLAN: was `valueFrom = var.rds_secret_arn`, which
      # injects the *entire* JSON secret as the env var value. The
      # `secret-arn:json-key::` suffix tells ECS to extract just the "url"
      # key from the JSON the secrets module wrote.
      valueFrom = "${var.rds_secret_arn}:url::"
    }]
  }])

  tags = var.common_tags
}

resource "aws_ecs_service" "env" {
  name            = "outpost-${var.env_id}"
  cluster         = data.aws_ecs_cluster.shared.id
  task_definition = aws_ecs_task_definition.env.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = [var.subnet_id]
    security_groups  = [var.security_group_id]
    assign_public_ip = true
  }

  # Make sure the execution role can actually resolve the secret before the
  # service starts trying to place tasks.
  depends_on = [aws_iam_role_policy.task_secrets]

  tags = var.common_tags
}
