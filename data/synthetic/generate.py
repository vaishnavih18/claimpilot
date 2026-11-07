#!/usr/bin/env python3
"""
ClaimPilot synthetic data generator.

Generates 3 fictional AU policy wordings (home, motor, travel) as realistic
Markdown documents -- ~45-55 clauses each, organised into 9 sections like a
real Product Disclosure Statement (definitions, cover, exclusions,
conditions, claims process, complaints). Each policy is generated section
by section (not in one shot) so clause quality stays high across a long
document.

Then parses those documents with parse_policy.py (the same parser your
ingestion pipeline will use later) to get structured clauses, and generates
60 fictional claims (45 labelled with an eval answer key, 15 unlabelled to
simulate live traffic for the demo) that cite real clause_ids from the
parsed policies.

Uses Claude Haiku 4.5 on Amazon Bedrock (ap-southeast-2 / Sydney, `au.`
inference profile). All data is fictional -- no real insurer wording or
real claimant information is used anywhere.

Usage:
    python generate.py

Output:
    data/synthetic/policies/home.md       (and motor.md, travel.md)
    data/synthetic/policies/home.json     (parsed -- and motor.json, travel.json)
    data/synthetic/claims/claims.jsonl
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

import boto3

from parse_policy import parse_policy_markdown

OUT_DIR = Path(__file__).resolve().parent
POLICY_DIR = OUT_DIR / "policies"
CLAIMS_DIR = OUT_DIR / "claims"

PREFIXES = {"home": "HOME", "motor": "MOTOR", "travel": "TRAVEL"}

# Section plan per policy type. Section NUMBER drives scope in parse_policy.py
# (fixed across all 3 types); section TITLE is policy-type-specific so the
# document reads like a real PDS for that product. target_clauses is a
# *target* -- the LLM may land a little above or below it.
SECTION_PLAN = {
    "home": [
        (1, "Definitions", 5),
        (2, "Significant Features and Benefits", 4),
        (3, "Buildings Cover", 6),
        (4, "Contents Cover", 5),
        (5, "General Exclusions", 6),
        (6, "Specific Peril and Regional Exclusions", 5),
        (7, "Conditions", 6),
        (8, "Claims Process", 5),
        (9, "Complaints and Dispute Resolution", 3),
    ],
    "motor": [
        (1, "Definitions", 5),
        (2, "Significant Features and Benefits", 4),
        (3, "Vehicle Damage Cover", 6),
        (4, "Liability and Additional Benefits Cover", 5),
        (5, "General Exclusions", 6),
        (6, "Specific Peril and Regional Exclusions", 5),
        (7, "Conditions", 6),
        (8, "Claims Process", 5),
        (9, "Complaints and Dispute Resolution", 3),
    ],
    "travel": [
        (1, "Definitions", 5),
        (2, "Significant Features and Benefits", 4),
        (3, "Trip Cancellation and Cover", 6),
        (4, "Medical and Emergency Cover", 5),
        (5, "General Exclusions", 6),
        (6, "Specific Peril and Regional Exclusions", 5),
        (7, "Conditions", 6),
        (8, "Claims Process", 5),
        (9, "Complaints and Dispute Resolution", 3),
    ],
}

# Declarations are generated in code, not by the LLM -- guarantees clean,
# parseable values instead of hoping the model formats a dollar figure
# consistently across 3 separate calls.
DECLARATIONS = {
    "home": lambda rng: {
        "sum_insured": rng.choice([450000, 550000, 650000, 750000, 900000]),
        "policy_basis": rng.choices(["sum_insured", "total_replacement"], weights=[85, 15])[0],
        "excess": rng.choice([300, 500, 750, 1000]),
    },
    "motor": lambda rng: {
        "sum_insured": rng.choice([18000, 25000, 35000, 45000, 60000]),
        "policy_basis": rng.choices(["sum_insured", "total_replacement"], weights=[90, 10])[0],
        "excess": rng.choice([400, 600, 900, 1200]),
    },
    "travel": lambda rng: {
        "policy_limit": rng.choice([50000, 100000, 250000]),
        "excess": rng.choice([100, 200, 300]),
    },
}

SECTION_PROMPT = """You are drafting part of a FICTIONAL Australian {policy_type} insurance \
policy wording, for a synthetic test dataset. Do not reproduce or closely paraphrase any real \
insurer's actual wording -- invent original content in a realistic AU insurance style.

This policy's declarations: {declarations_json}

Write ONLY section {section_num}, titled "{section_title}", as Markdown. Write approximately \
{target_clauses} clauses. Each clause MUST follow this exact format:

### {prefix}-{section_num}.<subsection number, starting at 1> <Clause Heading>
<1-4 sentences of clause wording prose>

