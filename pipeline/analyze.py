"""LLM prompt extraction via ModelScope DeepSeek (OpenAI-compatible). Output is validated to be verbatim text."""
import json
import os
import re

import requests

DEFAULT_BASE = "https://api-inference.modelscope.cn/v1"
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
BATCH = 8
TIMEOUT = 120

SYSTEM = """You analyze social-media posts by AI artists. For each post you get numbered candidate texts:
0 = the root post body, 1.. = the author's own self-replies.
Decide whether the post is an AI image/video work that includes a usable generation prompt, and extract that prompt.

CRITICAL RULES
- Copy prompt text VERBATIM, character for character, from the candidate. Do NOT translate, reword, summarize,
  fix typos, change punctuation, or reformat anything. Each "prompt" must be an exact substring of its candidate.
- A multi-part prompt (e.g. Part 1 / Part 2, or split across self-replies) may be returned as several segments, in order.
- Exclude hashtags, @mentions, t.co links and chit-chat that are not part of the prompt.
- If there is no prompt, set has_prompt=false and return no segments.

Reply with JSON only:
{"results": [{"id": "<post id as given>", "is_ai_work": true|false, "has_prompt": true|false,
  "kind": "image"|"video"|"unknown",
  "segments": [{"source": <candidate index>, "prompt": "<exact substring>"}], "reason": "short explanation"}]}"""


class LLMError(Exception):
    pass


def _post(url, headers, payload):
    """The only HTTP call; tests monkeypatch it. Returns (status_code, parsed_json_or_None)."""
    r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def _chat(messages):
    """Return the assistant message text. One retry, only on network error / 5xx (or if json mode is unsupported)."""
    url = os.environ.get("MODELSCOPE_BASE_URL", DEFAULT_BASE).rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {os.environ['MODELSCOPE_API_KEY']}"}
    payload = {"model": os.environ.get("MODELSCOPE_MODEL") or DEFAULT_MODEL, "messages": messages,
               "temperature": 0, "response_format": {"type": "json_object"}}
    for attempt in (1, 2):
        try:
            status, body = _post(url, headers, payload)
        except requests.RequestException as e:
            if attempt == 2:
                raise LLMError(f"网络错误: {type(e).__name__}")
            continue
        if status == 400 and "response_format" in payload:
            payload.pop("response_format")  # model does not support json mode; ask in plain text
            continue
        if status >= 500 and attempt == 1:
            continue
        if status >= 400 or not body:
            raise LLMError(f"HTTP {status}")
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise LLMError("响应格式异常")
    raise LLMError("重试后仍失败")


def parse_json(text):
    """Parse JSON from plain text or a ```json fenced block; None when impossible."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    for cand in ([m.group(1)] if m else []) + [text]:
        try:
            return json.loads(cand)
        except ValueError:
            continue
    return None


def validate(result, texts):
    """Return the joined prompt if every segment is a verbatim substring of its candidate, else None."""
    segs = result.get("segments")
    if not isinstance(segs, list) or not segs:
        return None
    parts = []
    for s in segs:
        src, p = s.get("source") if isinstance(s, dict) else None, s.get("prompt") if isinstance(s, dict) else None
        if not isinstance(src, int) or isinstance(src, bool) or not 0 <= src < len(texts):
            return None
        if not isinstance(p, str) or not p.strip() or p.strip() not in texts[src]:
            return None
        parts.append(p.strip())
    return "\n\n".join(parts)


def analyze_posts(posts, log=print):
    """Return {tweet_id: {"prompt": str|None, "reason": str, "kind": str}}.

    prompt None = the LLM judged there is no prompt (skip the post). Posts missing from the result
    (no key, call failed, invalid output) are absent so the caller falls back to the regex heuristic.
    """
    from .prompt import raw_candidates
    if not posts:
        return {}
    if not os.environ.get("MODELSCOPE_API_KEY"):
        log("MODELSCOPE_API_KEY 未设置：使用正则规则提取提示词")
        return {}
    out = {}
    for i in range(0, len(posts), BATCH):
        batch = posts[i:i + BATCH]
        cands = {p["tweet_id"]: raw_candidates(p) for p in batch}
        user = json.dumps([{"id": tid, "candidates": [{"index": n, "text": t} for n, t in enumerate(ts)]}
                           for tid, ts in cands.items()], ensure_ascii=False)
        try:
            data = parse_json(_chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]))
        except LLMError as e:
            log(f"[llm] 调用失败，改用正则规则: {e}")
            continue
        results = data.get("results") if isinstance(data, dict) else data
        if isinstance(data, dict) and "is_ai_work" in data and len(batch) == 1:
            results = [{**data, "id": batch[0]["tweet_id"]}]
        for r in results if isinstance(results, list) else []:
            if not isinstance(r, dict) or str(r.get("id")) not in cands:
                continue  # tolerate unknown / missing posts
            tid, reason, kind = str(r["id"]), str(r.get("reason") or ""), r.get("kind") or "unknown"
            if r.get("is_ai_work") is False or r.get("has_prompt") is False:
                out[tid] = {"prompt": None, "reason": reason or "LLM: 非 AI 作品或无提示词", "kind": kind}
                continue
            prompt = validate(r, cands[tid])
            if prompt is None:
                log(f"LLM 提取结果不是原文子串，已拒绝 (tweet {tid})")
                continue
            out[tid] = {"prompt": prompt, "reason": reason, "kind": kind}
    return out
