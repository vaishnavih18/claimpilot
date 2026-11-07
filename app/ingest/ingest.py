#!/usr/bin/env python3
"""
ClaimPilot policy ingestion: parse -> chunk -> embed (Titan V2) -> index (OpenSearch).

Each policy clause (already parsed into JSON by parse_policy.py / generate.py) is
treated as one chunk -- a clause is already a self-contained unit of meaning, so
splitting further would break mid-thought, and merging clauses would blur which
specific rule a citation points to.

Embeds `heading + text` together (not text alone) -- the heading often carries the
most distinguishing signal for short/vague claim queries (e.g. "Cyclone Damage --
Queensland and Northern Territory" is itself a strong retrieval signal).

Indexes all 3 policy types into ONE shared OpenSearch index with `policy_type` as a
filterable field, rather than 3 separate indices -- simpler to query, and splitting
by type only matters at a much larger scale than ~135 documents.

Usage:
    python ingest.py                    # ingest all 3 policies from ../data/synthetic/policies/
    python ingest.py --recreate-index   # drop and recreate the index first (clean rebuild)
"""

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
from opensearchpy import OpenSearch, helpers

def _find_repo_root(start: Path) -> Path:
    """
    Walk up from `start` until a directory containing `.git` is found,
    rather than a hardcoded number of `.parent` calls. The hardcoded
    version just broke in practice: this script turned out to live one
    level deeper in the real repo than assumed when this was written, so
    the old `parent.parent` silently resolved to the WRONG directory
    (one that happened to exist, just not the one with the data in it)
    instead of raising a clear error -- exactly the kind of bug that goes
    undetected in a quick sandbox test and only surfaces on the real
    machine, where the actual layout lives. Walking up to a `.git` marker
    is immune to this script moving to a different depth later.
    """
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"Could not find repo root (no .git found walking up from {start})")


POLICY_DIR = _find_repo_root(Path(__file__).resolve().parent) / "data" / "synthetic" / "policies"
INDEX_NAME = "policy-clauses"
EMBEDDING_DIM = 1024  # Titan Text Embeddings V2 default output size


def _get_real_domain_credentials(secret_arn: str, region: str) -> tuple[str, str]:
    """
    Real AWS OpenSearch Service auth, corrected: this used to assume
    IAM/SigV4 (see the removed comment below). Checking
    infra/terraform/opensearch.tf shows it's actually fine-grained access
    control with an internal user database -- plain HTTP basic auth over
    HTTPS -- and it deliberately reuses the SAME secret as RDS
    (master_user_password = random_password.rds_master.result) rather
    than minting a second one. So this is the exact same secret
    app/app/core/config.py's get_database_url() reads, just pulled out
    standalone here since this script lives outside the `app` package
    (see app/app/agent/retrieval.py's docstring for why that boundary
    isn't crossed with an import).
    """
    client = boto3.client("secretsmanager", region_name=region)
    secret = json.loads(client.get_secret_value(SecretId=secret_arn)["SecretString"])
    return secret["username"], secret["password"]


def get_opensearch_client(
    host: str = "localhost",
    port: int = 9200,
    tls_hostname: str | None = None,
    secret_arn: str | None = None,
    region: str = "ap-southeast-2",
) -> OpenSearch:
    """
    Local (no args beyond defaults): docker-compose's OpenSearch, no
    auth, no TLS -- unchanged from before.

    Real domain: pass secret_arn (the RDS secret's ARN -- see
    infra/terraform/outputs.tf's rds_credentials_secret_arn output) to
    switch to HTTPS + basic auth. The domain is VPC-private (opensearch.tf's
    vpc_options), so a laptop can't reach it directly -- tunnel through a
    kubectl proxy pod the same way the RDS migration did (a socat pod +
    `kubectl port-forward`, just forwarding 443 instead of 5432), connect
    to `localhost:<forwarded-port>` as `host`/`port`, and pass the REAL
    domain hostname separately as `tls_hostname` -- the TLS certificate
    the real domain presents only matches its own hostname, not
    "localhost", so without this the handshake fails even though the
    traffic itself tunnels through port-forward fine.
    """
    if not secret_arn:
        return OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_compress=True,
            use_ssl=False,
            verify_certs=False,
        )

    username, password = _get_real_domain_credentials(secret_arn, region)
    kwargs = dict(
        hosts=[{"host": host, "port": port}],
        http_auth=(username, password),
        http_compress=True,
        use_ssl=True,
        verify_certs=True,
    )
    if tls_hostname:
        kwargs["ssl_assert_hostname"] = tls_hostname
    return OpenSearch(**kwargs)


