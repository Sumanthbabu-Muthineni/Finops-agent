terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Primary provider: ap-south-1 (Mumbai)
provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "TBX-FinOps-Hackathon"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Secondary provider for CloudFront global resources if required
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}
