# Terraform Backend Configuration
# S3 backend을 사용하려면 아래 주석을 해제하세요

# terraform {
#   backend "s3" {
#     bucket         = "honbabnono-terraform-state"
#     key            = "stock-trading/terraform.tfstate"
#     region         = "ap-northeast-2"
#     encrypt        = true
#     dynamodb_table = "terraform-state-lock"
#   }
# }

# 현재는 로컬 state 사용 (GitHub Actions에서 관리)
# CI/CD에서는 매번 terraform init/apply 실행
