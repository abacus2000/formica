# IAM roles for IRSA. Least-privilege, resource-scoped by env+region.
# Creation is conditional on eks_oidc_provider_arn — skip for local/minikube.

locals {
  create_irsa = var.eks_oidc_provider_arn != "" && var.eks_oidc_provider_url != ""
}

data "aws_caller_identity" "current" {}

# --- OTEL Collector role: write to the S3 bucket for this env+region only.

data "aws_iam_policy_document" "otel_trust" {
  count = local.create_irsa ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_url}:sub"
      values   = ["system:serviceaccount:formica:formica-otel-collector"]
    }
  }
}

resource "aws_iam_role" "otel" {
  count              = local.create_irsa ? 1 : 0
  name               = "formica-otel-${var.env}-${var.region}"
  assume_role_policy = data.aws_iam_policy_document.otel_trust[0].json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "otel_s3" {
  statement {
    actions   = ["s3:PutObject", "s3:PutObjectAcl", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.otel.arn}/*"]
  }
  statement {
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.otel.arn]
  }
}

resource "aws_iam_policy" "otel_s3" {
  name   = "formica-otel-s3-${var.env}-${var.region}"
  policy = data.aws_iam_policy_document.otel_s3.json
}

resource "aws_iam_role_policy_attachment" "otel" {
  count      = local.create_irsa ? 1 : 0
  role       = aws_iam_role.otel[0].name
  policy_arn = aws_iam_policy.otel_s3.arn
}

# --- Fluent Bit role: write to the two env+region log groups only.

data "aws_iam_policy_document" "fluentbit_trust" {
  count = local.create_irsa ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_url}:sub"
      values   = ["system:serviceaccount:formica:fluent-bit"]
    }
  }
}

resource "aws_iam_role" "fluentbit" {
  count              = local.create_irsa ? 1 : 0
  name               = "formica-fluentbit-${var.env}-${var.region}"
  assume_role_policy = data.aws_iam_policy_document.fluentbit_trust[0].json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "fluentbit_cw" {
  statement {
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
      "logs:DescribeLogGroups",
    ]
    resources = [
      "${aws_cloudwatch_log_group.errors.arn}:*",
      "${aws_cloudwatch_log_group.drivers.arn}:*",
      aws_cloudwatch_log_group.errors.arn,
      aws_cloudwatch_log_group.drivers.arn,
    ]
  }
}

resource "aws_iam_policy" "fluentbit_cw" {
  name   = "formica-fluentbit-cw-${var.env}-${var.region}"
  policy = data.aws_iam_policy_document.fluentbit_cw.json
}

resource "aws_iam_role_policy_attachment" "fluentbit" {
  count      = local.create_irsa ? 1 : 0
  role       = aws_iam_role.fluentbit[0].name
  policy_arn = aws_iam_policy.fluentbit_cw.arn
}

# --- Controller role: read-only to Kubernetes (via cluster RBAC); no AWS privs.
# --- Agent role: call ssm:SendCommand on existing instances ONLY. No RunInstances.

data "aws_iam_policy_document" "agent_trust" {
  count = local.create_irsa ? 1 : 0
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_url}:sub"
      values   = ["system:serviceaccount:formica:formica-agent"]
    }
  }
}

resource "aws_iam_role" "agent" {
  count              = local.create_irsa ? 1 : 0
  name               = "formica-agent-${var.env}-${var.region}"
  assume_role_policy = data.aws_iam_policy_document.agent_trust[0].json
  tags               = local.common_tags
}

data "aws_iam_policy_document" "agent_ssm" {
  # Explicitly no ec2:RunInstances, ec2:CreateFleet, or eks:UpdateNodegroupConfig.
  statement {
    actions = [
      "ssm:SendCommand",
      "ssm:GetCommandInvocation",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/formica:env"
      values   = [var.env]
    }
  }
  # Deny any provisioning calls — defense in depth.
  statement {
    effect = "Deny"
    actions = [
      "ec2:RunInstances",
      "ec2:CreateFleet",
      "ec2:CreateLaunchTemplate",
      "ec2:ModifyInstanceCapacityReservationAttributes",
      "eks:UpdateNodegroupConfig",
      "eks:CreateNodegroup",
      "autoscaling:SetDesiredCapacity",
      "autoscaling:UpdateAutoScalingGroup",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "agent_ssm" {
  name   = "formica-agent-ssm-${var.env}-${var.region}"
  policy = data.aws_iam_policy_document.agent_ssm.json
}

resource "aws_iam_role_policy_attachment" "agent" {
  count      = local.create_irsa ? 1 : 0
  role       = aws_iam_role.agent[0].name
  policy_arn = aws_iam_policy.agent_ssm.arn
}
