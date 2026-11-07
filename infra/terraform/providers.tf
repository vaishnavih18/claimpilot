terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    # Added for secrets.tf — generates the RDS master password. A dedicated
    # provider for this one job rather than typing a password by hand, so
    # nobody (including you) ever actually sees or has to remember it; it
    # goes straight into Secrets Manager.
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    # Added for cognito.tf - zips the pre-sign-up Lambda source.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    # Added for github_oidc.tf — fetches GitHub's real OIDC certificate
    # thumbprint at apply time rather than hardcoding one that would go
    # stale if GitHub ever rotates it.
  }

  # No backend block = state stored locally in terraform.tfstate, right here in
  # infra/terraform/. Fine for a solo 3-day project with one person applying
  # changes. Already covered by the repo's .gitignore (terraform state files
  # are excluded), so the state file itself never gets committed.
  #
  # When to change: the moment a second person (or CI) needs to run
  # terraform apply too, local state breaks down — two people applying from
  # different laptops will have two different "truths" about what's deployed.
  # At that point, add a backend "s3" block pointing at a bucket + DynamoDB
  # lock table, and run `terraform init -migrate-state`.
}

provider "aws" {
  region  = var.aws_region
  profile = "claimpilot-static"
  # A plain long-lived IAM access key (created in the IAM console for
  # vaish-admin, stored in ~/.aws/credentials under this profile name) -
  # not a session, so it has no expiration clock to race against.
  #
  # The backstory: `claimpilot` (the profile from Day 1's `aws login`)
  # issues short-lived "login_session" credentials that auto-rotate every
  # ~15 min, but only when something goes through the AWS CLI's own
  # refresh mechanism. Terraform's AWS provider is a separate Go SDK that
  # doesn't drive that refresh - every bridge tried (`credential_process`,
  # exporting a one-time env-var snapshot) was only ever as fresh as the
  # moment it was taken, which kept expiring mid-wait during OpenSearch's
  # ~12-15 min creation time. A static access key removes the race
  # entirely: nothing to re-export, re-login, or time against.
  #
  # The trade-off: a static key is a standing credential - valid
  # indefinitely until manually deactivated/deleted, rather than
  # self-expiring. Acceptable for a disposable solo demo account; the
  # key should be deactivated or deleted (IAM console → vaish-admin →
  # Security credentials) once this project is done.
  #
  # When to change: delete this access key and go back to `aws login`
  # (or a proper SSO-based profile) if this account starts holding
  # anything beyond synthetic demo data, or is ever shared with anyone
  # else.

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
