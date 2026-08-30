"""Run the public collector or process already-sanitized bridge input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, Sequence

from .pipeline import rank_items
from .sources import fetch_hacker_news, fetch_from_config
from .mailer import send_digest

def _load_input(path: str, max_bytes: int = 1_000_000) -> list[dict]:
    source = Path(path)
    if source.stat().st_size > max_bytes:
        raise ValueError("input exceeds the byte limit")
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError("input must be a JSON list")
    return raw

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--hacker-news", action="store_true")
    group.add_argument("--config", action="store_true", help="use NEWS_SOURCE_CONFIG_JSON")
    group.add_argument("--input", help="local JSON list from a narrow private bridge")
    parser.add_argument("--max-items", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true", help="print email instead of sending")
    return parser

def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    
    if args.config:
        raw = fetch_from_config()
    elif args.hacker_news:
        raw = fetch_hacker_news(limit=min(args.max_items * 3, 50))
    else:
        raw = _load_input(args.input)
        
    ranked = rank_items(raw, limit=args.max_items)
    print(json.dumps(ranked, indent=2, sort_keys=True))
    
    # Send email
    if args.config or args.dry_run:
        send_digest(ranked, dry_run=args.dry_run)
        
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
