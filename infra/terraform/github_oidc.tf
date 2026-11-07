
# GitHub Actions OIDC provider + IAM role for CI/CD.
#
# Why OIDC instead of a stored AWS access key: a GitHub Actions secret
# holding a long-lived key is a standing liability - if it ever leaks (a
# workflow typo that echoes it, a compromised third-party Action), whoever
# has it can use it indefinitely, from anywhere. OIDC federation means
# GitHub's runner proves its identity with a short-lived token minted
# fresh for THIS SPECIFIC workflow run, and AWS only trusts that token for
# the exact repo/branch named in the trust policy's `sub` condition below -
# nothing to leak that's still valid five minutes later, and nothing to
# rotate.

data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
  # Fetches GitHub's real, current TLS certificate thumbprint at apply
  # time rather than hardcoding one - GitHub has rotated this certificate
  # before, and a hardcoded thumbprint would silently break OIDC the next
  # time they do, with an AWS error that gives no hint why.
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

resource "aws_iam_role" "github_actions_ci" {
  name = "${var.project_name}-github-actions-ci"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github_actions.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Restricted to pushes/merges on main only - not every branch,
          # and deliberately NOT pull_request events. A PR from a fork
          # would otherwise be able to assume this role just by opening a
          # PR against this repo, which is exactly the supply-chain
          # attack OIDC scoping exists to prevent. The test job in the
          # workflow still runs on PRs - it just never reaches the step
          # that needs AWS credentials.
          "token.actions.githubusercontent.com:sub" = "repo:vaishnavih18/claimpilot:ref:refs/heads/main"
        }
      }
    }]
  })
}

# ECR: push access scoped to exactly the two repos this project's CI
# actually builds (api, mcp-server) - not ecr:* on every repo in the
# account. Same "scope to exactly what's needed" pattern as the Pod
# Identity role's Secrets Manager permission elsewhere in this project.
resource "aws_iam_role_policy" "github_actions_ecr" {
  name = "${var.project_name}-github-actions-ecr-push"
  role = aws_iam_role.github_actions_ci.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # GetAuthorizationToken has no resource-level permissions in
        # IAM - it must be Resource "*", that's an AWS API constraint,
        # not a scoping choice being skipped here.
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
        ]
        Resource = [for repo in aws_ecr_repository.main : repo.arn]
      }
    ]
  })
}

# EKS: only eks:DescribeCluster (what `aws eks update-kubeconfig` needs to
# build a kubeconfig) - actual Kubernetes-level permissions come from the
# access entry/policy association below, not from this IAM policy. The
# two systems are deliberately separate in EKS's modern access model: IAM
# controls who can call the EKS API, access entries control what they can
# do once inside the cluster.
resource "aws_iam_role_policy" "github_actions_eks_describe" {
  name = "${var.project_name}-github-actions-eks-describe"
  role = aws_iam_role.github_actions_ci.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["eks:DescribeCluster"]
      Resource = aws_eks_cluster.main.arn
    }]
  })
}

# Namespace-scoped, not cluster-admin: CI only needs to apply/update the
# Deployment/Service/ServiceAccount inside the claimpilot namespace (what
# `kubectl apply -k k8s/` actually touches) - AmazonEKSEditPolicy covers
# that without granting the cluster-wide access eks.tf's admin access
# entry (your own IAM user) deliberately has for interactive debugging.
resource "aws_eks_access_entry" "github_actions_ci" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_iam_role.github_actions_ci.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "github_actions_ci" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = aws_iam_role.github_actions_ci.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"

  access_scope {
    type       = "namespace"
    namespaces = ["claimpilot"]
  }

  depends_on = [aws_eks_access_entry.github_actions_ci]
  # Same ordering reason as eks.tf's admin association: the access entry
  # must exist and propagate before AWS's API will accept a policy
  # association for that principal.
}
