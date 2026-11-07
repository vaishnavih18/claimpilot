variable "aws_region" {
  description = "AWS region for everything. Sydney, to match the account's existing project region and keep data in Australia for the AU-insurance story."
  type        = string
  default     = "ap-southeast-2"
}

variable "project_name" {
  description = "Short name used as a prefix on every resource (vpc, subnets, security groups, etc.) and in the default_tags block, so anything in the AWS console can be traced back to this project at a glance."
  type        = string
  default     = "claimpilot"
}

variable "environment" {
  description = "Environment tag. Only \"dev\" exists for this project — no staging/prod split needed for a portfolio build."
  type        = string
  default     = "dev"
}

# --- Networking ---

variable "vpc_cidr" {
  description = "IP range for the whole VPC. 10.0.0.0/16 gives 65,536 addresses - far more than this project needs, but it's the conventional starting block for a VPC and leaves room to add more subnets later without re-planning the whole range."
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "Which AZs to spread subnets across. Two AZs (not one, not three): two is the minimum AWS requires for things like RDS Multi-AZ and an EKS control plane to be considered highly available; a third AZ would add cost (another NAT-routed private subnet) without adding anything this project's eval/demo needs."
  type        = list(string)
  default     = ["ap-southeast-2a", "ap-southeast-2b"]
}

variable "public_subnet_cidrs" {
  description = "One /24 (256 addresses) per AZ for public subnets - only the ALB and the NAT gateway live here, so 256 addresses is overkill but it's a clean, memorable split from the private ranges below."
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "One /24 per AZ for private subnets - this is where RDS, the OpenSearch domain, and the EKS worker nodes all live, with no direct route in from the internet."
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "single_nat_gateway" {
  description = "Use one shared NAT gateway for both private subnets instead of one per AZ. A NAT gateway costs ~$0.065/hr just to exist, before any data transfer - one instead of two roughly halves that for a project that's only up for a few days and isn't trying to survive an AZ outage."
  type        = bool
  default     = true
  # When to change: flip to false (one NAT per AZ) the moment this needs to
  # survive a single AZ going down without an outage - i.e. if this were a
  # real production deployment rather than a demo/eval environment. With a
  # single shared NAT, if its AZ has a problem, the private subnet in the
  # *other* AZ loses internet egress too.
}

# --- RDS ---

variable "rds_instance_class" {
  description = "RDS instance size. db.t4g.micro is the smallest Graviton (ARM) burstable class - cheapest option that still runs Postgres fine for synthetic data and a handful of demo queries."
  type        = string
  default     = "db.t4g.micro"
  # When to change: bump to db.t4g.small/medium once you're running real
  # query load (e.g. load-testing the API) rather than ad hoc demo traffic,
  # or if you hit CPU credit exhaustion (burstable instances run out of
  # credits under sustained load).
}

variable "rds_allocated_storage_gb" {
  description = "RDS storage size in GB. 20 GB is the minimum gp3 allocation AWS allows and far more than synthetic claims data needs."
  type        = number
  default     = 20
  # When to change: only if you load a genuinely large dataset or start
  # storing LangGraph checkpoint history at volume - 20 GB holds this
  # project's data with room to spare.
}

variable "rds_engine_version" {
  description = "Postgres major version. 16, to match the pgvector/pgvector:pg16 image used for local Docker Compose - keeping local and AWS Postgres on the same major version avoids subtle SQL/extension differences between dev and \"prod\"."
  type        = string
  default     = "16"
}

variable "rds_backup_retention_days" {
  description = "Days of automated RDS backups to retain. 1 is the minimum (0 disables backups entirely) - just enough to recover from an accidental bad migration during the project, without paying for a longer retention window a demo doesn't need."
  type        = number
  default     = 1
  # When to change: raise to 7+ once this holds anything you'd actually
  # need to restore from a few days back, not just "yesterday."
}

variable "rds_multi_az" {
  description = "Whether RDS runs a synchronous standby in a second AZ for automatic failover. False - a demo/eval project doesn't need to survive an AZ outage, and Multi-AZ roughly doubles RDS cost."
  type        = bool
  default     = false
  # When to change: true the moment this is a real deployment that needs
  # to survive an AZ failure without manual intervention.
}

# --- OpenSearch ---

variable "opensearch_instance_type" {
  description = "OpenSearch data node size. t3.small.search is the smallest instance type OpenSearch Service supports with EBS storage - enough for a few thousand policy-clause documents with BM25 + kNN fields."
  type        = string
  default     = "t3.small.search"
  # When to change: move to an m-series or r-series instance once the
  # index grows past what a t3.small's memory comfortably holds, or if kNN
  # query latency becomes noticeable under real load.
}

variable "opensearch_volume_size_gb" {
  description = "EBS volume size per OpenSearch node, in GB. 10 GB comfortably fits this project's synthetic policy-clause corpus plus its vector index."
  type        = number
  default     = 10
  # When to change: raise if the corpus grows substantially, or if you add
  # additional indices (e.g. a second embedding model's vectors) alongside
  # the existing one.
}

# --- EKS ---

variable "eks_cluster_version" {
  description = "Kubernetes version for the EKS control plane. 1.31 - a recent version with Auto Mode support (Auto Mode requires 1.29+), without being the bleeding-edge version that might lack full AWS tooling/addon support yet."
  type        = string
  default     = "1.31"
  # When to change: bump when AWS deprecates 1.31 (EKS versions roll off
  # standard support on a schedule - check AWS's EKS version calendar), or
  # deliberately if you want a newer K8s feature.
}
