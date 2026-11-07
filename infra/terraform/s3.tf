resource "aws_s3_bucket" "documents" {
  # Bucket names are globally unique across ALL of AWS, not just your
  # account - so the account ID is appended to avoid a collision with
  # someone else's "claimpilot-documents" bucket.
  bucket = "${var.project_name}-documents-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "${var.project_name}-documents"
  }
  # Holds the synthetic claim documents/attachments the agent references by
  # claim ID - the one piece of "unstructured file" storage in the project,
  # separate from the structured claims data in Postgres and the policy
  # clauses in OpenSearch.
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
  # Enabled so an accidental overwrite or delete of a claim document doesn't
  # silently lose data - a previous version is always recoverable. Costs
  # essentially nothing at this project's scale (a handful of small files).
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
  # AES256 (SSE-S3, AWS-managed keys) rather than SSE-KMS: encryption at
  # rest either way, but SSE-KMS adds a per-request cost and the extra
  # complexity of managing a KMS key - not worth it unless there's a
  # compliance requirement for customer-managed keys, which a portfolio
  # project doesn't have.
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
  # All four set true - this bucket holds (synthetic, but still
  # claims-shaped) personal/financial data, so there is never a legitimate
  # reason for anything in it to be public. This is the standard default
  # AWS now recommends for every bucket unless you're specifically hosting
  # public static assets, which this isn't.
}
