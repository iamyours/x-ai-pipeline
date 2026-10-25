"""Publish generated images into the gallery repo (works/<id>/manifest.json + image.webp + thumb.webp)."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def work_id(date, author, tweet_id):
    return f"{date}-x-{author}-{tweet_id}"


def title_for(prompt, author):
    first = next((l.strip() for l in prompt.splitlines() if l.strip()), "")
    return f"{first[:18]} · @{author}"


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
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return wid


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
