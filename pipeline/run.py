"""Daily pipeline entry point: python -m pipeline.run"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import analyze, gallery, imagegen, inbox, media, prompt, queue

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "seen.json"


def log(msg):
    print(msg, flush=True)


def load_state():
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    for k in ("seen", "processed_inbox"):
        state.setdefault(k, {})
    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_seen(state, tweet_id, status, reason=None):
    state["seen"][tweet_id] = {"status": status, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if reason:
        state["seen"][tweet_id]["reason"] = reason


def slug_for(post):
    return re.sub(r"[^a-z0-9_-]", "", f"{post['author']}-{post['tweet_id']}".lower())


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    dry_run = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    config = yaml.safe_load((ROOT / "config" / "accounts.yml").read_text(encoding="utf-8"))
    state = load_state()
    date = os.environ.get("PIPELINE_DATE") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats = dict(inbox=0, skipped_no_prompt=0, generated=0, moderated=0, failed=0,
                 queued_videos=0, published=0, deferred=0)

    # 1. collect posts from inbox/ only, dedupe by tweet_id, skip already-seen ids
    posts, order = {}, []
    inbox_files = inbox.load_new(ROOT / "inbox", state["processed_inbox"])
    for _name, _sha, ps in inbox_files:
        for p in ps:
            stats["inbox"] += 1
            if p["tweet_id"] not in posts:
                posts[p["tweet_id"]] = p
                order.append(p["tweet_id"])
    todo = [posts[i] for i in order if i not in state["seen"]]

    # 2-6. per post: prompt, media, generation (capped), video queue
    cap = config.get("max_images_per_run", 5)
    calls = 0
    have_key = bool(os.environ.get("BYTECAT_API_KEY")) or dry_run
    if not have_key:
        log("BYTECAT_API_KEY 未设置：跳过生图，帖子留待下次处理")
    # bot-supplied prompt_text that checks out is used as-is; everything else goes to the LLM (or regex fallback)
    verdicts = analyze.analyze_posts([p for p in todo if not prompt.valid_prompt_text(p)], log)
    queue_file = ROOT / "pending_videos.json"
    entries = queue.load(queue_file)
    to_publish, deferred_ids = [], set()
    for post in todo:
        tid = post["tweet_id"]
        verdict = verdicts.get(tid)
        text = verdict["prompt"] if verdict else prompt.extract_prompt(post)
        if text is None:
            mark_seen(state, tid, "skipped_no_prompt", verdict and verdict["reason"])
            stats["skipped_no_prompt"] += 1
            continue
        if not have_key or calls >= cap:
            deferred_ids.add(tid)
            stats["deferred"] += 1
            continue
        slug = slug_for(post)
        rel = Path("data") / date / slug
        folder = ROOT / rel
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "post.json", post)
        (folder / "prompt.txt").write_text(text, encoding="utf-8")
        got = media.download_all(post, folder, dry_run, log)
        is_video = media.has_video(post)  # the video job is queued even if the original was not kept
        size = imagegen.choose_size(media.aspect_of(post, got["photos"]), config.get("image_size", "1024x1536"))
        gen_prompt = prompt.ref_prompt(text) if is_video else text
        out_name = "ref.png" if is_video else "gen.png"
        if is_video:
            (folder / "ref_prompt.txt").write_text(gen_prompt, encoding="utf-8")
        calls += 1  # exactly one attempt, never retried
        res = imagegen.generate(gen_prompt, size, folder / out_name, dry_run)
        write_json(folder / "gen_result.json", {**res, "kind": "ref" if is_video else "image"})
        if res["status"] == "ok":
            stats["generated"] += 1
            mark_seen(state, tid, "queued_video" if is_video else "generated")
            if is_video:
                orig = (rel / "orig-video.mp4").as_posix() if got["video"] else None
                if queue.add(entries, slug, (rel / "ref.png").as_posix(), text, post["url"],
                             post["author"], orig):
                    stats["queued_videos"] += 1
            else:
                to_publish.append((post, text, folder / "gen.png"))
        elif res["status"] == "skipped_moderation":
            stats["moderated"] += 1
            mark_seen(state, tid, "skipped_moderation")
        else:
            stats["failed"] += 1
            mark_seen(state, tid, "failed")
            log(f"[gen] {tid} 失败: {res['error']}")
    queue.save(queue_file, entries)

    # 7. publish to gallery
    stats["published"] = gallery.publish(to_publish, date, config, dry_run, log)

    # mark inbox files processed only when nothing in them was deferred, so no post is lost
    if not deferred_ids:
        for name, sha, ps in inbox_files:
            state["processed_inbox"][name] = sha
    else:
        for name, sha, ps in inbox_files:
            if not any(p["tweet_id"] in deferred_ids for p in ps):
                state["processed_inbox"][name] = sha
    save_state(state)

    # 8. summary
    summary = "run summary: " + ", ".join(f"{k}={v}" for k, v in stats.items())
    log(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## X AI pipeline\n\n" + "\n".join(f"- {k}: {v}" for k, v in stats.items()) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