INDEX_BODY = {
    "settings": {
        "index": {"knn": True}  # enables the k-NN plugin for this index specifically
    },
    "mappings": {
        "properties": {
            "clause_id": {"type": "keyword"},
            "policy_type": {"type": "keyword"},       # keyword, not text -- exact-match filter field
            "jurisdiction": {"type": "keyword"},       # same -- filtered on, never full-text searched
            "scope": {"type": "keyword"},
            "heading": {"type": "text"},               # text -- BM25 full-text search target
            "text": {"type": "text"},                  # text -- BM25 full-text search target
            "embedding": {
                "type": "knn_vector",
                "dimension": EMBEDDING_DIM,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",  # cosine -- standard for normalized text embeddings,
                                                    # matches how Titan V2 is tuned
                    # lucene, not nmslib: NMSLIB doesn't support filtered
                    # k-NN queries at all -- any "filter" inside a knn
                    # clause gets rejected outright with "Engine [NMSLIB]
                    # does not support filters", confirmed by hitting
                    # exactly that running the real agent (which always
                    # filters on policy_type, so this broke on the very
                    # first real retrieval). Lucene engine supports
                    # efficient filtered k-NN natively since OpenSearch
                    # 2.9, which is what hybrid_search.py's/retrieval.py's
                    # jurisdiction/policy_type filtering actually needs --
                    # switching to post-filter-after-retrieval instead
                    # would silently return fewer than k results whenever
                    # a filter is active, which defeats the point.
                    "engine": "lucene",
                },
            },
        }
    },
}


def embed_text(bedrock_client, text: str) -> list:
    resp = bedrock_client.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text}),
    )
    return json.loads(resp["body"].read())["embedding"]


def load_clauses() -> list:
    clauses = []
    for policy_type in ("home", "motor", "travel"):
        path = POLICY_DIR / f"{policy_type}.json"
        if not path.exists():
            print(f"ERROR: {path} not found -- run data/synthetic/generate.py first.", file=sys.stderr)
            sys.exit(1)
        policy = json.loads(path.read_text())
        clauses.extend(policy["clauses"])
    return clauses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opensearch-host", default="localhost", help="Where to actually connect -- 'localhost' when tunneling through kubectl port-forward")
    parser.add_argument("--opensearch-port", type=int, default=9200)
    parser.add_argument("--opensearch-secret-arn", default=None, help="RDS secret ARN -- set this to switch from local no-auth to the real domain's HTTPS+basic-auth (see infra/terraform/outputs.tf's rds_credentials_secret_arn)")
    parser.add_argument("--opensearch-tls-hostname", default=None, help="Real domain hostname for TLS cert verification -- required when --opensearch-host is a tunnel address like 'localhost', since the cert won't match that")
    parser.add_argument("--bedrock-profile", default="claimpilot")
    parser.add_argument("--bedrock-region", default="ap-southeast-2")
    parser.add_argument("--recreate-index", action="store_true")
    args = parser.parse_args()

    if args.opensearch_secret_arn and not args.opensearch_tls_hostname and args.opensearch_host == "localhost":
        print(
            "ERROR: --opensearch-secret-arn set with --opensearch-host=localhost but no "
            "--opensearch-tls-hostname -- TLS verification will fail against the real domain's "
            "certificate. Pass --opensearch-tls-hostname <the real domain endpoint>.",
            file=sys.stderr,
        )
        sys.exit(1)

    os_client = get_opensearch_client(
        args.opensearch_host,
        args.opensearch_port,
        tls_hostname=args.opensearch_tls_hostname,
        secret_arn=args.opensearch_secret_arn,
        region=args.bedrock_region,
    )

    if args.recreate_index:
        if os_client.indices.exists(INDEX_NAME):
            os_client.indices.delete(INDEX_NAME)
            print(f"Deleted existing index '{INDEX_NAME}'")

    if not os_client.indices.exists(INDEX_NAME):
        os_client.indices.create(INDEX_NAME, body=INDEX_BODY)
        print(f"Created index '{INDEX_NAME}'")

    session = boto3.Session(profile_name=args.bedrock_profile, region_name=args.bedrock_region)
    bedrock_client = session.client("bedrock-runtime")

    clauses = load_clauses()
    print(f"Loaded {len(clauses)} clauses from {POLICY_DIR}")

    print("Embedding and indexing (one Titan V2 call per clause) ...")
    actions = []
    for i, clause in enumerate(clauses, 1):
        embedding_input = f"{clause['heading']}. {clause['text']}"
        embedding = embed_text(bedrock_client, embedding_input)
        actions.append(
            {
                "_index": INDEX_NAME,
                "_id": clause["clause_id"],
                "_source": {**clause, "embedding": embedding},
            }
        )
        if i % 20 == 0 or i == len(clauses):
            print(f"  embedded {i}/{len(clauses)}")

    success, errors = helpers.bulk(os_client, actions, raise_on_error=False)
    print(f"Indexed {success} documents" + (f", {len(errors)} errors" if errors else ""))
    if errors:
        for e in errors[:5]:
            print(f"  error: {e}", file=sys.stderr)

    os_client.indices.refresh(INDEX_NAME)
    count = os_client.count(index=INDEX_NAME)["count"]
    print(f"\nDone. Index '{INDEX_NAME}' now has {count} documents.")


if __name__ == "__main__":
    main()