# Lets the claimpilot-api pod read its own RDS credentials from Secrets
# Manager at runtime (app/app/core/config.py's get_database_url(), via
# app/app/db/base.py), without the password ever appearing in a Docker
# image, a Kubernetes YAML file, or this repo. The agent's OpenSearch
# client (app/app/agent/clients.py) reads the SAME secret for its basic-
# auth credentials, since opensearch.tf deliberately reuses the RDS
# master password rather than minting a second one -- no extra IAM
# permission needed for that.
#
# EKS Pod Identity, not IRSA (the older OIDC-provider-based mechanism):
# Pod Identity is the newer, simpler AWS-native equivalent - no OIDC
# provider resource to create and no trust-policy string matching on a
# service account's namespace/name inside a federated-identity condition.
# It's also already running on this cluster for free: EKS Auto Mode has
# the Pod Identity Agent built in (confirmed against AWS's docs - "You do
# not need to install the EKS Pod Identity Agent on EKS Auto Mode
# Clusters"), so nothing else needs installing before this works.

resource "aws_iam_role" "claimpilot_api_pod" {
  name = "${var.project_name}-api-pod-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      # Trusted by the Pod Identity service itself, not by a specific
      # pod/namespace condition the way IRSA's trust policy would need -
      # the EKS Pod Identity Association resource below is what actually
      # scopes which pods get to assume this role.
      Principal = { Service = "pods.eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
    }]
  })
}

resource "aws_iam_role_policy" "claimpilot_api_pod_secrets" {
  name = "${var.project_name}-api-pod-secrets-access"
  role = aws_iam_role.claimpilot_api_pod.id

  # Scoped to exactly one secret ARN, not secretsmanager:* or a wildcard
  # resource - the pod can read the RDS credentials and nothing else in
  # this AWS account's Secrets Manager.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = aws_secretsmanager_secret.rds_credentials.arn
    }]
  })
}

resource "aws_eks_pod_identity_association" "claimpilot_api" {
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "claimpilot"
  service_account = "claimpilot-api"
  role_arn        = aws_iam_role.claimpilot_api_pod.arn
  # namespace/service_account must match k8s/service-account.yaml and
  # deployment.yaml's spec.serviceAccountName EXACTLY - this is a string
  # match, not a reference Terraform validates against the cluster's
  # actual objects, so a typo here fails silently (the pod just never
  # gets credentials) rather than erroring at apply time.
}
