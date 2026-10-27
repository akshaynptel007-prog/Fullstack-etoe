# Edge protection, evaluated at CloudFront POPs before traffic reaches AWS
# origin capacity: per-IP rate limits (stricter on checkout), IP reputation,
# known-bad inputs, OWASP common rules and (optionally) Bot Control.
resource "aws_wafv2_web_acl" "this" {
  count    = var.enable_waf ? 1 : 0
  provider = aws.us_east_1
  name     = var.name
  scope    = "CLOUDFRONT"

  default_action {
    allow {}
  }

  custom_response_body {
    key          = "rate_limited"
    content_type = "APPLICATION_JSON"
    content      = jsonencode({ error = { code = "RATE_LIMITED", message = "Too many requests - please retry shortly." } })
  }

  rule {
    name     = "checkout-rate-per-ip"
    priority = 1

    action {
      block {
        custom_response {
          response_code            = 429
          custom_response_body_key = "rate_limited"
          response_header {
            name  = "Retry-After"
            value = "10"
          }
        }
      }
    }

    statement {
      rate_based_statement {
        limit                 = var.waf_checkout_rate_limit_per_ip
        evaluation_window_sec = 60
        aggregate_key_type    = "IP"

        scope_down_statement {
          byte_match_statement {
            search_string         = "/checkout"
            positional_constraint = "ENDS_WITH"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name}-checkout-rate"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "global-rate-per-ip"
    priority = 2

    action {
      block {
        custom_response {
          response_code            = 429
          custom_response_body_key = "rate_limited"
          response_header {
            name  = "Retry-After"
            value = "30"
          }
        }
      }
    }

    statement {
      rate_based_statement {
        limit                 = var.waf_rate_limit_per_ip
        evaluation_window_sec = 60
        aggregate_key_type    = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name}-global-rate"
      sampled_requests_enabled   = true
    }
  }

  dynamic "rule" {
    for_each = concat(
      [
        { name = "AWSManagedRulesAmazonIpReputationList", priority = 10 },
        { name = "AWSManagedRulesKnownBadInputsRuleSet", priority = 11 },
        { name = "AWSManagedRulesCommonRuleSet", priority = 12 },
      ],
      var.enable_bot_control ? [{ name = "AWSManagedRulesBotControlRuleSet", priority = 13 }] : [],
    )
    content {
      name     = rule.value.name
      priority = rule.value.priority

      override_action {
        none {}
      }

      statement {
        managed_rule_group_statement {
          vendor_name = "AWS"
          name        = rule.value.name

          dynamic "managed_rule_group_configs" {
            for_each = rule.value.name == "AWSManagedRulesBotControlRuleSet" ? [1] : []
            content {
              aws_managed_rules_bot_control_rule_set {
                inspection_level = "COMMON"
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name}-${rule.value.name}"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = var.name
    sampled_requests_enabled   = true
  }
}
