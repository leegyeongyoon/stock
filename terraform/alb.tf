# ALB Target Groups and Listener Rules for Stock Trading
# 기존 honbabnono ALB를 재사용

# ============================================
# Target Groups
# ============================================

# Backend Target Group (FastAPI - 포트 8088)
resource "aws_lb_target_group" "backend" {
  name        = "${local.resource_prefix}-backend-tg"
  port        = 8088
  protocol    = "HTTP"
  vpc_id      = local.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 60
    matcher             = "200"
    path                = "/api/system/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 30
    unhealthy_threshold = 5
  }

  tags = {
    Name        = "${local.resource_prefix}-backend-tg"
    Environment = var.environment
  }
}

# Frontend Target Group (Next.js - 포트 3000)
resource "aws_lb_target_group" "frontend" {
  name        = "${local.resource_prefix}-frontend-tg"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = local.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 60
    matcher             = "200,301,302"
    path                = "/"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 30
    unhealthy_threshold = 5
  }

  tags = {
    Name        = "${local.resource_prefix}-frontend-tg"
    Environment = var.environment
  }
}

# ============================================
# HTTPS Listener Rules (기존 ALB에 규칙 추가)
# ============================================

# Backend API 라우팅 (stock-api.honbabnono.com)
resource "aws_lb_listener_rule" "backend" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 110

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    host_header {
      values = ["stock-api.honbabnono.com"]
    }
  }
}

# Frontend 라우팅 (stock.honbabnono.com)
resource "aws_lb_listener_rule" "frontend" {
  listener_arn = data.aws_lb_listener.https.arn
  priority     = 111

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }

  condition {
    host_header {
      values = ["stock.honbabnono.com"]
    }
  }
}

# ============================================
# Route 53 Records
# ============================================

# stock.honbabnono.com -> ALB (Frontend)
resource "aws_route53_record" "frontend" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "stock.honbabnono.com"
  type    = "A"

  alias {
    name                   = data.aws_lb.honbabnono.dns_name
    zone_id                = data.aws_lb.honbabnono.zone_id
    evaluate_target_health = false
  }
}

# stock-api.honbabnono.com -> ALB (Backend)
resource "aws_route53_record" "backend" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "stock-api.honbabnono.com"
  type    = "A"

  alias {
    name                   = data.aws_lb.honbabnono.dns_name
    zone_id                = data.aws_lb.honbabnono.zone_id
    evaluate_target_health = false
  }
}
