"""
find_repo_root(): walk up from a given directory until one containing
`.git` is found, rather than a hardcoded number of `.parent` calls or a
hardcoded `parents[N]` index.

Why this exists: `app/agent/run.py`'s CLAIMS_FILE and the repo-root
`ingest.py`'s POLICY_DIR both used hardcoded parent-counting, and
ingest.py's broke in practice -- it turned out to live one directory
level deeper in the real repo than assumed when it was written, so the
hardcoded count silently resolved to the WRONG (but existing) directory
instead of raising a clear error. Walking up to a `.git` marker is immune
to any of these scripts moving to a different depth later.
"""

from pathlib import Path


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"Could not find repo root (no .git found walking up from {start})")
