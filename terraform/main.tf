# Stock Auto-Trading Terraform
# 기존 honbabnono 인프라를 재사용하여 비용 최소화

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  resource_prefix = var.app_name
}

# ============================================
# 기존 인프라 참조 (honbabnono에서 생성됨)
# ============================================

# 기존 VPC 찾기
data "aws_vpcs" "available" {}

locals {
  vpc_id = data.aws_vpcs.available.ids[0]
}

# 기존 서브넷 찾기
data "aws_subnets" "available" {
  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }
}

locals {
  subnet_ids = data.aws_subnets.available.ids
}

# 기존 ECS 클러스터 참조
data "aws_ecs_cluster" "honbabnono" {
  cluster_name = "honbabnono-cluster"
}

# 기존 ALB 참조
data "aws_lb" "honbabnono" {
  name = "honbabnono-alb"
}

# 기존 HTTPS 리스너 참조
data "aws_lb_listener" "https" {
  load_balancer_arn = data.aws_lb.honbabnono.arn
  port              = 443
}

# 기존 ECS 태스크 실행 역할 참조
data "aws_iam_role" "ecs_task_execution_role" {
  name = "honbabnono-ecs-task-execution-role"
}

# 기존 ECS 태스크 역할 참조
data "aws_iam_role" "ecs_task_role" {
  name = "honbabnono-ecs-task-role"
}

# 기존 ECS 보안 그룹 참조
data "aws_security_group" "ecs_tasks" {
  name   = "honbabnono-ecs-tasks-sg"
  vpc_id = local.vpc_id
}

# Route 53 호스팅 존 참조
data "aws_route53_zone" "main" {
  name = "honbabnono.com"
}
