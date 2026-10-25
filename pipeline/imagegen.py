"""gpt-image-2 via bytecat. EXACTLY ONE attempt per call: no retries (timeouts may still be billed)."""
import base64
import io
import os

import requests
from PIL import Image, ImageDraw

URL = "https://codecdn.bytecatcode.org/v1/images/generations"
SIZES = {"portrait": "1024x1536", "landscape": "1536x1024", "square": "1024x1024"}
MODERATION_WORDS = ("moderation", "safety", "content_policy", "content policy")


def choose_size(aspect, default):
    if not aspect:
        return default
    if aspect < 0.9:
        return SIZES["portrait"]
    if aspect > 1.1:
        return SIZES["landscape"]
    return SIZES["square"]


def placeholder_png(size):
    w, h = map(int, size.split("x"))
    im = Image.new("RGB", (w, h), (60, 70, 110))
    ImageDraw.Draw(im).text((w // 2 - 30, h // 2), "DRY RUN", fill=(255, 255, 255))
    return im


def generate(prompt, size, out_path, dry_run=False):
    """Returns {status: ok|skipped_moderation|failed, error, usage, size}. Writes out_path (PNG) on ok."""
    result = {"status": "failed", "error": None, "usage": None, "size": size}
    if dry_run:
        placeholder_png(size).save(out_path, "PNG")
        result["status"] = "ok"
        return result
    try:
        r = requests.post(URL, timeout=300,
                          headers={"Authorization": f"Bearer {os.environ['BYTECAT_API_KEY']}"},
                          json={"model": "gpt-image-2", "prompt": prompt, "size": size, "n": 1})
        if r.status_code == 400 and any(w in r.text.lower() for w in MODERATION_WORDS):
            result.update(status="skipped_moderation", error=r.text[:300])
            return result
        if r.status_code >= 400:
            result["error"] = f"HTTP {r.status_code}: {r.text[:300]}"
            return result
        body = r.json()
        result["usage"] = body.get("usage")
        item = body["data"][0]
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
        else:  # a fetch of the already-generated image, not a new generation
            raw = requests.get(item["url"], timeout=120).content
        Image.open(io.BytesIO(raw)).save(out_path, "PNG")
        result["status"] = "ok"
    except Exception as e:  # timeouts included; never retried
        result["error"] = f"{type(e).__name__}: {e}"[:300]
    return result
