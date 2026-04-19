output "s3_otel_bucket"      { value = aws_s3_bucket.otel.bucket }
output "cloudwatch_errors"   { value = aws_cloudwatch_log_group.errors.name }
output "cloudwatch_drivers"  { value = aws_cloudwatch_log_group.drivers.name }
output "sns_alerts_topic"    { value = aws_sns_topic.alerts.arn }
output "glue_database"       { value = local.glue_database }
output "agent_role_arn"      { value = try(aws_iam_role.agent[0].arn, null) }
output "otel_role_arn"       { value = try(aws_iam_role.otel[0].arn, null) }
output "fluentbit_role_arn"  { value = try(aws_iam_role.fluentbit[0].arn, null) }
