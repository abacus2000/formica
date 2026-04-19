variable "env" {
  type        = string
  description = "Deployment environment (dev, prod, ...). Used in resource names."
}

variable "region" {
  type        = string
  description = "AWS region for all resources."
}

variable "retention_days" {
  type        = number
  description = "CloudWatch log retention. Default 30 for dev, 180 for prod."
  default     = 30
}

variable "eks_oidc_provider_arn" {
  type        = string
  description = "ARN of the EKS OIDC provider (for IRSA). Leave empty to skip IAM role creation."
  default     = ""
}

variable "eks_oidc_provider_url" {
  type        = string
  description = "URL (without https://) of the EKS OIDC provider."
  default     = ""
}
