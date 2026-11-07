"""
Shared AWS clients for the agent: OpenSearch (retrieval) and Bedrock
(embeddings + the LLM call). Both branch on the same local-vs-real-infra
env var pattern already established in app/core/config.py, for the same
reason: no AWS credentials needed for local dev against docker-compose,
no silent fallback to localhost in a real pod.

EMBEDDING_MODEL_ID is fixed - Titan Text Embeddings V2, the same model
ingest.py used to build the index. This ISN'T a free choice at query time:
a query embedded with a different model would land in a different vector
space than the indexed clauses, and k-NN similarity against mismatched
spaces is meaningless (not just "worse" - the scores would be comparing
unrelated geometries). If the embedding model ever changes, the whole
index has to be rebuilt with it, not just the query side.

CHAT_MODEL_ID is the cross-region inference profile confirmed working
against a real `converse` call earlier in this project (see the Setup
Log's Amazon Bedrock section). Sonnet, not Haiku, for the assess step -
coverage determination from policy clause text is exactly the kind of
multi-step reasoning (did THIS clause's conditions actually get met by
THIS claim's facts) that's worth paying Sonnet's higher per-token cost
for; Haiku stays a reasonable choice for anything higher-volume and
simpler later (e.g. a classification-only pre-filter), but there's no
such step in this graph yet.
"""

import os

from opensearchpy import OpenSearch

from app.core.config import get_db_secret

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

# TODO: confirm this is the exact profile ID string tested in the Setup
# Log's "Test an actual converse call against the au. Haiku 4.5 and
# Sonnet 4.5 inference profiles" step and replace this placeholder.
CHAT_MODEL_ID = "au.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Cheaper/faster model for the query-rewrite step before retrieval (a short
# paraphrase task, not coverage reasoning). Profile ID taken from
# `aws bedrock list-inference-profiles` in this account.
QUERY_MODEL_ID = "au.anthropic.claude-haiku-4-5-20251001-v1:0"


def get_opensearch_client() -> OpenSearch:
    host = os.environ.get("OPENSEARCH_HOST")

    if not host:
        # Local dev: docker-compose.yaml runs this with
        # DISABLE_SECURITY_PLUGIN=true, so no credentials at all - see
        # that file's comment on why there's no equivalent flag in prod.
        return OpenSearch(
            hosts=[{"host": "localhost", "port": 9200}],
            http_compress=True,
            use_ssl=False,
            verify_certs=False,
        )

    # Real domain: HTTPS + HTTP basic auth (fine-grained access control
    # with an internal user database - see infra/terraform/opensearch.tf's
    # advanced_security_options), NOT IAM/SigV4. The domain's master
    # username/password are deliberately the same values as the RDS
    # secret (same opensearch.tf comment), so this reads that one secret
    # rather than needing a second Secrets Manager entry or a new IAM
    # permission beyond what pod_identity.tf already grants.
    secret = get_db_secret()
    return OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=(secret["username"], secret["password"]),
        http_compress=True,
        use_ssl=True,
        verify_certs=True,
    )


def get_bedrock_runtime_client():
    region = os.environ.get("AWS_REGION", "ap-southeast-2")
    # Local dev uses the claimpilot-static CLI profile (same as every
    # other local AWS call in this project); in-cluster, boto3 picks up
    # the pod's own credentials automatically via Pod Identity - no
    # profile_name needed there, and passing one that doesn't exist in
    # the pod would just break it, so this only sets profile when asked.
    import boto3

    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile, region_name=region) if profile else boto3.Session(region_name=region)
    return session.client("bedrock-runtime")
