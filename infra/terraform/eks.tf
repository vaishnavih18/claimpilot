# EKS cluster using Auto Mode - AWS provisions and scales worker nodes
# itself based on what's actually scheduled, so there's no node-group
# instance-type/count/sizing variable to tune here the way a classic
# managed node group would need.

resource "aws_security_group" "eks_cluster" {
  name        = "${var.project_name}-eks-cluster-sg"
  description = "EKS control plane to node communication."
  # AWS security group descriptions only allow a specific character set
  # (letters, numbers, and a short punctuation list) - no < or > - so the
  # original "<->" arrow had to go.
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-eks-cluster-sg" }
}

resource "aws_eks_cluster" "main" {
  name     = "${var.project_name}-cluster"
  role_arn = aws_iam_role.eks_cluster.arn
  version  = var.eks_cluster_version

  bootstrap_self_managed_addons = false
  # Self-managed addons are the old, manual way of installing core
  # cluster components (CoreDNS, kube-proxy, VPC CNI) yourself. EKS Auto
  # Mode installs and manages its own equivalents, so AWS requires this
  # explicitly set to false - leaving it at its (true) default conflicts
  # with Auto Mode and the cluster fails to create.

  vpc_config {
    subnet_ids              = concat(aws_subnet.private[*].id, aws_subnet.public[*].id)
    security_group_ids      = [aws_security_group.eks_cluster.id]
    endpoint_private_access = true
    endpoint_public_access  = true
    # Both private and public subnets are listed so the cluster can place
    # an internet-facing load balancer (ALB) in the public subnets later
    # while worker nodes/pods stay in the private ones. Public API access
    # stays on so `kubectl` from your own laptop keeps working without a
    # VPN/bastion - fine for a demo. When to change: set
    # endpoint_public_access to false (private-only) if this cluster ever
    # holds anything beyond synthetic data and you want the control plane
    # reachable only from inside the VPC.
  }

  access_config {
    authentication_mode = "API"
    # "API" (the newer EKS access-entry system) instead of the legacy
    # aws-auth ConfigMap, so cluster access for your IAM user can be
    # granted with an aws_eks_access_entry resource (added below) rather
    # than hand-editing a Kubernetes ConfigMap.
  }

  compute_config {
    enabled = true
    # This is what turns on EKS Auto Mode. With it enabled, AWS manages
    # the node pools, their scaling, AMI patching, and bin-packing - which
    # is the whole reason no instance-type or node-count variable appears
    # in this file.
    node_pools = ["general-purpose", "system"]
    node_role_arn = aws_iam_role.eks_node.arn
  }

  kubernetes_network_config {
    elastic_load_balancing {
      enabled = true
    }
    # Required alongside compute_config for Auto Mode - this is the piece
    # that lets Auto Mode provision AWS Load Balancer Controller resources
    # (ALB/NLB) automatically when you create a Kubernetes Service of type
    # LoadBalancer, instead of you installing and managing that controller
    # yourself.
  }

  storage_config {
    block_storage {
      enabled = true
    }
    # The third required switch for Auto Mode, alongside compute_config
    # and kubernetes_network_config's elastic_load_balancing above - AWS
    # requires all three to be explicitly set (true or false) together
    # once Auto Mode is in play, even though this project doesn't
    # currently need persistent volumes. This lets Auto Mode provision EBS
    # volumes automatically for any PersistentVolumeClaim a pod creates,
    # instead of you installing and managing the EBS CSI driver yourself.
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_cluster_policy
  ]
}

# Grants your own IAM user (the one Terraform is running as) admin access
# to the cluster via kubectl, using the newer access-entry system rather
# than the aws-auth ConfigMap. Reuses the aws_caller_identity data source
# already declared in s3.tf (same account, no need to look it up twice).
resource "aws_eks_access_entry" "admin" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = data.aws_caller_identity.current.arn
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "admin" {
  cluster_name  = aws_eks_cluster.main.name
  principal_arn = data.aws_caller_identity.current.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}
