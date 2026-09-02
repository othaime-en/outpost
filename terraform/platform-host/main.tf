provider "aws" {
  region = var.aws_region
}

# Latest Amazon Linux 2023 AMI (x86_64) via SSM public parameter — avoids a
# hardcoded AMI ID going stale; SSM Agent ships preinstalled on AL2023.
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# --- Security group: HTTP/HTTPS only. No SSH port — access is via SSM Session Manager. ---
resource "aws_security_group" "api_host" {
  name        = "${var.name_prefix}-sg"
  description = "Outpost platform API host — HTTP/HTTPS only, no SSH"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTP (Caddy ACME challenge + redirect to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.name_prefix}-sg"
    Project = "outpost"
  }
}

# --- IAM role + instance profile for SSM Session Manager (no SSH key pair needed) ---
resource "aws_iam_role" "api_host" {
  name = "${var.name_prefix}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = "outpost" }
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.api_host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "api_host" {
  name = "${var.name_prefix}-instance-profile"
  role = aws_iam_role.api_host.name
}

# --- EC2 instance ---
resource "aws_instance" "api_host" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.instance_type
  subnet_id              = var.public_subnet_id
  vpc_security_group_ids = [aws_security_group.api_host.id]
  iam_instance_profile   = aws_iam_instance_profile.api_host.name

  # Needed at launch so the instance can reach the internet (dnf/docker install)
  # before the Elastic IP associates.
  associate_public_ip_address = true

  root_block_device {
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = file("${path.module}/user_data.sh")

  tags = {
    Name    = "${var.name_prefix}-host"
    Project = "outpost"
  }

  lifecycle {
    # App deploys happen via SSM afterward, not by replacing the instance
    # every time the AMI parameter drifts.
    ignore_changes = [ami]
  }
}

# --- Elastic IP: stable address for the outpost-api.othaimeen.dev A record ---
resource "aws_eip" "api_host" {
  instance = aws_instance.api_host.id
  domain   = "vpc"

  tags = {
    Name    = "${var.name_prefix}-eip"
    Project = "outpost"
  }
}