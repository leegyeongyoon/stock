# ECS Services for Stock Trading

# ============================================
# CloudWatch Log Groups (1일 보관 - 비용 최소화)
# ============================================

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.resource_prefix}-backend"
  retention_in_days = 1

  tags = {
    Name        = "${local.resource_prefix}-backend-logs"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.resource_prefix}-frontend"
  retention_in_days = 1

  tags = {
    Name        = "${local.resource_prefix}-frontend-logs"
    Environment = var.environment
  }
}

# ============================================
# Backend Task Definition (FastAPI)
# ============================================

resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.resource_prefix}-backend-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = data.aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = data.aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name  = "${local.resource_prefix}-backend"
      image = "${aws_ecr_repository.backend.repository_url}:latest"

      portMappings = [
        {
          containerPort = 8088
          hostPort      = 8088
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "DATABASE_URL"
          value = var.database_url
        },
        {
          name  = "KIS_APP_KEY"
          value = var.kis_app_key
        },
        {
          name  = "KIS_APP_SECRET"
          value = var.kis_app_secret
        },
        {
          name  = "KIS_ACCOUNT_NO"
          value = var.kis_account_no
        },
        {
          name  = "KIS_IS_MOCK"
          value = var.kis_is_mock
        },
        {
          name  = "OPENAI_API_KEY"
          value = var.openai_api_key
        },
        {
          name  = "LOG_LEVEL"
          value = "INFO"
        },
        {
          name  = "MAX_POSITION_SIZE"
          value = "0.1"
        },
        {
          name  = "MAX_DAILY_LOSS"
          value = "0.03"
        },
        {
          name  = "MAX_POSITIONS"
          value = "10"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.backend.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name        = "${local.resource_prefix}-backend-task"
    Environment = var.environment
  }
}

# ============================================
# Frontend Task Definition (Next.js)
# ============================================

resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.resource_prefix}-frontend-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = data.aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = data.aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name  = "${local.resource_prefix}-frontend"
      image = "${aws_ecr_repository.frontend.repository_url}:latest"

      portMappings = [
        {
          containerPort = 3000
          hostPort      = 3000
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "NEXT_PUBLIC_API_URL"
          value = "https://stock-api.honbabnono.com"
        },
        {
          name  = "NEXT_PUBLIC_WS_URL"
          value = "wss://stock-api.honbabnono.com"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name        = "${local.resource_prefix}-frontend-task"
    Environment = var.environment
  }
}

# ============================================
# Backend ECS Service
# ============================================

resource "aws_ecs_service" "backend" {
  name            = "${local.resource_prefix}-backend-service"
  cluster         = data.aws_ecs_cluster.honbabnono.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 1

  # Fargate Spot으로 70% 비용 절감
  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 100
    base              = 0
  }

  network_configuration {
    security_groups  = [aws_security_group.stock_ecs.id]
    subnets          = local.subnet_ids
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.id
    container_name   = "${local.resource_prefix}-backend"
    container_port   = 8088
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 50
  health_check_grace_period_seconds  = 300

  depends_on = [
    aws_lb_target_group.backend
  ]

  tags = {
    Name        = "${local.resource_prefix}-backend-service"
    Environment = var.environment
  }
}

# ============================================
# Frontend ECS Service
# ============================================

resource "aws_ecs_service" "frontend" {
  name            = "${local.resource_prefix}-frontend-service"
  cluster         = data.aws_ecs_cluster.honbabnono.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = 1

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 100
    base              = 0
  }

  network_configuration {
    security_groups  = [aws_security_group.stock_ecs.id]
    subnets          = local.subnet_ids
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.id
    container_name   = "${local.resource_prefix}-frontend"
    container_port   = 3000
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 50
  health_check_grace_period_seconds  = 300

  depends_on = [
    aws_lb_target_group.frontend
  ]

  tags = {
    Name        = "${local.resource_prefix}-frontend-service"
    Environment = var.environment
  }
}
