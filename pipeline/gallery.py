"""Publish generated images into the gallery repo (works/<id>/manifest.json + image.webp + thumb.webp)."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def work_id(date, author, tweet_id):
    return f"{date}-x-{author}-{tweet_id}"


def title_for(prompt, author):
    first = next((l.strip() for l in prompt.splitlines() if l.strip()), "")
    return f"{first[:18]} · @{author}"


ORIG_MAX_EDGE = 1600
_ORIG_RE = re.compile(r"^orig-(\d+)\.jpe?g$", re.IGNORECASE)
_WORK_ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-x-(.+)-(\d+)$")


def _find_originals(src_dir):
    """orig-N.jpg files in src_dir, sorted numerically by N (orig-video.mp4 etc. ignored)."""
    found = []
    for f in Path(src_dir).iterdir():
        m = _ORIG_RE.match(f.name)
        if m and f.is_file():
            found.append((int(m.group(1)), f))
    return [f for _, f in sorted(found, key=lambda t: t[0])]


def save_originals(src_dir, out_dir):
    """Convert orig-N.jpg in src_dir to orig-N.webp in out_dir; returns the webp names."""
    names = []
    for f in _find_originals(src_dir):
        n = _ORIG_RE.match(f.name).group(1)
        with Image.open(f) as im:
            im = im.convert("RGB")
            longest = max(im.size)
            if longest > ORIG_MAX_EDGE:
                s = ORIG_MAX_EDGE / longest
                im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)
            name = f"orig-{int(n)}.webp"
            im.save(Path(out_dir) / name, "WEBP", quality=80)
        names.append(name)
    return names


def write_work(gallery_dir, date, post, prompt, png_path, tag):
    """Create the work folder; returns its id."""
    wid = work_id(date, post["author"], post["tweet_id"])
    out = Path(gallery_dir) / "works" / wid
    out.mkdir(parents=True, exist_ok=True)
    with Image.open(png_path) as im:
        im = im.convert("RGB")
        scale = min(1.0, 2048 / max(im.size))
        full = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS) if scale < 1 else im
        full.save(out / "image.webp", "WEBP", quality=82)
        tw = 480
        thumb = im.resize((tw, round(im.height * tw / im.width)), Image.LANCZOS)
        thumb.save(out / "thumb.webp", "WEBP", quality=75)
        width, height = full.size
    manifest = {"id": wid, "title": title_for(prompt, post["author"]), "type": "image",
                "file": "image.webp", "thumb": "thumb.webp", "width": width, "height": height,
                "prompt": prompt, "model": "gpt-image-2", "tags": [tag, f"@{post['author']}"],
                "date": date, "source": post["url"], "author": f"@{post['author']}"}
    originals = save_originals(Path(png_path).parent, out)
    if originals:
        manifest["originals"] = originals
        manifest["originals_credit"] = {"author": f"@{post['author']}", "url": post["url"]}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return wid


def backfill_originals(gallery_dir, data_date_dir, log=print):
    """Add originals to existing works from local data (no network). Returns the number of works updated.

    Only works whose id is <date>-x-<author>-<tweet_id> and whose data folder
    <data_date_dir>/<author>-<tweet_id>/ has post.json and orig-*.jpg are touched;
    image.webp/thumb.webp are never rewritten. Idempotent.
    """
    works_dir = Path(gallery_dir) / "works"
    if not works_dir.is_dir():
        return 0
    updated = 0
    for wdir in sorted(works_dir.iterdir()):
        m = _WORK_ID_RE.match(wdir.name)
        mf = wdir / "manifest.json"
        if not (m and wdir.is_dir() and mf.is_file()):
            continue
        _, author, tweet_id = m.groups()
        src = Path(data_date_dir) / f"{author}-{tweet_id}"
        post_file = src / "post.json"
        if not (src.is_dir() and post_file.is_file() and _find_originals(src)):
            continue
        post = json.loads(post_file.read_text(encoding="utf-8"))
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        names = save_originals(src, wdir)
        credit = {"author": f"@{post.get('author') or author}",
                  "url": post.get("url") or f"https://x.com/{author}/status/{tweet_id}"}
        if manifest.get("originals") == names and manifest.get("originals_credit") == credit:
            continue
        manifest["originals"] = names
        manifest["originals_credit"] = credit
        mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"[backfill] {wdir.name}: {len(names)} originals")
        updated += 1
    return updated


def _git(cwd, *args, token=None):
    """Run git; mask the token in any raised error."""
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        err = (r.stderr or r.stdout)
        if token:
            err = err.replace(token, "***")
        raise RuntimeError(f"git {args[0]} failed: {err.strip()[:300]}")
    return r.stdout


def publish(works, date, config, dry_run, log=print):
    """works: [(post, prompt, png_path)]. Returns the number of works published."""
    if not works:
        return 0
    token = os.environ.get("GALLERY_PUSH_TOKEN")
    local = os.environ.get("GALLERY_DIR")
    if dry_run and not local:
        log("[gallery] DRY_RUN 且未设置 GALLERY_DIR：跳过发布")
        return 0
    if not local and not token:
        log("[gallery] GALLERY_PUSH_TOKEN 未设置：跳过发布（图片保留在 data/）")
        return 0
    tmp = None
    try:
        if local:
            gdir = local
        else:
            tmp = tempfile.TemporaryDirectory()
            gdir = tmp.name
            url = f"https://x-access-token:{token}@github.com/{config['gallery_repo']}.git"
            _git(tmp.name, "clone", "--depth", "1", url, ".", token=token)
        ids = [write_work(gdir, date, p, pr, png, config["gallery_tag"]) for p, pr, png in works]
        if dry_run:
            log(f"[gallery] DRY_RUN：已写入 {len(ids)} 件到 {gdir}，不提交")
            return len(ids)
        _git(gdir, "add", "works", token=token)
        _git(gdir, "-c", "user.name=x-ai-pipeline", "-c", "user.email=bot@users.noreply.github.com",
             "commit", "-m", f"auto: 新增 {len(ids)} 件 X 作品 ({date})", token=token)
        _git(gdir, "push", "origin", "HEAD:main", token=token)
        return len(ids)
    except Exception as e:
        log(f"[gallery] 发布失败: {str(e).replace(token, '***') if token else e}")
        return 0
    finally:
        if tmp:
            tmp.cleanup()
