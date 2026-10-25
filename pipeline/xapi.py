"""X API v2 client. Set FAKE_X_FIXTURE=<json path> to use canned responses (tests, no network)."""
import json
import os

import requests

BASE = "https://api.x.com/2"
TWEET_FIELDS = "created_at,conversation_id,note_tweet,author_id,referenced_tweets,in_reply_to_user_id"
MEDIA_FIELDS = "url,variants,type,preview_image_url,width,height"


class RateLimited(Exception):
    pass


class _FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text, self.headers = data, status, json.dumps(data), {}

    def json(self):
        return self._data


class FakeSession:
    """Serves responses from a fixture: {users: {name: id}, tweets: {id: resp}, search: {conv_id: resp}}."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            self.fx = json.load(f)

    def get(self, url, params=None, headers=None, timeout=None):
        rest = url[len(BASE):]
        if rest.startswith("/users/by/username/"):
            uid = self.fx.get("users", {}).get(rest.rsplit("/", 1)[1])
            return _FakeResponse({"data": {"id": uid}} if uid else {"errors": ["nf"]}, 200 if uid else 404)
        if rest.startswith("/users/") and rest.endswith("/tweets"):
            return _FakeResponse(self.fx.get("tweets", {}).get(rest.split("/")[2], {}))
        if rest.startswith("/tweets/search/recent"):
            conv = (params or {}).get("query", "").split("conversation_id:")[-1].split()[0]
            return _FakeResponse(self.fx.get("search", {}).get(conv, {}))
        return _FakeResponse({}, 404)


class XClient:
    def __init__(self, token):
        fake = os.environ.get("FAKE_X_FIXTURE")
        self.session = FakeSession(fake) if fake else requests.Session()
        self.headers = {"Authorization": f"Bearer {token}"}

    def _get(self, path, params=None):
        r = self.session.get(BASE + path, params=params, headers=self.headers, timeout=30)
        if r.status_code == 429:
            raise RateLimited()
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code} {path}: {r.text[:200]}")
        return r.json()

    def user_id(self, username, cache):
        if username not in cache:
            cache[username] = self._get(f"/users/by/username/{username}")["data"]["id"]
        return cache[username]

    def timeline(self, uid, max_results, since_id=None):
        params = {"max_results": max(5, min(100, max_results)), "exclude": "retweets",
                  "expansions": "attachments.media_keys", "media.fields": MEDIA_FIELDS,
                  "tweet.fields": TWEET_FIELDS}
        if since_id:
            params["since_id"] = since_id
        return self._get(f"/users/{uid}/tweets", params)

    def search_conversation(self, conv_id, username):
        params = {"query": f"conversation_id:{conv_id} from:{username}", "expansions": "attachments.media_keys",
                  "media.fields": MEDIA_FIELDS, "tweet.fields": TWEET_FIELDS}
        return self._get("/tweets/search/recent", params)


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
                      "media": media, "created_at": t.get("created_at", ""), "source": "x_api",
                      "conversation_id": t.get("conversation_id", tid), "author_id": t.get("author_id")})
    return posts


def fetch_all(token, config, state, log=print, has_prompt=lambda p: True):
    """Fetch posts for every account. Returns (posts, newest_id_by_user). Never raises per account."""
    client = XClient(token)
    posts, newest = [], {}
    for username in config["accounts"]:
        try:
            uid = client.user_id(username, state.setdefault("user_ids", {}))
            resp = client.timeline(uid, config.get("max_posts_per_account", 10),
                                   state.get("last_since_id", {}).get(username))
            user_posts = build_posts(username, resp)
            ids = [int(t["id"]) for t in resp.get("data") or []]
            if ids:
                newest[username] = str(max(ids))
            for p in user_posts:
                if has_prompt(p):
                    continue
                try:  # recent search may be unavailable on this plan
                    found = client.search_conversation(p["conversation_id"], username)
                    for t in found.get("data") or []:
                        t.setdefault("author_id", p["author_id"])
                        if _is_reply(t) and t.get("in_reply_to_user_id") == p["author_id"]:
                            p["replies"].append(_text(t))
                except RateLimited:
                    raise
                except Exception as e:
                    log(f"[x] 搜索 {p['tweet_id']} 的自回复失败（可能套餐不支持）: {e}")
            posts.extend(user_posts)
        except RateLimited:
            log("[x] 触发 429 限流，本次停止 X 抓取")
            break
        except Exception as e:
            log(f"[x] 账号 {username} 抓取失败: {e}")
    return posts, newest
