variable "aws_region" {
  description = "AWS region for primary hosting (Mumbai)"
  type        = string
  default     = "ap-south-1"
}

variable "bedrock_region" {
  description = "AWS region for Bedrock Llama 3.1 8B invocation"
  type        = string
  default     = "us-east-1"
}

variable "app_name" {
  description = "Application name prefix for all AWS resources"
  type        = string
  default     = "finops-assistant"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "container_cpu" {
  description = "Fargate CPU units (512 = 0.5 vCPU)"
  type        = number
  default     = 512
}

variable "container_memory" {
  description = "Fargate Memory (1024 = 1 GB)"
  type        = number
  default     = 1024
}

variable "min_capacity" {
  description = "Minimum number of auto-scaled backend tasks"
  type        = number
  default     = 1
}

variable "max_capacity" {
  description = "Maximum number of auto-scaled backend tasks under load"
  type        = number
  default     = 5
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "tiby_hackathon"
}

variable "db_user" {
  description = "Database master username"
  type        = string
  default     = "tiby"
}

variable "db_password" {
  description = "Database master password"
  type        = string
  sensitive   = true
  default     = ""
}
