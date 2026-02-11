# SSL Certificate for Stock Trading subdomains
# stock.honbabnono.com, stock-api.honbabnono.com

# 새 ACM 인증서 생성 (stock 서브도메인용)
resource "aws_acm_certificate" "stock" {
  domain_name               = "stock.honbabnono.com"
  subject_alternative_names = ["stock-api.honbabnono.com"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name        = "${local.resource_prefix}-cert"
    Environment = var.environment
  }
}

# DNS 검증 레코드
resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.stock.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.main.zone_id
}

# 인증서 검증 완료 대기
resource "aws_acm_certificate_validation" "stock" {
  certificate_arn         = aws_acm_certificate.stock.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

# HTTPS 리스너에 인증서 추가
resource "aws_lb_listener_certificate" "stock" {
  listener_arn    = data.aws_lb_listener.https.arn
  certificate_arn = aws_acm_certificate_validation.stock.certificate_arn
}
