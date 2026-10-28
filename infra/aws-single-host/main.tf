data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

data "aws_cloudfront_response_headers_policy" "security_headers" {
  name = "Managed-SecurityHeadersPolicy"
}

resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

locals {
  name_prefix = var.resource_name_prefix
  bucket_name = "${local.name_prefix}-source-${data.aws_caller_identity.current.account_id}-${data.aws_region.current.region}"
}

resource "aws_s3_bucket" "source" {
  bucket        = local.bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "source" {
  bucket                  = aws_s3_bucket.source.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "source" {
  bucket = aws_s3_bucket.source.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "source" {
  bucket = aws_s3_bucket.source.id

  rule {
    id     = "expire-source-archive"
    status = "Enabled"

    filter {}

    expiration {
      days = 1
    }
  }
}

resource "aws_s3_object" "source" {
  bucket       = aws_s3_bucket.source.id
  key          = "flashsale-source.zip"
  source       = var.source_zip_path
  source_hash  = filemd5(var.source_zip_path)
  content_type = "application/zip"
}

resource "aws_security_group" "origin" {
  name        = "${local.name_prefix}-origin"
  description = "CloudFront-only access to the NGINX origin."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "CloudFront origin-facing addresses only"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    description = "Outbound package and image downloads for the single-host deployment"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name      = "${local.name_prefix}-origin"
    Project   = "flashsale"
    ManagedBy = "terraform"
  }
}

resource "aws_iam_role" "instance" {
  name = "${local.name_prefix}-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "source_read" {
  name = "read-demo-source-archive"
  role = aws_iam_role.instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.source.arn}/flashsale-source.zip"
    }]
  })
}

resource "aws_iam_instance_profile" "instance" {
  name = "${local.name_prefix}-instance"
  role = aws_iam_role.instance.name
}

resource "aws_instance" "demo" {
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = sort(data.aws_subnets.default.ids)[0]
  vpc_security_group_ids      = [aws_security_group.origin.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.instance.name

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gib
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    aws_region         = var.aws_region
    source_bucket      = aws_s3_bucket.source.bucket
    source_key         = aws_s3_object.source.key
    origin_verify      = random_password.origin_verify.result
    package_sha256     = filebase64sha256(var.source_zip_path)
    bootstrap_log_file = var.bootstrap_log_file
  })
  user_data_replace_on_change = true

  depends_on = [
    aws_iam_role_policy_attachment.ssm,
    aws_iam_role_policy.source_read,
    aws_s3_bucket_server_side_encryption_configuration.source,
    aws_s3_bucket_public_access_block.source,
    aws_s3_object.source,
  ]

  tags = {
    Name      = "${local.name_prefix}-ec2"
    Project   = "flashsale"
    ManagedBy = "terraform"
  }
}

resource "aws_cloudfront_cache_policy" "web" {
  name        = "${local.name_prefix}-origin-cache-control"
  comment     = "Honor NGINX cache headers for immutable web assets."
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true

    cookies_config {
      cookie_behavior = "none"
    }

    headers_config {
      header_behavior = "none"
    }

    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_distribution" "demo" {
  enabled             = true
  comment             = "FlashSale single-host AWS application"
  default_root_object = "index.html"
  is_ipv6_enabled     = true
  price_class         = "PriceClass_100"
  http_version        = "http2and3"

  origin {
    domain_name = aws_instance.demo.public_dns
    origin_id   = "${local.name_prefix}-nginx"

    custom_origin_config {
      http_port                = 8080
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/api/*"
    target_origin_id           = "${local.name_prefix}-nginx"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods             = ["GET", "HEAD", "OPTIONS"]
    compress                   = true
    cache_policy_id            = data.aws_cloudfront_cache_policy.caching_disabled.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
  }

  default_cache_behavior {
    target_origin_id           = "${local.name_prefix}-nginx"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD", "OPTIONS"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.web.id
    origin_request_policy_id   = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security_headers.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  depends_on = [aws_instance.demo]

  tags = {
    Name      = "${local.name_prefix}-cdn"
    Project   = "flashsale"
    ManagedBy = "terraform"
  }
}
