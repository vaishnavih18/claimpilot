# OpenSearch domain - the production counterpart to the local Docker
# Compose OpenSearch container used for the ingest.py/hybrid-search work
# earlier. Holds the indexed policy clauses (BM25 + vector/kNN fields) that
# the agent's retrieval node queries.

resource "aws_security_group" "opensearch" {
  name        = "${var.project_name}-opensearch-sg"
  description = "Allows HTTPS (443) from inside the VPC."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from anything inside the VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    # Same VPC-CIDR-scoped trade-off as the RDS security group above:
    # loosened for parallel provisioning during initial setup, tighten to
    # EKS's node security group once the cluster exists.
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-opensearch-sg" }
}

# A service-linked role (AWSServiceRoleForAmazonOpenSearchService) is
# required before AWS will create a VPC-based OpenSearch domain - it's
# the role AWS itself uses to manage network interfaces inside your VPC
# on OpenSearch's behalf. It's not declared as a resource here: the first
# (failed) apply attempt already caused AWS to create it as a side
# effect, and it's an account-wide singleton, so Terraform creating it
# again would just collide with the one that already exists. If this
# project were set up in a brand-new AWS account with no OpenSearch
# history at all, you'd need either this one-time CLI command first -
# aws iam create-service-linked-role --aws-service-name opensearchservice.amazonaws.com -
# or an aws_iam_service_linked_role resource, same as the one removed
# here after it collided with the pre-existing role.

resource "aws_opensearch_domain" "main" {

  domain_name    = "${var.project_name}-search"
  engine_version = "OpenSearch_2.15"
  # Pinned minor version rather than "latest" so a `terraform apply` run
  # next month doesn't silently pick a newer engine and trigger an
  # in-place upgrade you didn't ask for. When to change: bump this
  # deliberately if you want a newer OpenSearch feature (e.g. a newer
  # neural-sparse model) - check AWS's supported-versions list first since
  # not every OpenSearch OSS version is offered as a managed domain.

  # Resource-based access policy. REQUIRED for the API to reach the domain:
  # the API authenticates with HTTP basic auth (master user, see
  # advanced_security_options below), and a basic-auth request carries no IAM
  # identity - IAM sees it as "anonymous". With an empty policy the domain
  # rejects it with 403 "User: anonymous is not authorized to perform:
  # es:ESHttp..." before fine-grained access control ever checks the
  # username/password. Principal "*" therefore does NOT mean open to the
  # world here: the domain is VPC-only (only reachable through its security
  # group from inside the VPC), and fine-grained access control still demands
  # valid credentials on every request. This is the standard policy for FGAC
  # + basic auth.
  # The ARN is built by hand (not aws_opensearch_domain.main.arn) because a
  # resource cannot reference itself.
  # When to change: switch the API to SigV4-signed requests with a specific
  # IAM role (and map that role in FGAC) to drop the "*" principal.
  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "*" }
      Action    = "es:ESHttp*"
      Resource  = "arn:aws:es:${var.aws_region}:${data.aws_caller_identity.current.account_id}:domain/${var.project_name}-search/*"
    }]
  })

  cluster_config {
    instance_type  = var.opensearch_instance_type
    instance_count = 1
    # Single node, no dedicated master nodes. A real production search
    # cluster wants 3+ data nodes (for quorum) and separate dedicated
    # master nodes (so master elections don't compete with query load).
    # One node is fine for a demo with synthetic data and no real traffic.
    # When to change: 3 data nodes once you care about surviving a node
    # failure; add dedicated masters once you have enough data/query
    # volume that master-election stability matters.
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.opensearch_volume_size_gb
  }

  vpc_options {
    subnet_ids         = [aws_subnet.private[0].id]
    security_group_ids = [aws_security_group.opensearch.id]
    # Only one subnet because instance_count = 1 above - a single-node
    # domain can only live in one AZ/subnet. When to change: once
    # instance_count goes to 3, list subnet_ids for each AZ you want nodes
    # spread across.
  }

  encrypt_at_rest {
    enabled = true
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https = true
  }

  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = true
    master_user_options {
      master_user_name     = "claimpilot_admin"
      master_user_password = random_password.rds_master.result
      # Reuses the same random_password resource as RDS rather than
      # minting a second one. Both are throwaway dev credentials stored
      # only in Secrets Manager / Terraform state, never typed by hand, so
      # there's no real security cost to sharing the value - it just saves
      # a second random_password resource. When to change: give this its
      # own random_password if these two systems should rotate on
      # independent schedules, or if you want a compromise of one secret
      # to not also expose the other.
    }
  }

  tags = { Name = "${var.project_name}-opensearch" }
}