{section_guidance}

Return ONLY the Markdown for this section (starting with the first ### heading) -- \
no section title heading, no preamble, no other text."""

SECTION_GUIDANCE = {
    5: "This is GENERAL exclusions -- keep every clause nationally applicable (e.g. wear and "
    "tear, intentional damage, unlawful use, gradual deterioration). Do NOT mention a specific "
    "state/territory here. If you cover flood, describe it as a national standard exclusion "
    "(Australia has one statutory flood definition, not a state-by-state one).",
    6: "This is REGIONAL exclusions -- each clause should name ONE specific AU state or "
    "territory (NSW, VIC, QLD, WA, SA, TAS, ACT, or NT) and a peril genuinely concentrated "
    "there (e.g. cyclone in QLD/NT/northern WA, bushfire in VIC/NSW/SA). Do not use flood here.",
}

CLAIMS_PROMPT = """You are generating FICTIONAL insurance claims for a synthetic test dataset, \
for testing an AI claims-triage system. No real claimant information.

Here are the policy clauses to write claims against (use these clause_ids exactly, do not \
invent new ones):

{clauses_summary}

Generate {n} claims as a JSON array. {n_labelled} of them MUST include an "expected_decision" \
and "expected_clauses" answer key (set is_labelled: true); the rest have is_labelled: false and \
omit those two fields.

Each claim:
{{
  "claim_id": "CLM-<3 digit number>",
  "policy_type": "home" | "motor" | "travel",
  "claimant_state": "<AU state/territory code>",
  "text": "<2-4 sentences, first person, describing what happened>",
  "amount_claimed": <integer AUD>,
  "prior_claims_count": <integer 0-3, mostly 0>,
  "is_labelled": true | false,
  "expected_decision": "covered" | "partly_covered" | "not_covered" | "unsure"   (labelled only)
  "expected_clauses": ["<clause_id>", ...]   (labelled only, must be real clause_ids above)
  "notes": "<one sentence on why this decision, for human review>"   (labelled only)
}}

Make the set varied and realistic:
- Mix of clearly covered, clearly excluded, and genuinely ambiguous cases
- At least 5 claims where amount_claimed exceeds the relevant sum_insured/policy_limit (for \
  partly_covered / total-loss-style cases)
- At least 4 claims that hit a regional (state-specific) exclusion clause from section 6
- At least 3 claims from claimants with prior_claims_count >= 2 (risk signal cases)
- Spread roughly evenly across home/motor/travel

IMPORTANT -- expected_clauses rule: only cite clauses that establish COVERAGE, an EXCLUSION, \
or a CONDITION that was breached -- i.e. clauses that actually determine the decision. Do NOT \
cite a claims-process clause (notification deadlines, documentation requirements, assessment \
procedure, payment timing) as a reason something is covered or not covered. The ONLY exception: \
if a claim's decision genuinely hinges on a process failure (e.g. the claimant notified us 90 \
days after the loss, breaching the 30-day notification clause), you may cite that clause -- and \
in that case the claim's "text" must actually describe the late notification, and "notes" must \
say that's why. For ordinary coverage/exclusion claims, expected_clauses should only ever contain \
clauses from sections 1-6 (definitions, coverage, exclusions) or section 7 (conditions breached), \
never section 8 or 9 (claims process, complaints) unless that exception applies.

Return ONLY the JSON array, no other text."""


def converse(client, model_id: str, prompt: str, max_tokens: int = 4096, temperature: float = 0.7) -> str:
    resp = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    return resp["output"]["message"]["content"][0]["text"]


def extract_json(text: str):
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def declarations_markdown(policy_type: str, decl: dict) -> str:
    lines = [f"# {policy_type.title()} Insurance Policy Wording", "", "## Declarations", ""]
    if "sum_insured" in decl:
        lines.append(f"- Sum Insured: ${decl['sum_insured']:,}")
    if "policy_limit" in decl:
        lines.append(f"- Policy Limit: ${decl['policy_limit']:,}")
    if "policy_basis" in decl:
        lines.append(f"- Policy Basis: {decl['policy_basis']}")
    lines.append(f"- Excess: ${decl['excess']:,}")
    lines.append("")
    return "\n".join(lines)


def generate_policy_markdown(client, model_id: str, policy_type: str, rng: random.Random) -> str:
    decl = DECLARATIONS[policy_type](rng)
    md = [declarations_markdown(policy_type, decl)]

    for section_num, section_title, target_clauses in SECTION_PLAN[policy_type]:
        guidance = SECTION_GUIDANCE.get(section_num, "Keep all clauses nationally applicable (jurisdiction: national).")
        prompt = SECTION_PROMPT.format(
            policy_type=policy_type,
            declarations_json=json.dumps(decl),
            section_num=section_num,
            section_title=section_title,
            target_clauses=target_clauses,
            prefix=PREFIXES[policy_type],
            section_guidance=guidance,
        )
        section_md = converse(client, model_id, prompt, max_tokens=2048).strip()
        md.append(f"## {section_num}. {section_title}\n")
        md.append(section_md)
        md.append("")
        n_clauses = len(re.findall(r"^### ", section_md, re.MULTILINE))
        print(f"  {policy_type} section {section_num} ({section_title}): {n_clauses} clauses")

    return "\n".join(md)


def generate_claims(client, model_id: str, policies: dict, n: int, n_labelled: int) -> list:
    clauses_summary = json.dumps(
        {
            pt: [
                {"clause_id": c["clause_id"], "scope": c["scope"], "jurisdiction": c["jurisdiction"], "heading": c["heading"]}
                for c in p["clauses"]
            ]
            for pt, p in policies.items()
        },
        indent=2,
    )
    prompt = CLAIMS_PROMPT.format(clauses_summary=clauses_summary, n=n, n_labelled=n_labelled)
    raw = converse(client, model_id, prompt, max_tokens=16384, temperature=0.8)
    return extract_json(raw)


def validate_claims(claims: list, policies: dict) -> list:
    all_clause_ids = {c["clause_id"] for p in policies.values() for c in p["clauses"]}
    problems = []
    for claim in claims:
        if claim.get("is_labelled"):
            bad = [cid for cid in claim.get("expected_clauses", []) if cid not in all_clause_ids]
            if bad:
                problems.append((claim["claim_id"], bad))
    if problems:
        print("WARNING: labelled claims citing unknown clause_ids (fix manually):", file=sys.stderr)
        for claim_id, bad in problems:
            print(f"  {claim_id}: {bad}", file=sys.stderr)
    return claims


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model-id",
        default="au.anthropic.claude-haiku-4-5-20251001-v1:0",
        help="Bedrock inference profile ID (default: Haiku 4.5, Sydney cross-region profile)",
    )
    parser.add_argument("--region", default="ap-southeast-2")
    parser.add_argument("--profile", default="claimpilot")
    parser.add_argument("--n-claims", type=int, default=60)
    parser.add_argument("--n-labelled", type=int, default=45)
    parser.add_argument("--seed", type=int, default=42, help="Seed for declarations (sum insured etc.) -- change for a different draw")
    parser.add_argument(
        "--claims-only",
        action="store_true",
        help="Skip policy generation; load existing policies/*.json (already parsed) and only (re)generate claims.jsonl",
    )
    args = parser.parse_args()

    POLICY_DIR.mkdir(parents=True, exist_ok=True)
    CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    client = session.client("bedrock-runtime")

    policies = {}
    if args.claims_only:
        print("Loading existing parsed policies (--claims-only) ...")
        for policy_type in ("home", "motor", "travel"):
            json_path = POLICY_DIR / f"{policy_type}.json"
            if not json_path.exists():
                print(f"ERROR: {json_path} not found -- run without --claims-only first.", file=sys.stderr)
                sys.exit(1)
            policies[policy_type] = json.loads(json_path.read_text())
            print(f"  {policy_type}: {len(policies[policy_type]['clauses'])} clauses loaded from {json_path.name}")
    else:
        print(f"Generating policies with {args.model_id} (section by section) ...")
        for policy_type in ("home", "motor", "travel"):
            md_text = generate_policy_markdown(client, args.model_id, policy_type, rng)
            md_path = POLICY_DIR / f"{policy_type}.md"
            md_path.write_text(md_text)

            policy = parse_policy_markdown(md_text, policy_type)
            policies[policy_type] = policy
            json_path = POLICY_DIR / f"{policy_type}.json"
            json_path.write_text(json.dumps(policy, indent=2))

            print(f"  {policy_type}: {len(policy['clauses'])} total clauses -> {md_path.name}, {json_path.name}")

    print(f"\nGenerating {args.n_claims} claims ({args.n_labelled} labelled) ...")
    claims = generate_claims(client, args.model_id, policies, n=args.n_claims, n_labelled=args.n_labelled)
    claims = validate_claims(claims, policies)

    claims_path = CLAIMS_DIR / "claims.jsonl"
    with claims_path.open("w") as f:
        for claim in claims:
            f.write(json.dumps(claim) + "\n")

    labelled = sum(1 for c in claims if c.get("is_labelled"))
    print(f"  wrote {claims_path} ({len(claims)} claims, {labelled} labelled)")
    print("\nDone. Spot-check a few clauses and claims by hand before building the ingestion pipeline.")


if __name__ == "__main__":
    main()