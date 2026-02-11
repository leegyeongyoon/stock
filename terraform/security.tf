# Security Group for Stock Trading Services
# 기존 보안 그룹은 포트 80만 허용하므로, 추가 포트용 보안 그룹 생성

# 기존 ALB 보안 그룹 참조
data "aws_security_group" "alb" {
  name   = "honbabnono-alb-sg"
  vpc_id = local.vpc_id
}

# Stock Trading 전용 보안 그룹
resource "aws_security_group" "stock_ecs" {
  name        = "${local.resource_prefix}-ecs-sg"
  description = "Security group for Stock Trading ECS tasks"
  vpc_id      = local.vpc_id

  # Backend (FastAPI) - 포트 8088
  ingress {
    from_port       = 8088
    to_port         = 8088
    protocol        = "tcp"
    security_groups = [data.aws_security_group.alb.id]
    description     = "Allow inbound from ALB to Backend"
  }

  # Frontend (Next.js) - 포트 3000
  ingress {
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [data.aws_security_group.alb.id]
    description     = "Allow inbound from ALB to Frontend"
  }

  # Outbound - 모든 트래픽 허용 (외부 API 호출, DB 연결 등)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound traffic"
  }

  tags = {
    Name        = "${local.resource_prefix}-ecs-sg"
    Environment = var.environment
  }
}
