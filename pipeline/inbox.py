"""Inbox: a fetching bot pushes JSON files into inbox/; they are never modified, only hashed in state.
Also holds the pure normalization of raw X API v2 responses (no network)."""
import hashlib
import json
from pathlib import Path


def _text(t):
    return (t.get("note_tweet") or {}).get("text") or t.get("text", "")


def _media(tweet, media_by_key):
    out = []
    for key in (tweet.get("attachments") or {}).get("media_keys", []):
        m = media_by_key.get(key)
        if not m:
            continue
        item = {"type": m.get("type"), "width": m.get("width"), "height": m.get("height")}
        if m.get("type") == "photo":
            item["url"] = m.get("url")
        else:
            item["variants"] = m.get("variants", [])
            item["url"] = m.get("preview_image_url")
        out.append(item)
    return out


def _is_reply(t):
    return any(r.get("type") == "replied_to" for r in t.get("referenced_tweets") or [])


def build_posts(username, resp, extra_replies=None):
    """Group a timeline response into root posts with the author's self-replies attached."""
    media_by_key = {m["media_key"]: m for m in (resp.get("includes") or {}).get("media", [])}
    tweets = list(resp.get("data") or []) + list(extra_replies or [])
    roots, replies = {}, {}
    for t in tweets:
        if not _is_reply(t):
            roots[t["id"]] = t
        elif t.get("in_reply_to_user_id") == t.get("author_id"):  # self-reply
            replies.setdefault(t.get("conversation_id"), []).append(t)
    posts = []
    for tid, t in roots.items():
        reps = sorted(replies.get(t.get("conversation_id", tid), []), key=lambda r: int(r["id"]))
        media = _media(t, media_by_key)
        for r in reps:  # the media may sit on a self-reply
            media = media or _media(r, media_by_key)
        posts.append({"tweet_id": tid, "url": f"https://x.com/{username}/status/{tid}", "author": username,
                      "text": _text(t), "prompt_text": "", "replies": [_text(r) for r in reps],
                      "media": media, "created_at": t.get("created_at", ""), "source": "inbox",
                      "conversation_id": t.get("conversation_id", tid), "author_id": t.get("author_id")})
    return posts


def posts_from_raw(resp):
    """Normalize a raw X API v2 response (as pushed by a bot) with the same grouping as build_posts."""
    inc = resp.get("includes") or {}
    users = {u["id"]: u["username"] for u in inc.get("users", []) if u.get("id") and u.get("username")}
    data = resp.get("data") or []
    data = [data] if isinstance(data, dict) else list(data)
    have = {t["id"] for t in data}
    # a self-reply's root may only be delivered under includes.tweets
    wanted = {t.get("conversation_id") for t in data if _is_reply(t)}
    data += [t for t in inc.get("tweets", []) if t["id"] in wanted and t["id"] not in have]
    by_author = {}
    for t in data:
        by_author.setdefault(t.get("author_id"), []).append(t)
    posts = []
    for author_id, tweets in by_author.items():
        if author_id not in users:
            continue  # cannot build a URL / attribute the post without a username
        for p in build_posts(users[author_id], {"data": tweets, "includes": inc}):
            p["source"] = "inbox"
            posts.append(p)
    return posts


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
    # an empty timeline comes back as {"meta": {"result_count": 0}} with no data/includes
    return isinstance(obj, dict) and "tweet_id" not in obj and ("data" in obj or "includes" in obj or "meta" in obj)


def parse(data):
    """Accept: normalized list, raw response, list of raws, {"responses": [...]}, {"posts": [...]} (items may be mixed)."""
    if isinstance(data, dict) and not _is_raw(data):
        data = data.get("responses") if "responses" in data else data.get("posts", [])
    if _is_raw(data):
        data = [data]
    posts = []
    for item in data:
        posts.extend(posts_from_raw(item) if _is_raw(item) else [normalize(item)])
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
