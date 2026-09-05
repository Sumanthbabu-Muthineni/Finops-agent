output "cloudfront_url" {
  description = "The Primary Public HTTPS URL for Hackathon Judges & Users"
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "alb_dns_name" {
  description = "Direct Application Load Balancer DNS Name"
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecr_repository_url" {
  description = "ECR Repository URL for Backend Docker Image"
  value       = aws_ecr_repository.backend.repository_url
}

output "s3_bucket_name" {
  description = "Frontend S3 Bucket Name"
  value       = aws_s3_bucket.frontend.id
}

output "cloudfront_distribution_id" {
  description = "CloudFront Distribution ID for cache invalidations"
  value       = aws_cloudfront_distribution.main.id
}
