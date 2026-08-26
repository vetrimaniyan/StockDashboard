"""Regenerate METRICS.md from the registry (NFR-5.6)."""

from __future__ import annotations

from alpha500.config import REPO_ROOT
from alpha500.metrics import registry


def main() -> int:
    target = REPO_ROOT / "METRICS.md"
    target.write_text(registry.to_markdown(), encoding="utf-8")
    print(f"Wrote {target} ({len(registry.REGISTRY)} metrics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
