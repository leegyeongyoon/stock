# Outputs for Stock Trading

output "dashboard_url" {
  value       = "https://stock.honbabnono.com"
  description = "Stock Trading Dashboard URL"
}

output "api_url" {
  value       = "https://stock-api.honbabnono.com"
  description = "Stock Trading API URL"
}

output "api_docs_url" {
  value       = "https://stock-api.honbabnono.com/docs"
  description = "Stock Trading API Documentation (Swagger)"
}

output "ecr_backend_url" {
  value       = aws_ecr_repository.backend.repository_url
  description = "Backend ECR Repository URL"
}

output "ecr_frontend_url" {
  value       = aws_ecr_repository.frontend.repository_url
  description = "Frontend ECR Repository URL"
}

output "ecs_cluster_name" {
  value       = data.aws_ecs_cluster.honbabnono.cluster_name
  description = "ECS Cluster Name (shared with honbabnono)"
}

output "backend_service_name" {
  value       = aws_ecs_service.backend.name
  description = "Backend ECS Service Name"
}

output "frontend_service_name" {
  value       = aws_ecs_service.frontend.name
  description = "Frontend ECS Service Name"
}

# 비용 예측
output "estimated_monthly_cost" {
  value = {
    ecs_fargate_spot = {
      backend  = "$3-5/월 (256 CPU, 512MB, Spot 70% 할인)"
      frontend = "$3-5/월 (256 CPU, 512MB, Spot 70% 할인)"
    }
    cloudwatch_logs = "$1-2/월 (1일 보관)"
    ecr_storage     = "< $1/월"
    total           = "$7-13/월 추가"
    note            = "기존 ALB, VPC, ECS 클러스터 재사용으로 비용 최소화"
  }
  description = "Estimated monthly cost for stock trading services"
}
