#!/usr/bin/env python3
"""Backfill original X post images into existing gallery works (local only, no network).

  backfill_originals.py <gallery_dir> <data_date_dir>

For works/<date>-x-<author>-<tweet_id> with <data_date_dir>/<author>-<tweet_id>/{post.json,orig-*.jpg},
writes orig-N.webp and adds `originals` + `originals_credit` to manifest.json.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.gallery import backfill_originals  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gallery_dir")
    ap.add_argument("data_date_dir")
    args = ap.parse_args(argv)
    n = backfill_originals(args.gallery_dir, args.data_date_dir)
    print(f"[backfill] updated {n} work(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
