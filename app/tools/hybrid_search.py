#!/usr/bin/env python3
"""
ClaimPilot hybrid policy search: BM25 (sparse, exact-term) + k-NN (dense,
semantic) combined via OpenSearch's search pipeline with score normalization.

This is the core of the `search_policy` tool your LangGraph agent's
search_policy node will call. Run standalone here to spot-check retrieval
quality against real queries before wiring it into the agent.

Why hybrid, not just one or the other:
  - BM25 alone misses a claim like "my roof blew off" matching a clause about
    "storm damage to structural elements" -- no shared words.
  - k-NN alone can over-match on loose semantic similarity and miss a clause
    that uses a very specific, exact term a claim also uses (e.g. "excess").
  - Combining both and normalizing their scores onto the same scale gets
    the benefit of each without picking one and eating the other's blind spot.

Usage:
    python hybrid_search.py "water came through my roof during the storm"
    python hybrid_search.py "stolen laptop" --policy-type home --k 5
"""

import argparse
import json
import sys

import boto3
from opensearchpy import OpenSearch

INDEX_NAME = "policy-clauses"
PIPELINE_NAME = "hybrid-search-pipeline"

# Search pipeline: normalizes BM25 and k-NN scores onto a comparable scale
# (min-max) before combining them with equal weight (arithmetic mean).
# Equal 0.5/0.5 weighting is the sensible starting point -- see note below
# on when/how to tune this once you have eval numbers to tune it against.
PIPELINE_BODY = {
    "description": "Normalize and combine BM25 + k-NN scores for hybrid policy search",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {"weights": [0.5, 0.5]},
                },
            }
        }
    ],
}


def get_opensearch_client(host: str = "localhost", port: int = 9200) -> OpenSearch:
    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_compress=True,
        use_ssl=False,
        verify_certs=False,
    )


def ensure_pipeline(client: OpenSearch):
    """Create the search pipeline once; safe to call every run."""
    client.transport.perform_request(
        "PUT", f"/_search/pipeline/{PIPELINE_NAME}", body=json.dumps(PIPELINE_BODY)
    )


def embed_query(bedrock_client, text: str) -> list:
    resp = bedrock_client.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text}),
    )
    return json.loads(resp["body"].read())["embedding"]


def hybrid_search(
    os_client: OpenSearch,
    bedrock_client,
    query_text: str,
    k: int = 5,
    policy_type: str | None = None,
    jurisdiction: str | None = None,
) -> list:
    """
    Returns up to k clauses, each with its combined hybrid score.

    policy_type / jurisdiction filters are applied as hard filters (not
    scored) -- this is the "metadata filtering on top of hybrid search"
    piece from the project design: a claim's policy_type is known before
    search even runs, and jurisdiction narrows regional exclusions.
    """
    query_vector = embed_query(bedrock_client, query_text)

    filters = []
    if policy_type:
        filters.append({"term": {"policy_type": policy_type}})
    if jurisdiction:
        # A clause tagged "national" should always be eligible regardless of
        # the claimant's state -- only exclude clauses tagged for a DIFFERENT
        # specific state than the claimant's.
        filters.append(
            {"bool": {"should": [{"term": {"jurisdiction": "national"}}, {"term": {"jurisdiction": jurisdiction}}]}}
        )

    bool_filter = {"filter": filters} if filters else {}

    body = {
        "size": k,
        "query": {
            "hybrid": {
                "queries": [
                    {"bool": {**bool_filter, "must": [{"multi_match": {"query": query_text, "fields": ["heading^2", "text"]}}]}},
                    {
                        "bool": {
                            **bool_filter,
                            "must": [{"knn": {"embedding": {"vector": query_vector, "k": k}}}],
                        }
                    },
                ]
            }
        },
    }

    resp = os_client.search(
        index=INDEX_NAME,
        body=body,
        params={"search_pipeline": PIPELINE_NAME},
    )
    return [
        {
            "clause_id": hit["_source"]["clause_id"],
            "heading": hit["_source"]["heading"],
            "policy_type": hit["_source"]["policy_type"],
            "jurisdiction": hit["_source"]["jurisdiction"],
            "scope": hit["_source"]["scope"],
            "score": hit["_score"],
            "text": hit["_source"]["text"],
        }
        for hit in resp["hits"]["hits"]
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="The claim text / search query")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--policy-type", default=None, choices=["home", "motor", "travel"])
    parser.add_argument("--jurisdiction", default=None, help="e.g. QLD, VIC -- narrows regional exclusions")
    parser.add_argument("--opensearch-host", default="localhost")
    parser.add_argument("--opensearch-port", type=int, default=9200)
    parser.add_argument("--bedrock-profile", default="claimpilot")
    parser.add_argument("--bedrock-region", default="ap-southeast-2")
    args = parser.parse_args()

    os_client = get_opensearch_client(args.opensearch_host, args.opensearch_port)
    ensure_pipeline(os_client)

    session = boto3.Session(profile_name=args.bedrock_profile, region_name=args.bedrock_region)
    bedrock_client = session.client("bedrock-runtime")

    results = hybrid_search(
        os_client, bedrock_client, args.query, k=args.k, policy_type=args.policy_type, jurisdiction=args.jurisdiction
    )

    print(f"Query: {args.query!r}  (policy_type={args.policy_type}, jurisdiction={args.jurisdiction})\n")
    if not results:
        print("No results.")
        sys.exit(0)
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['score']:.4f}] {r['clause_id']} -- {r['heading']} ({r['policy_type']}/{r['scope']}/{r['jurisdiction']})")
        print(f"   {r['text'][:160]}{'...' if len(r['text']) > 160 else ''}")
        print()


if __name__ == "__main__":
    main()
