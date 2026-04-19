terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = ">= 5.0" }
  }
}

provider "aws" {
  region = var.region
}

locals {
  name_prefix    = "formica-${var.env}-${var.region}"
  otel_bucket    = "formica-otel-${var.env}-${var.region}"
  glue_database  = replace("formica_otel_${var.env}_${var.region}", "-", "_")
  errors_group   = "/formica/${var.env}/${var.region}/errors"
  drivers_group  = "/formica/${var.env}/${var.region}/drivers"
  alerts_topic   = "formica-${var.env}-${var.region}-alerts"

  common_tags = {
    "formica:env"    = var.env
    "formica:region" = var.region
    "formica:app"    = "formica"
  }
}

# --------------------- S3 (OTEL) ---------------------

resource "aws_s3_bucket" "otel" {
  bucket = local.otel_bucket
  tags   = local.common_tags
}

resource "aws_s3_bucket_public_access_block" "otel" {
  bucket                  = aws_s3_bucket.otel.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "otel" {
  bucket = aws_s3_bucket.otel.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "otel" {
  bucket = aws_s3_bucket.otel.id
  rule {
    id     = "expire-old-logs"
    status = "Enabled"
    expiration {
      days = var.env == "prod" ? 365 : 90
    }
  }
}

# --------------------- CloudWatch log groups ---------------------

resource "aws_cloudwatch_log_group" "errors" {
  name              = local.errors_group
  retention_in_days = var.retention_days
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "drivers" {
  name              = local.drivers_group
  retention_in_days = var.retention_days
  tags              = local.common_tags
}

# --------------------- SNS alerts ---------------------

resource "aws_sns_topic" "alerts" {
  name = local.alerts_topic
  tags = local.common_tags
}

# Metric-filter on error count.
resource "aws_cloudwatch_log_metric_filter" "error_rate" {
  name           = "${local.name_prefix}-error-rate"
  log_group_name = aws_cloudwatch_log_group.errors.name
  pattern        = "{ ($.level = \"ERROR\") || ($.level = \"CRITICAL\") }"
  metric_transformation {
    name      = "${local.name_prefix}-error-rate"
    namespace = "Formica/${var.env}/${var.region}"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "error_spike" {
  alarm_name          = "${local.name_prefix}-error-spike"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "${local.name_prefix}-error-rate"
  namespace           = "Formica/${var.env}/${var.region}"
  period              = 300
  statistic           = "Sum"
  threshold           = 20
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  tags                = local.common_tags
}
