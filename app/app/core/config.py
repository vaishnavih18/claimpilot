"""
Settings for the ClaimPilot API, with one job worth explaining: resolving
the Postgres connection string without ever putting the password in an
env var that `kubectl describe pod` or a CloudWatch log line could echo
back verbatim.

Two ways DATABASE_URL gets resolved, in priority order:

1. DATABASE_URL env var set directly - for local development against the
   docker-compose Postgres (see /home/claude/docker-compose.yaml), where
   there's no Secrets Manager and no reason to pretend there is one.
   Example: postgresql+psycopg://claimpilot:claimpilot_local_dev@localhost:5432/claimpilot

2. RDS_SECRET_ARN env var set instead - for everywhere else (EKS, this
   migration, CI). The pod's env only ever holds an ARN (not a secret
   value - ARNs aren't sensitive), and this code calls Secrets Manager at
   startup to resolve the real username/password/host/dbname from the
   JSON secret that secrets.tf creates. The node's IAM role (not a
   hardcoded key) is what authorizes that call - see the "when to change"
   note below for the one piece of wiring this still needs.

This pod's permission to call secretsmanager:GetSecretValue comes from EKS
Pod Identity (infra/terraform/pod_identity.tf), not the node's own IAM
role - a per-ServiceAccount role, scoped to exactly this one secret's
ARN, associated via k8s/service-account.yaml's claimpilot-api service
account matching the association's namespace/service_account strings
exactly. If this call ever starts failing with AccessDenied after working
before, check that string match first - it's a plain string comparison,
not a Terraform-validated reference, so a rename on either side breaks it
silently.

get_db_secret() below is split out from get_database_url() because the
agent's OpenSearch client (app/app/agent/clients.py) needs the same
username/password too - opensearch.tf deliberately reuses the RDS master
password as the OpenSearch master password rather than minting a second
secret, so one fetch serves both.
"""

import json
import os
from functools import lru_cache

import boto3


@lru_cache(maxsize=1)
def get_db_secret() -> dict:
    """Returns the Secrets Manager secret dict: username, password, host,
    port, dbname. Raises if RDS_SECRET_ARN isn't set - callers that also
    accept a local-dev fallback (get_database_url below) check for that
    env var themselves before calling this."""
    secret_arn = os.environ["RDS_SECRET_ARN"]
    region = os.environ.get("AWS_REGION", "ap-southeast-2")
    client = boto3.client("secretsmanager", region_name=region)
    return json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])


@lru_cache(maxsize=1)
def get_database_url() -> str:
    direct = os.environ.get("DATABASE_URL")
    if direct:
        return direct

    if "RDS_SECRET_ARN" not in os.environ:
        raise RuntimeError(
            "Neither DATABASE_URL nor RDS_SECRET_ARN is set. Set DATABASE_URL "
            "directly for local dev (see docker-compose.yaml), or RDS_SECRET_ARN "
            "to the Secrets Manager secret Terraform created (see "
            "infra/terraform/outputs.tf -> rds_credentials_secret_arn) when "
            "running against real infrastructure."
        )

    secret = get_db_secret()

    # +psycopg tells SQLAlchemy to use psycopg3 (what's in requirements.txt),
    # not the legacy psycopg2 driver SQLAlchemy would otherwise default to.
    return (
        f"postgresql+psycopg://{secret['username']}:{secret['password']}"
        f"@{secret['host']}:{secret['port']}/{secret['dbname']}"
    )
