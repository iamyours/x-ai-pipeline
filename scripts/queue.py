#!/usr/bin/env python3
"""Video queue CLI for bots (stdlib only). Operates on pending_videos.json at the repo root.

  queue.py list [--status pending]
  queue.py show SLUG
  queue.py mark SLUG done|rejected|pending [--video-url URL] [--note TEXT]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import queue as q  # noqa: E402  (pipeline/queue.py, stdlib only)

FILE = Path(__file__).resolve().parent.parent / "pending_videos.json"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--status", choices=q.STATUSES)
    sub.add_parser("show").add_argument("slug")
    mk = sub.add_parser("mark")
    mk.add_argument("slug")
    mk.add_argument("status", choices=q.STATUSES)
    mk.add_argument("--video-url")
    mk.add_argument("--note")
    args = ap.parse_args(argv)

    entries = q.load(FILE)
    if args.cmd == "list":
        rows = [e for e in entries if not args.status or e["status"] == args.status]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif args.cmd == "show":
        hit = next((e for e in entries if e["slug"] == args.slug), None)
        if not hit:
            print(f"未找到 {args.slug}", file=sys.stderr)
            return 1
        print(json.dumps(hit, ensure_ascii=False, indent=2))
    else:
        try:
            e = q.mark(entries, args.slug, args.status, args.video_url, args.note)
        except KeyError:
            print(f"未找到 {args.slug}", file=sys.stderr)
            return 1
        q.save(FILE, entries)
        print(json.dumps(e, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
