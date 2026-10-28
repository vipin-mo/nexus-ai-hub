# One Graviton instance in the default VPC running the Docker Compose stack, with Ollama on the host.
# No load balancer, NAT gateway or inbound ports: access is through Session Manager port forwarding,
# and every service binds to 127.0.0.1 on the instance anyway.

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ami" "ubuntu" {
  count       = var.ami_id == "" ? 1 : 0
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*"]
  }
}

locals {
  ami_id = var.ami_id != "" ? var.ami_id : data.aws_ami.ubuntu[0].id
}

resource "aws_security_group" "nexus" {
  name        = "nexus-ai"
  description = "NexusAI demo host: no inbound unless ssh_cidr is set"
  vpc_id      = data.aws_vpc.default.id

  dynamic "ingress" {
    for_each = var.ssh_cidr == "" ? [] : [var.ssh_cidr]
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    description = "Package, model and image downloads; Session Manager"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "nexus" {
  name = "nexus-ai-ec2"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.nexus.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "nexus" {
  name = "nexus-ai-ec2"
  role = aws_iam_role.nexus.name
}

resource "aws_instance" "nexus" {
  ami                    = local.ami_id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.nexus.id]
  # Outbound internet without a NAT gateway; nothing listens on the public address.
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.nexus.name
  key_name                    = var.key_name == "" ? null : var.key_name

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url = var.repo_url
    git_ref  = var.git_ref
  })

  root_block_device {
    volume_type = "gp3"
    volume_size = var.volume_gb
    encrypted   = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  tags = { Name = "nexus-ai" }

  lifecycle {
    # A newer Ubuntu image or an edited bootstrap script must not silently replace the instance
    # (and its databases); taint it to rebuild on purpose.
    ignore_changes = [ami, user_data]
  }
}

resource "aws_budgets_budget" "monthly" {
  count        = var.budget_email == "" ? 0 : 1
  name         = "nexus-ai-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
}
