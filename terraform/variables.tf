# Stock Auto-Trading Variables

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "ap-northeast-2"
}

variable "app_name" {
  description = "Application name"
  type        = string
  default     = "stock-trading"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

# ECS 리소스 설정
variable "backend_cpu" {
  description = "Backend Fargate CPU units"
  type        = string
  default     = "512"
}

variable "backend_memory" {
  description = "Backend Fargate memory (MiB)"
  type        = string
  default     = "1024"
}

variable "frontend_cpu" {
  description = "Frontend Fargate CPU units"
  type        = string
  default     = "256"
}

variable "frontend_memory" {
  description = "Frontend Fargate memory (MiB)"
  type        = string
  default     = "512"
}

# 서브도메인 설정
variable "subdomain" {
  description = "Subdomain for stock trading dashboard"
  type        = string
  default     = "stock"
}

# 환경 변수 (민감한 정보는 AWS Secrets Manager 또는 Parameter Store 사용 권장)
variable "database_url" {
  description = "PostgreSQL database URL"
  type        = string
  sensitive   = true
}

variable "kis_app_key" {
  description = "KIS API App Key"
  type        = string
  sensitive   = true
  default     = ""
}

variable "kis_app_secret" {
  description = "KIS API App Secret"
  type        = string
  sensitive   = true
  default     = ""
}

variable "kis_account_no" {
  description = "KIS Account Number"
  type        = string
  sensitive   = true
  default     = ""
}

variable "kis_is_mock" {
  description = "KIS Mock Trading Mode"
  type        = string
  default     = "true"
}

variable "openai_api_key" {
  description = "OpenAI API Key"
  type        = string
  sensitive   = true
  default     = ""
}

# 로깅 설정
variable "enable_logging" {
  description = "Enable CloudWatch logging (set to false to save $1-2/month)"
  type        = bool
  default     = true  # 디버깅 위해 기본 활성화, false로 바꾸면 로그 비용 $0
}
