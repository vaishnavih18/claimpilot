# RDS Postgres - holds claims metadata tables and LangGraph's PostgresSaver
# checkpoints (the agent's conversation/state history). Lives in the private
# subnets alongside OpenSearch and the EKS worker nodes.

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds-sg"
  description = "Allows Postgres (5432) from inside the VPC."
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "Postgres from anything inside the VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    # Scoped to the whole VPC CIDR, not to EKS's own security group
    # specifically. Tighter would be: only allow traffic from the EKS node
    # security group. The reason for the looser rule here is sequencing -
    # RDS, OpenSearch and EKS are all being created in the same apply, and
    # scoping this to "EKS's security group" would force Terraform to
    # create EKS first just so this rule could reference it, serializing
    # three resources that would otherwise provision in parallel. For a
    # single-VPC dev/demo project where nothing untrusted shares the VPC,
    # that's an acceptable trade. When to change: tighten this to
    # reference aws_eks_cluster.main's node security group once the
    # cluster exists and you're not fighting for parallel apply time -
    # i.e. treat this as a one-time loosening for initial setup, not a
    # permanent posture.
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project_name}-rds-sg" }
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${var.project_name}-db-subnet-group" }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.project_name}-postgres"
  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  allocated_storage = var.rds_allocated_storage_gb
  storage_type       = "gp3"
  storage_encrypted  = true

  db_name  = "claimpilot"
  username = "claimpilot_admin"
  password = random_password.rds_master.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  multi_az            = var.rds_multi_az
  backup_retention_period = var.rds_backup_retention_days
  skip_final_snapshot = true
  # true = on destroy, don't bother creating a final snapshot first. A real
  # prod DB should keep this false (or unset) so a `terraform destroy`
  # can't silently lose data. This is a demo DB that gets created and
  # destroyed repeatedly while iterating, and snapshotting it each time
  # adds minutes to every destroy for no benefit. When to change: flip to
  # false the moment this holds anything you'd be upset to lose.

  publicly_accessible = false
  deletion_protection  = false
  # Same reasoning as skip_final_snapshot - false so this project can be
  # torn down in one command. Set true for anything you don't want an
  # accidental `terraform destroy` to take out.

  apply_immediately = true

  tags = { Name = "${var.project_name}-postgres" }
}
