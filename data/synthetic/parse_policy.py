#!/usr/bin/env python3
"""
Parses a ClaimPilot policy wording Markdown document into structured clause
records. This is the "ingestion" half of the pipeline -- it's what turns a
realistic, document-shaped policy wording into the clause-level JSON that
gets chunked and indexed into OpenSearch.

Mirrors how a real policy PDF, converted to text, would be parsed: headings
define clause boundaries, section numbers imply scope, and jurisdiction is
detected from AU state/territory mentions rather than being pre-tagged.

Usage (standalone):
    python parse_policy.py policies/home.md > policies/home.json

Usage (imported, as generate.py does):
    from parse_policy import parse_policy_markdown
    policy = parse_policy_markdown(markdown_text, policy_type="home")
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Section number -> scope. This convention is fixed across all three policy
# types (home/motor/travel) even though each type's section TITLES differ
# (e.g. section 3 is "Buildings Cover" for home, "Vehicle Cover" for motor) --
# the parser only relies on the number, never the title text, to stay robust.
SECTION_SCOPE = {
    1: "definition",
    2: "coverage",
    3: "coverage",
    4: "coverage",
    5: "exclusion",
    6: "exclusion",
    7: "condition",
    8: "claims_process",
    9: "claims_process",
}

# AU states/territories the parser looks for when tagging jurisdiction.
# Full names are matched case-insensitively; abbreviations are matched
# CASE-SENSITIVELY and separately, because several abbreviations collide
# with ordinary English words when matched case-insensitively -- notably
# "ACT" vs the common word "act" (as in "criminal act"), but also "SA",
# "WA", "NT" are all short enough to risk false positives. An abbreviation
# only counts if it appears in actual uppercase in the text.
STATE_PATTERNS = [
    ("NSW", r"\bNew South Wales\b", r"\bNSW\b"),
    ("VIC", r"\bVictoria\b", r"\bVIC\b"),
    ("QLD", r"\bQueensland\b", r"\bQLD\b"),
    ("WA", r"\bWestern Australia\b", r"\bWA\b"),
    ("SA", r"\bSouth Australia\b", r"\bSA\b"),
    ("TAS", r"\bTasmania\b", r"\bTAS\b"),
    ("ACT", r"\bAustralian Capital Territory\b", r"\bACT\b"),
    ("NT", r"\bNorthern Territory\b", r"\bNT\b"),
]

HEADING_RE = re.compile(r"^###\s+(?P<clause_id>[A-Z]+-(?P<section>\d+)\.\d+)\s+(?P<heading>.+)$", re.MULTILINE)
DECL_SUM_INSURED_RE = re.compile(r"Sum Insured:\s*\$?([\d,]+)")
DECL_POLICY_LIMIT_RE = re.compile(r"Policy Limit:\s*\$?([\d,]+)")
DECL_EXCESS_RE = re.compile(r"Excess:\s*\$?([\d,]+)")
DECL_BASIS_RE = re.compile(r"Policy Basis:\s*(\w+)")


def detect_jurisdiction(text: str) -> str:
    """Flood must never resolve to a state -- Australia has a single
    national statutory flood definition, so a clause mentioning flood
    alongside a state name (e.g. "as defined nationally, applies in NSW
    too") should still default toward national unless the clause is
    UNAMBIGUOUSLY about a state-specific peril (cyclone, bushfire)."""
    if re.search(r"\bflood\b", text, re.IGNORECASE):
        return "national"
    for code, name_pattern, abbr_pattern in STATE_PATTERNS:
        if re.search(name_pattern, text, re.IGNORECASE):
            return code
        if re.search(abbr_pattern, text):  # case-sensitive -- see comment on STATE_PATTERNS above
            return code
    return "national"


def parse_policy_markdown(markdown_text: str, policy_type: str) -> dict:
    declarations = {"policy_type": policy_type}

    sum_insured_match = DECL_SUM_INSURED_RE.search(markdown_text)
    if sum_insured_match:
        declarations["sum_insured"] = int(sum_insured_match.group(1).replace(",", ""))

    policy_limit_match = DECL_POLICY_LIMIT_RE.search(markdown_text)
    if policy_limit_match:
        declarations["policy_limit"] = int(policy_limit_match.group(1).replace(",", ""))

    excess_match = DECL_EXCESS_RE.search(markdown_text)
    if excess_match:
        declarations["excess"] = int(excess_match.group(1).replace(",", ""))

    basis_match = DECL_BASIS_RE.search(markdown_text)
    if basis_match:
        declarations["policy_basis"] = basis_match.group(1)

    headings = list(HEADING_RE.finditer(markdown_text))
    clauses = []
    for i, m in enumerate(headings):
        clause_id = m.group("clause_id")
        section = int(m.group("section"))
        heading = m.group("heading").strip()
        start = m.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown_text)
        body = markdown_text[start:end].strip()

        scope = SECTION_SCOPE.get(section, "coverage")
        jurisdiction = detect_jurisdiction(heading + " " + body)

        clauses.append(
            {
                "clause_id": clause_id,
                "policy_type": policy_type,
                "jurisdiction": jurisdiction,
                "scope": scope,
                "heading": heading,
                "text": body,
            }
        )

    declarations["clauses"] = clauses
    return declarations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown_file", type=Path)
    parser.add_argument("--policy-type", default=None, help="Defaults to the file stem, e.g. home.md -> home")
    args = parser.parse_args()

    policy_type = args.policy_type or args.markdown_file.stem
    text = args.markdown_file.read_text()
    policy = parse_policy_markdown(text, policy_type)

    print(json.dumps(policy, indent=2))
    print(f"Parsed {len(policy['clauses'])} clauses from {args.markdown_file}", file=sys.stderr)


if __name__ == "__main__":
    main()
