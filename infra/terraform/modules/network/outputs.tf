output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

# Where ECS tasks run: private subnets behind NAT, or public subnets with a
# public IP when the NAT gateway is disabled to save cost.
output "app_subnet_ids" {
  value = var.enable_nat_gateway ? aws_subnet.private[*].id : aws_subnet.public[*].id
}

output "assign_public_ip" {
  value = !var.enable_nat_gateway
}

output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "app_security_group_id" {
  value = aws_security_group.app.id
}

output "postgres_security_group_id" {
  value = aws_security_group.data["postgres"].id
}

output "redis_security_group_id" {
  value = aws_security_group.data["redis"].id
}

output "rabbitmq_security_group_id" {
  value = aws_security_group.data["rabbitmq"].id
}
