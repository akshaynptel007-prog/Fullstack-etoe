output "app_url" {
  description = "HTTPS URL for the application."
  value       = "https://${aws_cloudfront_distribution.demo.domain_name}"
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.demo.id
}

output "instance_id" {
  value = aws_instance.demo.id
}

output "origin_public_dns" {
  value = aws_instance.demo.public_dns
}

output "source_bucket_name" {
  value = aws_s3_bucket.source.bucket
}
