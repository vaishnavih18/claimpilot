# ClaimPilot eval report

Labelled claims: **50** &nbsp;·&nbsp; scored: **50** &nbsp;·&nbsp; errored: **0**

- **Decision accuracy:** 32/50 = **64%**
- **Expected-clause citation recall:** 43/59 = **73%** (14 claims missing at least one)
- **Claims that used the retry:** 16

## Missed expected clauses by cause

| Category | Missed clauses |
|---|---|
| corpus_gap | 0 |
| retrieval_miss | 13 |
| jurisdiction_filtered | 0 |
| citation_miss | 3 |
| **total** | **16** |

## Decisions: expected → actual

| Expected | Actual | Count |
|---|---|---|
| covered | covered | 9 |
| covered | partly_covered | 3 |
| covered | unsure | 8 |
| not_covered | not_covered | 20 |
| not_covered | unsure | 5 |
| partly_covered | partly_covered | 2 |
| unsure | not_covered | 1 |
| unsure | partly_covered | 1 |
| unsure | unsure | 1 |

## Per claim

| Claim | Policy / state | Expected | Actual (conf) | Match | Missed clauses (cause) |
|---|---|---|---|---|---|
| CLM-001 | home / NSW | covered | unsure (0.30) | ❌ | HOME-3.1 — retrieval_miss |
| CLM-002 | home / QLD | not_covered | unsure (0.75) | ❌ | — |
| CLM-003 | home / VIC | covered | covered (0.72) | ✅ | — |
| CLM-004 | home / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-005 | home / SA | not_covered | not_covered (0.95) | ✅ | — |
| CLM-006 | home / TAS | not_covered | not_covered (0.85) | ✅ | — |
| CLM-007 | home / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-008 | home / WA | not_covered | not_covered (0.95) | ✅ | — |
| CLM-009 | home / ACT | covered | unsure (0.30) | ❌ | HOME-4.1 — retrieval_miss |
| CLM-010 | home / NSW | not_covered | not_covered (1.00) | ✅ | — |
| CLM-011 | motor / NSW | covered | unsure (0.35) | ❌ | MOTOR-3.1 — retrieval_miss |
| CLM-012 | motor / QLD | not_covered | not_covered (0.95) | ✅ | — |
| CLM-013 | motor / VIC | not_covered | not_covered (0.95) | ✅ | — |
| CLM-014 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-015 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-016 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-017 | motor / NSW | covered | covered (0.92) | ✅ | — |
| CLM-018 | motor / NSW | covered | covered (0.92) | ✅ | — |
| CLM-019 | motor / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-020 | motor / NSW | not_covered | not_covered (0.85) | ✅ | — |
| CLM-021 | travel / NSW | covered | covered (0.95) | ✅ | — |
| CLM-022 | travel / NSW | not_covered | not_covered (0.85) | ✅ | — |
| CLM-023 | travel / QLD | not_covered | not_covered (0.95) | ✅ | — |
| CLM-024 | travel / NSW | covered | partly_covered (0.85) | ❌ | — |
| CLM-025 | travel / NSW | covered | covered (0.92) | ✅ | — |
| CLM-026 | travel / NSW | not_covered | not_covered (0.85) | ✅ | TRAVEL-3.3 — retrieval_miss |
| CLM-027 | travel / NSW | not_covered | not_covered (0.95) | ✅ | — |
| CLM-028 | travel / NSW | not_covered | unsure (0.00) | ❌ | TRAVEL-5.2 — retrieval_miss |
| CLM-029 | home / NSW | unsure | not_covered (0.85) | ❌ | — |
| CLM-030 | motor / NSW | unsure | partly_covered (0.85) | ❌ | — |
| CLM-031 | travel / NSW | covered | unsure (0.30) | ❌ | — |
| CLM-032 | home / NSW | covered | covered (0.72) | ✅ | — |
| CLM-033 | motor / NSW | covered | partly_covered (0.92) | ❌ | — |
| CLM-034 | home / NSW | covered | unsure (0.20) | ❌ | HOME-3.1 — retrieval_miss<br>HOME-3.2 — retrieval_miss |
| CLM-035 | home / NSW | not_covered | not_covered (0.92) | ✅ | — |
| CLM-036 | motor / NSW | not_covered | not_covered (0.92) | ✅ | — |
| CLM-037 | home / NSW | not_covered | unsure (0.20) | ❌ | HOME-5.1 — retrieval_miss |
| CLM-038 | travel / NSW | not_covered | unsure (0.20) | ❌ | TRAVEL-5.1 — retrieval_miss |
| CLM-039 | motor / NSW | covered | covered (0.85) | ✅ | — |
| CLM-040 | home / NSW | covered | unsure (0.20) | ❌ | HOME-3.1 — retrieval_miss<br>HOME-3.2 — retrieval_miss |
| CLM-041 | home / NSW | not_covered | unsure (0.30) | ❌ | — |
| CLM-042 | motor / NSW | not_covered | not_covered (0.95) | ✅ | MOTOR-5.1 — citation_miss |
| CLM-043 | travel / NSW | covered | partly_covered (0.85) | ❌ | — |
| CLM-044 | home / NSW | covered | unsure (0.30) | ❌ | — |
| CLM-045 | motor / NSW | partly_covered | partly_covered (0.90) | ✅ | MOTOR-3.3 — citation_miss |
| CLM-046 | home / NSW | partly_covered | partly_covered (0.85) | ✅ | HOME-3.6 — retrieval_miss |
| CLM-047 | travel / NSW | covered | covered (0.88) | ✅ | — |
| CLM-048 | motor / NSW | covered | unsure (0.30) | ❌ | MOTOR-3.1 — retrieval_miss |
| CLM-049 | home / NSW | unsure | unsure (0.15) | ✅ | HOME-3.1 — citation_miss |
| CLM-050 | travel / NSW | covered | covered (0.85) | ✅ | — |

## Miss details

- **CLM-001** HOME-3.1 — `retrieval_miss`: never in top results of any try
- **CLM-009** HOME-4.1 — `retrieval_miss`: never in top results of any try
- **CLM-011** MOTOR-3.1 — `retrieval_miss`: never in top results of any try
- **CLM-026** TRAVEL-3.3 — `retrieval_miss`: never in top results of any try
- **CLM-028** TRAVEL-5.2 — `retrieval_miss`: never in top results of any try
- **CLM-034** HOME-3.1 — `retrieval_miss`: never in top results of any try
- **CLM-034** HOME-3.2 — `retrieval_miss`: never in top results of any try
- **CLM-037** HOME-5.1 — `retrieval_miss`: never in top results of any try
- **CLM-038** TRAVEL-5.1 — `retrieval_miss`: never in top results of any try
- **CLM-040** HOME-3.1 — `retrieval_miss`: never in top results of any try
- **CLM-040** HOME-3.2 — `retrieval_miss`: never in top results of any try
- **CLM-042** MOTOR-5.1 — `citation_miss`: retrieved (try 1), not cited
- **CLM-045** MOTOR-3.3 — `citation_miss`: retrieved (try 1), not cited
- **CLM-046** HOME-3.6 — `retrieval_miss`: never in top results of any try
- **CLM-048** MOTOR-3.1 — `retrieval_miss`: never in top results of any try
- **CLM-049** HOME-3.1 — `citation_miss`: retrieved (try 1), not cited
