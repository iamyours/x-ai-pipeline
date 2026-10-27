"""Build the GitHub Pages site for Muse reverse-video works.

Reads resources/*/index.json and works/<id>/*, writes index.html (repo root)
and docs/index.html (same content, with ../ relative paths).
Run: python3 scripts/build_site.py
"""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def clean_text(t):
    return re.sub(r"https://t\.co/\S+", "", t or "").strip()


def load_posts():
    posts = []
    for idx in sorted((ROOT / "resources").glob("*/index.json")):
        data = json.loads(idx.read_text(encoding="utf-8"))
        for p in data.get("posts", []):
            p["_author"] = data.get("author", idx.parent.name)
            posts.append(p)
    posts.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return posts


def card_html(p, prefix):
    pid = p["id"]
    work = ROOT / "works" / pid
    img_prompt = (work / "image_prompt.txt").read_text(encoding="utf-8").strip() if (work / "image_prompt.txt").exists() else ""
    vid_prompt = (work / "video_prompt.txt").read_text(encoding="utf-8").strip() if (work / "video_prompt.txt").exists() else ""
    has_img = (work / "image.png").exists()
    has_vid = (work / "muse.mp4").exists()
    status = p.get("status", "pending")
    reason = p.get("reason", "")
    title = clean_text(p.get("text", "")) or pid
    orig = f"{prefix}resources/{p['_author']}/{pid}/video.mp4"
    parts = []
    parts.append(f'<article class="card" data-status="{html.escape(status)}">')
    parts.append(f'<h2>{html.escape(title)}</h2>')
    parts.append(f'<p class="meta">{html.escape(p.get("created_at", ""))} · @{html.escape(p["_author"])} · <span class="badge {html.escape(status)}">{html.escape(status)}</span> · <a href="{html.escape(p.get("url", ""))}">original post</a></p>')
    if reason:
        parts.append(f'<p class="reason">Reason: {html.escape(reason)}</p>')
    parts.append(f'<p class="orig-text">{html.escape(p.get("text", ""))}</p>')
    parts.append('<div class="media-row">')
    parts.append(f'<div><h3>Original video</h3><video controls preload="metadata" src="{html.escape(orig)}"></video></div>')
    if has_img:
        parts.append(f'<div><h3>Reverse image</h3><img src="{prefix}works/{pid}/image.png" alt="reverse image"></div>')
    else:
        parts.append('<div><h3>Reverse image</h3><p class="missing">Not generated yet.</p></div>')
    parts.append('</div>')
    if img_prompt or vid_prompt:
        parts.append('<div class="prompts">')
        if img_prompt:
            parts.append(f'<h3>Image prompt</h3><pre>{html.escape(img_prompt)}</pre><button onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent)">Copy image prompt</button>')
        if vid_prompt:
            parts.append(f'<h3>Video prompt</h3><pre>{html.escape(vid_prompt)}</pre><button onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent)">Copy video prompt</button>')
        parts.append('</div>')
    if has_vid:
        parts.append(f'<div><h3>Reverse video</h3><video controls preload="metadata" src="{prefix}works/{pid}/muse.mp4"></video></div>')
    else:
        parts.append('<div><h3>Reverse video</h3><p class="missing">Not generated yet.</p></div>')
    parts.append('</article>')
    return "\n".join(parts)


def build(prefix):
    posts = load_posts()
    from collections import Counter
    counts = Counter(p.get("status", "pending") for p in posts)
    cards = "\n".join(card_html(p, prefix) for p in posts)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Muse reverse videos — tari323</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:24px;line-height:1.5}}
.card{{border:1px solid #ddd;border-radius:12px;padding:16px;margin:20px 0}}
.media-row{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
video,img{{width:100%;height:auto;border-radius:8px;background:#111}}
pre{{white-space:pre-wrap;background:#f6f6f6;padding:12px;border-radius:8px}}
.badge{{padding:2px 8px;border-radius:999px;background:#eee}}
.badge.done{{background:#d4edda}} .badge.failed{{background:#f8d7da}} .badge.refused{{background:#fff3cd}} .badge.pending{{background:#e2e3e5}}
button{{margin:4px 0 12px}} .missing{{color:#666}} .meta,.reason{{color:#555}}
@media(max-width:700px){{.media-row{{grid-template-columns:1fr}}}}
</style></head><body>
<h1>Muse reverse videos — tari323</h1>
<p>{len(posts)} posts · done {counts.get('done',0)} · failed {counts.get('failed',0)} · refused {counts.get('refused',0)} · pending {counts.get('pending',0)}</p>
<p><button onclick="filterCards('all')">All</button> <button onclick="filterCards('done')">Done</button> <button onclick="filterCards('failed')">Failed</button> <button onclick="filterCards('refused')">Refused</button> <button onclick="filterCards('pending')">Pending</button></p>
<script>function filterCards(s){{document.querySelectorAll('.card').forEach(c=>{{c.style.display=(s==='all'||c.dataset.status===s)?'':'none'}})}}</script>
{cards}
</body></html>
"""


def main():
    (ROOT / "index.html").write_text(build(""), encoding="utf-8")
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text(build("../"), encoding="utf-8")
    print(f"wrote index.html and docs/index.html")


if __name__ == "__main__":
    main()
