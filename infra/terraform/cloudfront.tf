# HTTPS front door for the app, with no domain to buy.
#
# Why: Cognito only accepts https:// callback URLs (http:// only for
# localhost), and the ALB behind the Ingress is HTTP-only with an AWS-made
# hostname. Every CloudFront distribution gets a free
# https://<id>.cloudfront.net address with an AWS-managed certificate, so
# putting one in front of the ALB gives the app a real HTTPS URL that Cognito
# will redirect back to. Terraform registers that URL on the Cognito client
# (see local.frontend_origins in cognito.tf).
#
#   browser --HTTPS--> CloudFront --HTTP--> ALB --> /api -> API, / -> frontend
#
# The CloudFront -> ALB hop is plain HTTP (the ALB has no certificate). That is
# acceptable for a synthetic-data demo; the API still requires a Cognito ID
# token on every call. A custom domain + ACM certificate on the ALB would make
# that hop HTTPS too (see k8s/ingress.yaml).
#
# Enabled only when var.alb_dns_name is set, because the ALB is created by the
# Kubernetes Ingress, not by Terraform:
#   export TF_VAR_alb_dns_name=$(kubectl -n claimpilot get ingress claimpilot \
#     -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')

variable "alb_dns_name" {
  description = "DNS name of the ALB the Ingress created (kubectl get ingress). Empty = no CloudFront distribution."
  type        = string
  default     = ""
}

locals {
  cloudfront_enabled = var.alb_dns_name != ""
  cloudfront_url     = local.cloudfront_enabled ? "https://${try(aws_cloudfront_distribution.frontend[0].domain_name, "")}" : ""
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# Forwards every viewer header (including Authorization, which carries the
# Cognito ID token) and all query strings to the origin, except Host.
data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

resource "aws_cloudfront_distribution" "frontend" {
  count = local.cloudfront_enabled ? 1 : 0

  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.project_name} app (frontend + /api) in front of the Ingress ALB"
  # All edge locations: PriceClass_100/200 leave out Australia, where the users are.
  price_class = "PriceClass_All"

  origin {
    origin_id   = "alb"
    domain_name = var.alb_dns_name

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      # 60s is the default maximum. CloudFront's default (30s) is too short for
      # a triage call that does a retry (Bedrock + OpenSearch, twice).
      origin_read_timeout      = 60
      origin_keepalive_timeout = 5
    }
  }

  # Default: nothing cached. Covers the HTML shell, /config.js and every
  # /api call (including POST /api/claims/{id}/triage).
  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    compress                 = true
  }

  # Vite's hashed build files never change under the same name, so cache them.
  ordered_cache_behavior {
    path_pattern           = "/assets/*"
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = {
    Name = "${var.project_name}-cloudfront"
  }
}

output "app_url" {
  description = "HTTPS URL of the deployed app (CloudFront). Sign in here - no port-forward needed."
  value       = local.cloudfront_enabled ? local.cloudfront_url : "not enabled: set TF_VAR_alb_dns_name"
}
