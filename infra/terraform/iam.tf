## Two roles here - the cluster role and the node role - because EKS has
## two separate things that each need their own AWS permissions: the
## control plane (managed by AWS, needs a role to call other AWS APIs on
## your behalf) and the worker nodes (your EC2 instances, need a role to
## join the cluster and let pods pull images / write logs). They're created
## now, ahead of eks.tf, because the EKS cluster resource itself requires
## the role ARN to already exist at creation time.

resource "aws_iam_role" "eks_cluster" {
  name = "${var.project_name}-eks-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
      Action    = ["sts:AssumeRole", "sts:TagSession"]
      # sts:TagSession alongside sts:AssumeRole - Auto Mode specifically
      # requires this (AWS's docs call it out explicitly for the cluster
      # role's trust policy); EKS uses session tags internally to scope
      # the temporary credentials it hands to Auto Mode's compute/storage/
      # networking controllers. Plain (non-Auto-Mode) EKS only needs
      # sts:AssumeRole - this is one of the few places Auto Mode changes
      # what the cluster role's TRUST policy (not just its permissions)
      # has to say.
    }]
  })
  # "assume_role_policy" is the TRUST policy, not a permissions policy - it
  # answers "who is allowed to use this role", not "what can this role do".
  # Here: only the EKS service itself can assume it, which is what lets AWS
  # provision and manage the cluster's control plane under the hood.
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  # AWS-managed policy (not something we wrote) - the standard minimum
  # permission set AWS documents as required for the EKS control plane to
  # manage the cluster's EC2/ENI/load-balancer resources on your behalf.
  #
  # NOTE: this one alone is NOT enough once Auto Mode is turned on (see the
  # three attachments below) - this is the plain, non-Auto-Mode minimum,
  # kept here because every EKS cluster needs it regardless.
}

# The three attachments below are EXTRA permissions Auto Mode specifically
# needs on the CLUSTER role (not the node role) - this was the actual
# root cause of the stuck deploy: the NodeClass's "InstanceProfileReady"
# condition was failing with "Failed to create instance profile" because
# the cluster role couldn't call the IAM APIs (iam:CreateInstanceProfile,
# iam:AddRoleToInstanceProfile, etc.) needed to stand up an instance
# profile for the node role. AWS Auto Mode's own node pools/node class
# were created fine (by eks.tf's compute_config) - they just couldn't
# finish reconciling without these.
#
# Confirmed against AWS's own docs (docs.aws.amazon.com/eks - "Amazon EKS
# Auto Mode cluster IAM role"): these three managed policies, plus
# AmazonEKSClusterPolicy above, are the full required set for a cluster
# role used with Auto Mode.
resource "aws_iam_role_policy_attachment" "eks_cluster_compute_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSComputePolicy"
  # Lets the cluster provision/manage EC2 instances and instance profiles
  # for Auto Mode nodes - this is the specific permission that was missing.
}

resource "aws_iam_role_policy_attachment" "eks_cluster_block_storage_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSBlockStoragePolicy"
  # Lets Auto Mode manage EBS volumes for PersistentVolumeClaims without a
  # separately-installed EBS CSI driver.
}

resource "aws_iam_role_policy_attachment" "eks_cluster_load_balancing_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSLoadBalancingPolicy"
  # Lets Auto Mode provision the NLB behind k8s/service.yaml's
  # `type: LoadBalancer` Service without a separately-installed AWS Load
  # Balancer Controller.
}

resource "aws_iam_role_policy_attachment" "eks_cluster_networking_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSNetworkingPolicy"
  # Originally left off (see the removed comment below, kept in history/the
  # Setup Log for the record) under the assumption it was only for
  # per-pod security groups via Pod Identity. That assumption was wrong:
  # pod sandbox creation itself started failing with
  # "failed to assign an IP address to container" (an aws-cni error) once
  # a real node joined - the subnet had plenty of free IPs (246/254) and
  # the node (c6a.large, 1 ENI) was nowhere near its own IP limit, which
  # pointed at the actual AWS API call failing, not a capacity problem.
  # Same shape as the sts:TagSession fix earlier: Auto Mode performs this
  # ENI/IP-assignment work through its own AWS-owned chain role assuming
  # the CLUSTER role, so the cluster role needs the networking permissions
  # too, not just the node role.
}

resource "aws_iam_role" "eks_node" {
  name = "${var.project_name}-eks-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  # Trusted by EC2 this time, not EKS - because the worker nodes ARE EC2
  # instances (even under EKS Auto Mode, which manages them for you but
  # they're still EC2 under the hood).
}

resource "aws_iam_role_policy_attachment" "eks_node_worker_policy" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
  # Lets a node register itself with the cluster and report status.
}

resource "aws_iam_role_policy_attachment" "eks_node_cni_policy" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
  # Lets the VPC CNI plugin assign real VPC IP addresses to pods - without
  # this, pods on the node can't get networking at all.
}

resource "aws_iam_role_policy_attachment" "eks_node_ecr_policy" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
  # Lets a node pull the images from the ECR repos created in ecr.tf.
  # Read-only deliberately - nodes only ever need to pull images, never
  # push or delete them.
}

resource "aws_iam_role_policy_attachment" "eks_node_ssm_policy" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  # Lets you shell into a node via AWS Systems Manager Session Manager
  # instead of needing SSH keys and an open port 22 - useful for debugging
  # a node directly during the build. Not strictly required for the
  # cluster to function; it's a convenience/debugging addition.
  #
  # When to change: remove this if a node should have the smallest possible
  # permission set (e.g. in a real production cluster with a separate,
  # audited break-glass access process) - for this project, the debugging
  # convenience is worth the extra (fairly standard, AWS-managed) policy.
}
