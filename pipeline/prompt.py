"""Prompt extraction: pick the prompt text out of a post (and its self-replies). Never rewrites text."""
import re

MARKERS = ["prompt", "提示词", "咒语", "负面提示词", "negative", "--ar"]
JSON_KEYS = re.compile(r'"(subject|scene|style)"\s*:', re.I)
CONTINUATION = re.compile(r"(part\s*\d+|（续）|\(续\)|续[:：]|分镜|shot\s*\d+|\b\d+\s*/\s*\d+\b)", re.I)
LEADING_MENTIONS = re.compile(r"^(?:@\w+\s+)+")
TRAILING_TCO = re.compile(r"(?:\s*https://t\.co/\w+)+\s*$")
SEPARATORS = re.compile(r"[,，、；;]")
VIDEO_SECTION = re.compile(
    r"人物|角色|Character|Subject|场景|Scene|Master Prompt|外貌|服装", re.I)
THRESHOLD = 3


def clean(text):
    """Strip only a leading @mention prefix and trailing t.co links."""
    text = LEADING_MENTIONS.sub("", text or "")
    return TRAILING_TCO.sub("", text).strip()


def score(text):
    low = text.lower()
    s = 3 * sum(1 for m in MARKERS if m in low)
    if "{" in text and JSON_KEYS.search(text):
        s += 4
    if len(text) >= 200:
        s += 1
        if len(SEPARATORS.findall(text)) >= 8:
            s += 3
    return s


def raw_candidates(post):
    """Unmodified candidate texts: index 0 = root post body, 1.. = the author's self-replies."""
    return [post.get("text", "") or ""] + [r or "" for r in post.get("replies") or []]


def valid_prompt_text(post):
    """A bot-supplied prompt_text is trusted only if it is a verbatim substring of some candidate text."""
    pt = post.get("prompt_text") or ""
    if not pt.strip():
        return None
    texts = raw_candidates(post)
    return pt if any(pt in t or pt.strip() in clean(t) for t in texts) else None


def extract_prompt(post):
    """Return the raw prompt for a normalized post, or None when nothing looks like a prompt."""
    supplied = valid_prompt_text(post)
    if supplied:
        return supplied
    candidates = [clean(t) for t in [post.get("text", "")] + list(post.get("replies") or [])]
    candidates = [c for c in candidates if c]
    scores = [score(c) for c in candidates]
    if not scores or max(scores) < THRESHOLD:
        return None
    best = scores.index(max(scores))  # earliest wins ties
    start = best
    if CONTINUATION.search(candidates[best]):
        # best is itself a later part: start from the first prompt-like/continuation text
        for i, c in enumerate(candidates):
            if scores[i] >= THRESHOLD or CONTINUATION.search(c):
                start = i
                break
    parts = [candidates[start]] + [c for c in candidates[start + 1:] if CONTINUATION.search(c)]
    return "\n\n".join(parts)


def ref_prompt(prompt):
    """Prompt for the video reference image: character/scene lines verbatim, else the whole prompt."""
    lines = [l for l in prompt.splitlines() if VIDEO_SECTION.search(l)]
    return "\n".join(lines) if lines else prompt
