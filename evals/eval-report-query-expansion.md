# ClaimPilot eval report

Labelled claims: **50** &nbsp;·&nbsp; scored: **50** &nbsp;·&nbsp; errored: **0**

- **Decision accuracy:** 34/50 = **68%**
- **Expected-clause citation recall:** 47/59 = **80%** (10 claims missing at least one)
- **Claims that used the retry:** 14

## Missed expected clauses by cause

| Category | Missed clauses |
|---|---|
| corpus_gap | 0 |
| retrieval_miss | 4 |
| jurisdiction_filtered | 0 |
| citation_miss | 8 |
| **total** | **12** |

## Decisions: expected → actual

| Expected | Actual | Count |
|---|---|---|
| covered | covered | 9 |
| covered | not_covered | 1 |
| covered | partly_covered | 4 |
| covered | unsure | 6 |
| not_covered | not_covered | 22 |
| not_covered | unsure | 3 |
| partly_covered | partly_covered | 2 |
| unsure | not_covered | 1 |
| unsure | partly_covered | 1 |
| unsure | unsure | 1 |

## Per claim

| Claim | Policy / state | Expected | Actual (conf) | Match | Missed clauses (cause) |
|---|---|---|---|---|---|
| CLM-001 | home / NSW | covered | unsure (0.20) | ❌ | HOME-3.1 — retrieval_miss<br>HOME-3.2 — retrieval_miss |
| CLM-002 | home / QLD | not_covered | not_covered (0.95) | ✅ | — |
| CLM-003 | home / VIC | covered | covered (0.75) | ✅ | — |
| CLM-004 | home / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-005 | home / SA | not_covered | not_covered (0.95) | ✅ | — |
| CLM-006 | home / TAS | not_covered | not_covered (0.85) | ✅ | — |
| CLM-007 | home / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-008 | home / WA | not_covered | not_covered (0.95) | ✅ | — |
| CLM-009 | home / ACT | covered | partly_covered (0.82) | ❌ | — |
| CLM-010 | home / NSW | not_covered | not_covered (1.00) | ✅ | — |
| CLM-011 | motor / NSW | covered | unsure (0.30) | ❌ | MOTOR-3.1 — retrieval_miss |
| CLM-012 | motor / QLD | not_covered | not_covered (0.95) | ✅ | — |
| CLM-013 | motor / VIC | not_covered | not_covered (0.95) | ✅ | — |
| CLM-014 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-015 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-016 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-017 | motor / NSW | covered | covered (0.95) | ✅ | — |
| CLM-018 | motor / NSW | covered | covered (0.92) | ✅ | — |
| CLM-019 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-020 | motor / NSW | not_covered | not_covered (0.85) | ✅ | — |
| CLM-021 | travel / NSW | covered | covered (0.95) | ✅ | — |
| CLM-022 | travel / NSW | not_covered | not_covered (0.85) | ✅ | TRAVEL-3.3 — citation_miss |
| CLM-023 | travel / QLD | not_covered | not_covered (0.95) | ✅ | — |
| CLM-024 | travel / NSW | covered | partly_covered (0.85) | ❌ | — |
| CLM-025 | travel / NSW | covered | covered (0.92) | ✅ | — |
| CLM-026 | travel / NSW | not_covered | not_covered (0.75) | ✅ | — |
| CLM-027 | travel / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-028 | travel / NSW | not_covered | not_covered (0.85) | ✅ | — |
| CLM-029 | home / NSW | unsure | not_covered (0.85) | ❌ | — |
| CLM-030 | motor / NSW | unsure | partly_covered (0.85) | ❌ | — |
| CLM-031 | travel / NSW | covered | unsure (0.35) | ❌ | — |
| CLM-032 | home / NSW | covered | covered (0.75) | ✅ | — |
| CLM-033 | motor / NSW | covered | partly_covered (0.95) | ❌ | — |
| CLM-034 | home / NSW | covered | unsure (0.30) | ❌ | — |
| CLM-035 | home / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-036 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-037 | home / NSW | not_covered | unsure (0.20) | ❌ | HOME-5.1 — citation_miss |
| CLM-038 | travel / NSW | not_covered | unsure (0.30) | ❌ | TRAVEL-5.1 — citation_miss |
| CLM-039 | motor / NSW | covered | covered (0.85) | ✅ | — |
| CLM-040 | home / NSW | covered | unsure (0.25) | ❌ | HOME-3.2 — retrieval_miss |
| CLM-041 | home / NSW | not_covered | unsure (0.30) | ❌ | HOME-5.2 — citation_miss |
| CLM-042 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-043 | travel / NSW | covered | partly_covered (0.85) | ❌ | — |
| CLM-044 | home / NSW | covered | unsure (0.30) | ❌ | — |
| CLM-045 | motor / NSW | partly_covered | partly_covered (0.92) | ✅ | MOTOR-3.3 — citation_miss |
| CLM-046 | home / NSW | partly_covered | partly_covered (0.92) | ✅ | HOME-2.1 — citation_miss<br>HOME-3.6 — citation_miss |
| CLM-047 | travel / NSW | covered | covered (0.85) | ✅ | — |
| CLM-048 | motor / NSW | covered | not_covered (0.75) | ❌ | — |
| CLM-049 | home / NSW | unsure | unsure (0.10) | ✅ | HOME-3.1 — citation_miss |
| CLM-050 | travel / NSW | covered | covered (0.75) | ✅ | — |

## Miss details

- **CLM-001** HOME-3.1 — `retrieval_miss`: never in top results of any try
- **CLM-001** HOME-3.2 — `retrieval_miss`: never in top results of any try
- **CLM-011** MOTOR-3.1 — `retrieval_miss`: never in top results of any try
- **CLM-022** TRAVEL-3.3 — `citation_miss`: retrieved (try 1), not cited
- **CLM-037** HOME-5.1 — `citation_miss`: retrieved (try 1), not cited
- **CLM-038** TRAVEL-5.1 — `citation_miss`: retrieved (retry only), not cited
- **CLM-040** HOME-3.2 — `retrieval_miss`: never in top results of any try
- **CLM-041** HOME-5.2 — `citation_miss`: retrieved (try 1), not cited
- **CLM-045** MOTOR-3.3 — `citation_miss`: retrieved (try 1), not cited
- **CLM-046** HOME-2.1 — `citation_miss`: retrieved (try 1), not cited
- **CLM-046** HOME-3.6 — `citation_miss`: retrieved (try 1), not cited
- **CLM-049** HOME-3.1 — `citation_miss`: retrieved (try 1), not cited
