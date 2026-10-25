"""Download post media into the data folder (placeholders in DRY_RUN)."""
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

MAX_BYTES = 90 * 1024 * 1024  # GitHub rejects files over 100MB and data/ is committed
VIDEO_TYPES = ("video", "animated_gif")


class TooLarge(Exception):
    pass


def has_video(post):
    return any(m.get("type") in VIDEO_TYPES for m in post.get("media", []))


def pick_url(m):
    """Photos: pbs.twimg.com gets ?name=orig. Videos: mp4 variant with the highest bit_rate."""
    if m.get("type") in VIDEO_TYPES and m.get("variants"):
        mp4 = [v for v in m["variants"] if v.get("content_type") == "video/mp4" and v.get("url")]
        if mp4:
            return max(mp4, key=lambda v: v.get("bit_rate") or 0)["url"]
    url = m.get("url")
    if url and urlparse(url).netloc == "pbs.twimg.com" and "name=" not in url:
        url += ("&" if "?" in url else "?") + "name=orig"
    return url


def _placeholder(path, is_video):
    if is_video:
        path.write_bytes(b"DRY RUN placeholder video")
    else:
        Image.new("RGB", (64, 96), (90, 90, 90)).save(path, "JPEG")


def _download(url, path):
    total = 0
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise TooLarge(f"exceeds {MAX_BYTES // (1024 * 1024)}MB cap")
                f.write(chunk)


def download_all(post, folder, dry_run, log=print):
    """Download media; returns {"photos": [paths], "video": path|None}. Failures are logged, not fatal.
    An original over MAX_BYTES is deleted (partial file included) and returned as None; the caller still knows
    it is a video post via has_video()."""
    folder = Path(folder)
    photos, video, n = [], None, 0
    for m in post.get("media", []):
        is_video = m.get("type") in VIDEO_TYPES
        if is_video:
            path = folder / "orig-video.mp4"
            if video:
                continue
        else:
            n += 1
            path = folder / f"orig-{n}.jpg"
        try:
            if dry_run:
                _placeholder(path, is_video)
            else:
                _download(pick_url(m), path)
        except TooLarge as e:
            path.unlink(missing_ok=True)
            log(f"[media] 警告 {post['tweet_id']}: 原文件{e}，已删除，original 置空")
            continue
        except Exception as e:
            log(f"[media] 下载失败 {post['tweet_id']}: {e}")
            continue
        if is_video:
            video = path
        else:
            photos.append(path)
    return {"photos": photos, "video": video}


def aspect_of(post, photos):
    """Width/height of the first original (media metadata, else downloaded photo), or None."""
    for m in post.get("media", []):
        if m.get("width") and m.get("height"):
            return m["width"] / m["height"]
    for p in photos:
        try:
            with Image.open(p) as im:
                return im.width / im.height
        except Exception:
            pass
    return None
