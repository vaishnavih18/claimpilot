"""
Importable hybrid search (BM25 + k-NN), for the agent's retrieve_node.

This deliberately duplicates /home/claude/hybrid_search.py's query logic
rather than importing it: that script lives at the repo root as a
standalone CLI spot-check tool (`python hybrid_search.py "query"`), not
inside the `app` package, so importing it here would mean reaching
outside the package across a boundary that isn't guaranteed stable (it's
a dev tool, meant to be run directly, not depended on). If the two ever
drift, hybrid_search.py is the one to treat as the spot-check copy and
this one as the source of truth, since this is what production actually
runs. Worth consolidating into one shared, importable module later (e.g.
move this logic into app/ingest/ alongside the indexer) if the CLI tool
keeps being useful enough to maintain.
"""

import json

from opensearchpy import OpenSearch

from app.agent.state import RetrievedClause

INDEX_NAME = "policy-clauses"
PIPELINE_NAME = "hybrid-search-pipeline"

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


def ensure_search_pipeline(client: OpenSearch) -> None:
    """Idempotent - PUT-ing the same pipeline body again is a no-op, so
    this is called on every retrieve rather than once at startup. Simpler
    than tracking "has this process already ensured the pipeline exists"
    across pod restarts for a call that costs nothing when it's a no-op."""
    client.transport.perform_request("PUT", f"/_search/pipeline/{PIPELINE_NAME}", body=json.dumps(PIPELINE_BODY))


def embed_query(bedrock_client, text: str) -> list[float]:
    from app.agent.clients import EMBEDDING_MODEL_ID

    resp = bedrock_client.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text}),
    )
    return json.loads(resp["body"].read())["embedding"]


def hybrid_search(
    os_client: OpenSearch,
    bedrock_client,
    query_text: str,
    k: int = 8,
    policy_type: str | None = None,
    jurisdiction: str | None = None,
) -> list[RetrievedClause]:
    """
    policy_type is always worth filtering on when known (a home claim has
    no business matching a motor clause). jurisdiction is the dial the
    retry widens: dropping it (pass None) lets clauses tagged for OTHER
    states back into the results, which matters if the first retrieval's
    jurisdiction filter was itself the reason the right clause got missed
    (e.g. a claim mentioning facts the generator didn't tag precisely).
    """
    query_vector = embed_query(bedrock_client, query_text)

    filters = []
    if policy_type:
        filters.append({"term": {"policy_type": policy_type}})
    if jurisdiction:
        # A "national" clause is always in scope regardless of the
        # claimant's state - only a DIFFERENT specific state's clause
        # should be excluded.
        filters.append({"bool": {"should": [{"term": {"jurisdiction": "national"}}, {"term": {"jurisdiction": jurisdiction}}]}})

    bool_filter = {"filter": filters} if filters else {}

    body = {
        "size": k,
        "query": {
            "hybrid": {
                "queries": [
                    {"bool": {**bool_filter, "must": [{"multi_match": {"query": query_text, "fields": ["heading^2", "text"]}}]}},
                    {"knn": {"embedding": {"vector": query_vector, "k": k, "filter": {"bool": bool_filter} if filters else None}}},
                ]
            }
        },
    }

    resp = os_client.search(index=INDEX_NAME, body=body, params={"search_pipeline": PIPELINE_NAME})

    return [
        RetrievedClause(
            clause_id=hit["_source"]["clause_id"],
            heading=hit["_source"]["heading"],
            text=hit["_source"]["text"],
            policy_type=hit["_source"]["policy_type"],
            jurisdiction=hit["_source"]["jurisdiction"],
            scope=hit["_source"]["scope"],
            score=hit["_score"],
        )
        for hit in resp["hits"]["hits"]
    ]
