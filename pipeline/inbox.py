"""Inbox mode: bots push JSON files into inbox/; they are never modified, only hashed in state."""
import hashlib
import json
from pathlib import Path

from . import xapi


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def normalize(item):
    """Coerce an inbox item into the internal post shape."""
    author = str(item.get("author", "")).lstrip("@")
    return {
        "tweet_id": str(item["tweet_id"]),
        "url": item.get("url") or f"https://x.com/{author}/status/{item['tweet_id']}",
        "author": author,
        "text": item.get("text", "") or "",
        "prompt_text": item.get("prompt_text", "") or "",
        "replies": list(item.get("replies") or []),
        "media": list(item.get("media") or []),
        "created_at": item.get("created_at", ""),
        "source": "inbox",
    }


def _is_raw(obj):
    """A raw X API v2 response has data/includes and no normalized tweet_id."""
    return isinstance(obj, dict) and "tweet_id" not in obj and ("data" in obj or "includes" in obj)


def parse(data):
    """Accept: normalized list, raw response, list of raws, {"responses": [...]}, {"posts": [...]} (items may be mixed)."""
    if isinstance(data, dict) and not _is_raw(data):
        data = data.get("responses") if "responses" in data else data.get("posts", [])
    if _is_raw(data):
        data = [data]
    posts = []
    for item in data:
        posts.extend(xapi.posts_from_raw(item) if _is_raw(item) else [normalize(item)])
    return posts


def load_new(inbox_dir, processed):
    """Return [(filename, sha, [posts])] for files whose hash differs from state.processed_inbox."""
    out = []
    for path in sorted(Path(inbox_dir).glob("*.json")):
        sha = sha256_file(path)
        if processed.get(path.name) == sha:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            posts = parse(data)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            print(f"[inbox] 跳过无法解析的文件 {path.name}: {e}", flush=True)
            continue
        out.append((path.name, sha, posts))
    return out
