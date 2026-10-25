"""Data layer for pending_videos.json (stdlib only; also used by scripts/queue.py)."""
import json
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ("pending", "done", "rejected")
RAW = "https://raw.githubusercontent.com/iamyours/x-ai-pipeline/main/"


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def save(path, entries):
    Path(path).write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add(entries, slug, ref_image, video_prompt, source_url, author, original_video):
    """Append a pending entry unless the slug is already queued."""
    if any(e["slug"] == slug for e in entries):
        return None
    entry = {"slug": slug, "ref_image": ref_image, "ref_image_url": RAW + ref_image,
             "video_prompt": video_prompt, "source_url": source_url, "author": author,
             "original_video": original_video, "created_at": now(), "status": "pending"}
    entries.append(entry)
    return entry


def mark(entries, slug, status, video_url=None, note=None):
    """Update one entry in place; raises KeyError for an unknown slug."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    for e in entries:
        if e["slug"] == slug:
            e["status"] = status
            if video_url is not None:
                e["video_url"] = video_url
            if note is not None:
                e["note"] = note
            e["updated_at"] = now()
            return e
    raise KeyError(slug)
