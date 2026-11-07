output "vpc_id" {
  description = "VPC ID - referenced by every later Terraform file (RDS, OpenSearch, EKS, security groups)."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnet IDs - RDS, the OpenSearch domain, and EKS worker nodes all get created inside these."
  value       = aws_subnet.private[*].id
}

output "nat_gateway_ids" {
  value = aws_nat_gateway.main[*].id
}

output "ecr_repository_urls" {
  description = "ECR repo URLs (api, mcp-server) - needed by Docker/CI to know where to push built images."
  value       = { for k, repo in aws_ecr_repository.main : k => repo.repository_url }
}

output "documents_bucket_name" {
  value = aws_s3_bucket.documents.id
}

output "eks_cluster_role_arn" {
  description = "Referenced by eks.tf when the EKS cluster resource is created."
  value       = aws_iam_role.eks_cluster.arn
}

output "eks_node_role_arn" {
  description = "Referenced by eks.tf's node group / Auto Mode configuration."
  value       = aws_iam_role.eks_node.arn
}

output "rds_endpoint" {
  description = "Postgres host:port - the app connects here (pulled from Secrets Manager at runtime, not hardcoded)."
  value       = aws_db_instance.main.endpoint
}

output "rds_credentials_secret_arn" {
  description = "Secrets Manager ARN holding the RDS username/password/host/dbname as JSON."
  value       = aws_secretsmanager_secret.rds_credentials.arn
}

output "opensearch_endpoint" {
  description = "OpenSearch domain HTTPS endpoint - the retrieval node queries this instead of localhost:9200 once deployed."
  value       = aws_opensearch_domain.main.endpoint
}

output "eks_cluster_name" {
  value = aws_eks_cluster.main.name
}

output "eks_cluster_endpoint" {
  description = "EKS API server endpoint - used by kubectl / aws eks update-kubeconfig."
  value       = aws_eks_cluster.main.endpoint
}

output "github_actions_ci_role_arn" {
  description = "IAM role GitHub Actions assumes via OIDC (github_oidc.tf) - hardcoded into .github/workflows/ci-cd.yml's role-to-assume, not read dynamically. Run `terraform output github_actions_ci_role_arn` after any change to project_name and confirm it still matches what the workflow file has, since nothing enforces that the two stay in sync automatically."
  value       = aws_iam_role.github_actions_ci.arn
}
