#!/usr/bin/env bash
set -e

# ==============================================================================
# TBX FinOps Assistant - Automated AWS Production Deployment Script
# ==============================================================================

REGION="ap-south-1"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "================================================================="
echo "🚀 STARTING AUTOMATED AWS DEPLOYMENT FOR FINOPS ASSISTANT"
echo "   Region: ${REGION} (Mumbai)"
echo "   Model:  Meta Llama 3.1 8B via AWS Bedrock"
echo "================================================================="

# 1. Check Prerequisites
echo -e "\n[1/6] Checking Prerequisites..."
if ! command -v aws &> /dev/null; then echo "❌ AWS CLI not found!"; exit 1; fi
if ! command -v terraform &> /dev/null; then echo "❌ Terraform not found!"; exit 1; fi
if ! command -v docker &> /dev/null; then echo "❌ Docker not found!"; exit 1; fi

CALLER_IDENTITY=$(aws sts get-caller-identity)
echo "✅ Authenticated as: $(echo "$CALLER_IDENTITY" | grep -o '"Arn": "[^"]*' | cut -d'"' -f4)"

# 2. Build Frontend Production Bundle
echo -e "\n[2/6] Building React Frontend..."
cd "${PROJECT_ROOT}/frontend"
npm run build
cd "${PROJECT_ROOT}"
echo "✅ Frontend build complete in frontend/dist/"

# 3. Initialize Terraform & Provision ECR
echo -e "\n[3/6] Initializing Terraform & ECR..."
cd "${PROJECT_ROOT}/terraform"
terraform init
terraform apply -target=aws_ecr_repository.backend -auto-approve
ECR_URL=$(terraform output -raw ecr_repository_url)
cd "${PROJECT_ROOT}"
echo "✅ ECR Repository ready: ${ECR_URL}"

# 4. Build & Push Backend Container to ECR (AWS Graviton ARM64)
echo -e "\n[4/6] Building and pushing Docker container for AWS Fargate (ARM64 Graviton)..."
aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${ECR_URL}"
docker build --platform linux/arm64 -t "${ECR_URL}:latest" -f Dockerfile.backend .
docker push "${ECR_URL}:latest"
echo "✅ Docker image pushed to ECR: ${ECR_URL}:latest"

# 5. Apply Full Infrastructure (ECS Fargate + ALB + S3 + CloudFront + Bedrock IAM)
echo -e "\n[5/6] Deploying Full AWS Infrastructure via Terraform..."
cd "${PROJECT_ROOT}/terraform"
terraform apply -auto-approve

S3_BUCKET=$(terraform output -raw s3_bucket_name)
CLOUDFRONT_ID=$(terraform output -raw cloudfront_distribution_id)
CLOUDFRONT_URL=$(terraform output -raw cloudfront_url)
ALB_URL=$(terraform output -raw alb_dns_name)
cd "${PROJECT_ROOT}"

# 6. Upload Frontend Assets to S3 & Invalidate CloudFront
echo -e "\n[6/6] Uploading Frontend to S3 & Invalidating CloudFront CDN..."
aws s3 sync "${PROJECT_ROOT}/frontend/dist" "s3://${S3_BUCKET}/" --delete
aws cloudfront create-invalidation --distribution-id "${CLOUDFRONT_ID}" --paths "/*" > /dev/null

echo "================================================================="
echo "🎉 DEPLOYMENT COMPLETE! YOUR APPLICATION IS LIVE ON AWS!"
echo "================================================================="
echo "🌍 Public Production URL: ${CLOUDFRONT_URL}"
echo "⚡ Backend Load Balancer:  ${ALB_URL}"
echo "📦 Frontend S3 Bucket:    s3://${S3_BUCKET}"
echo "🤖 Active LLM Model:      Meta Llama 3.1 8B (AWS Bedrock)"
echo "📈 Auto-Scaling:          AWS ECS Fargate (1 - 5 containers)"
echo "================================================================="
