"""End-to-end DRY_RUN tests on a temp copy of the repo (no network, no real gallery)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
DATE = "2026-10-25"


class PipelineTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(REPO, self.root, ignore=shutil.ignore_patterns(
            ".venv", ".git", "__pycache__", "data", "tests", "state", "inbox", "pending_videos.json"))
        # real runtime state/inbox/queue must not leak into the test copy
        for d in ("data", "inbox"):
            (self.root / d).mkdir()
        (self.root / "inbox" / f"{DATE}.json").write_text((FIX / "inbox.json").read_text(encoding="utf-8"))
        (self.root / "inbox" / f"{DATE}-sandmrk.json").write_text((FIX / "raw_sandmrk.json").read_text(encoding="utf-8"))
        self.gallery = Path(self.tmp.name) / "gallery"
        (self.gallery / "works").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_pipeline(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ("BYTECAT_API_KEY", "GALLERY_PUSH_TOKEN")}
        env.update(DRY_RUN="1", PIPELINE_DATE=DATE, GALLERY_DIR=str(self.gallery), **extra)
        r = subprocess.run([sys.executable, "-m", "pipeline.run"], cwd=self.root, env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def state(self):
        return json.loads((self.root / "state" / "seen.json").read_text(encoding="utf-8"))


class DryRunTest(PipelineTestBase):
    def test_full_run(self):
        out = self.run_pipeline()
        seen = self.state()["seen"]
        self.assertEqual(seen["9001"]["status"], "generated")
        self.assertEqual(seen["9002"]["status"], "queued_video")
        self.assertEqual(seen["9003"]["status"], "skipped_no_prompt")
        self.assertEqual(seen["1001"]["status"], "generated")
        self.assertEqual(seen["1002"]["status"], "generated")  # inbox copy wins the dedupe
        self.assertNotIn("1005", seen)  # reply to someone else is not a root post
        self.assertIn("published=3", out)

        d = self.root / "data" / DATE
        api = d / "sandmrk-1001"
        for f in ("post.json", "prompt.txt", "orig-1.jpg", "gen.png", "gen_result.json"):
            self.assertTrue((api / f).exists(), f)
        # self-reply + continuation concatenated verbatim, @mention prefix stripped
        self.assertEqual((api / "prompt.txt").read_text(encoding="utf-8"),
                         "Prompt: a girl on a rooftop at dusk, cinematic, volumetric light --ar 2:3"
                         "\n\nPart 2 (续): wind in hair, 85mm")
        self.assertEqual(json.loads((api / "gen_result.json").read_text())["size"], "1024x1536")
        landscape = json.loads((d / "pixelaigc-9001" / "gen_result.json").read_text())
        self.assertEqual(landscape["size"], "1536x1024")

        vid = d / "pixelaigc-9002"
        self.assertTrue((vid / "ref.png").exists() and (vid / "orig-video.mp4").exists())
        self.assertEqual((vid / "ref_prompt.txt").read_text(encoding="utf-8"),
                         "Master Prompt: a cinematic scene\n人物：红衣女子")
        queue = json.loads((self.root / "pending_videos.json").read_text(encoding="utf-8"))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["status"], "pending")
        self.assertEqual(queue[0]["ref_image"], f"data/{DATE}/pixelaigc-9002/ref.png")
        self.assertTrue(queue[0]["video_prompt"].endswith("Camera slowly pushes in, wind"))

        wid = f"{DATE}-x-pixelaigc-9001"
        m = json.loads((self.gallery / "works" / wid / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((m["width"], m["height"]), (1536, 1024))
        self.assertEqual(m["tags"], ["X 自动", "@pixelaigc"])
        self.assertEqual(m["prompt"], "暗红旗袍，奇幻肖像\n【人物】成年女性\n--ar 2:3")
        self.assertTrue(m["title"].endswith(" · @pixelaigc"))
        for f in ("image.webp", "thumb.webp"):
            self.assertTrue((self.gallery / "works" / wid / f).exists())

        # inbox files are never modified; processed hash is recorded
        self.assertIn(f"{DATE}.json", self.state()["processed_inbox"])

    def test_second_run_is_noop(self):
        self.run_pipeline()
        out = self.run_pipeline()
        self.assertIn("generated=0", out)
        self.assertIn("published=0", out)

    def test_state_has_no_fetch_fields(self):
        self.run_pipeline()
        self.assertEqual(sorted(self.state()), ["processed_inbox", "seen"])

    def test_cap_defers_posts(self):
        cfg = self.root / "config" / "accounts.yml"
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        data["max_images_per_run"] = 1
        (self.root / "inbox" / f"{DATE}-sandmrk.json").unlink()
        cfg.write_text(yaml.safe_dump(data), encoding="utf-8")
        out = self.run_pipeline()
        self.assertIn("generated=1", out)
        seen = self.state()["seen"]
        self.assertEqual(seen["9001"]["status"], "generated")
        self.assertNotIn("9002", seen)  # left for the next run
        self.assertNotIn(f"{DATE}.json", self.state()["processed_inbox"])
        out = self.run_pipeline()  # next run picks up the rest
        self.assertEqual(self.state()["seen"]["9002"]["status"], "queued_video")


class RawInboxTest(PipelineTestBase):
    def test_raw_response(self):
        (self.root / "inbox" / f"{DATE}-raw.json").write_text((FIX / "raw_response.json").read_text(encoding="utf-8"))
        self.run_pipeline()
        seen = self.state()["seen"]
        self.assertEqual(seen["5001"]["status"], "generated")
        self.assertEqual(seen["5003"]["status"], "queued_video")  # note_tweet text, video post
        self.assertNotIn("5002", seen)  # self-reply is a candidate, not a post
        d = self.root / "data" / DATE
        self.assertEqual((d / "rawartist-5001" / "prompt.txt").read_text(encoding="utf-8"),
                         "Prompt: a fox in snow, 85mm, soft light --ar 2:3")
        post = json.loads((d / "rawartist-5001" / "post.json").read_text(encoding="utf-8"))
        self.assertEqual(post["url"], "https://x.com/rawartist/status/5001")
        self.assertEqual(post["media"][0]["url"], "https://pbs.twimg.com/media/fox.jpg")
        q = json.loads((self.root / "pending_videos.json").read_text(encoding="utf-8"))
        e = next(x for x in q if x["slug"] == "rawartist-5003")
        self.assertEqual(e["video_prompt"], "Master Prompt: neon city at night\n人物：黑衣少年\nCamera orbits slowly")

    def test_parse_shapes(self):
        sys.path.insert(0, str(REPO))
        from pipeline import inbox
        raw = json.loads((FIX / "raw_response.json").read_text(encoding="utf-8"))
        for shape in (raw, [raw], {"responses": [raw]}, {"posts": [raw]}):
            self.assertEqual(sorted(p["tweet_id"] for p in inbox.parse(shape)), ["5001", "5003"])


class LLMAnalyzeTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(REPO))
        from pipeline import analyze
        self.analyze = analyze
        self.logs = []
        self._orig = analyze._post
        os.environ["MODELSCOPE_API_KEY"] = "k"
        self.addCleanup(os.environ.pop, "MODELSCOPE_API_KEY", None)
        self.addCleanup(setattr, analyze, "_post", self._orig)

    def mock(self, results, fenced=False):
        content = json.dumps({"results": results}, ensure_ascii=False)
        if fenced:
            content = "here you go\n```json\n" + content + "\n```"
        self.analyze._post = lambda url, headers, payload: (200, {"choices": [{"message": {"content": content}}]})

    def test_valid_rejected_and_not_ai(self):
        posts = [{"tweet_id": "1", "text": "hi", "replies": ["Prompt: a cat, 85mm", "Part 2: wind"]},
                 {"tweet_id": "2", "text": "Prompt: a dog", "replies": []},
                 {"tweet_id": "3", "text": "lunch time", "replies": []}]
        self.mock([
            {"id": "1", "is_ai_work": True, "has_prompt": True, "kind": "image",
             "segments": [{"source": 1, "prompt": "Prompt: a cat, 85mm"}, {"source": 2, "prompt": "Part 2: wind"}]},
            {"id": "2", "is_ai_work": True, "has_prompt": True, "kind": "image",
             "segments": [{"source": 0, "prompt": "Prompt: a happy dog"}]},  # reworded -> reject
            {"id": "3", "is_ai_work": False, "has_prompt": False, "kind": "unknown", "segments": [],
             "reason": "not art"}], fenced=True)
        out = self.analyze.analyze_posts(posts, self.logs.append)
        self.assertEqual(out["1"]["prompt"], "Prompt: a cat, 85mm\n\nPart 2: wind")
        self.assertNotIn("2", out)  # caller falls back to regex
        self.assertTrue(any("不是原文子串" in l for l in self.logs))
        self.assertEqual((out["3"]["prompt"], out["3"]["reason"]), (None, "not art"))

    def test_missing_key_and_http_error(self):
        del os.environ["MODELSCOPE_API_KEY"]
        self.assertEqual(self.analyze.analyze_posts([{"tweet_id": "1", "text": "x"}], self.logs.append), {})
        self.assertIn("MODELSCOPE_API_KEY 未设置：使用正则规则提取提示词", self.logs)
        os.environ["MODELSCOPE_API_KEY"] = "k"
        self.analyze._post = lambda *a: (500, None)
        self.assertEqual(self.analyze.analyze_posts([{"tweet_id": "1", "text": "x"}], self.logs.append), {})

    def test_run_uses_llm_and_records_reason(self):
        from pipeline import run
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(REPO, root, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", "data", "tests"))
            (root / "data").mkdir()
            (root / "inbox" / "a.json").write_text(json.dumps([
                {"tweet_id": "7", "author": "a", "text": "just words", "replies": ["zzz make a fox, soft"]},
                {"tweet_id": "8", "author": "a", "text": "Prompt: x", "media": []}]))
            self.mock([
                {"id": "7", "is_ai_work": True, "has_prompt": True, "segments": [{"source": 1, "prompt": "make a fox, soft"}]},
                {"id": "8", "is_ai_work": False, "has_prompt": False, "reason": "meme"}])
            env = {"DRY_RUN": "1", "PIPELINE_DATE": DATE, "GALLERY_DIR": ""}
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            orig = (run.ROOT, run.STATE_FILE)
            run.ROOT, run.STATE_FILE = root, root / "state" / "seen.json"
            try:
                run.main()
            finally:
                run.ROOT, run.STATE_FILE = orig
                for k, v in old.items():
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
            seen = json.loads((root / "state" / "seen.json").read_text())["seen"]
            self.assertEqual(seen["7"]["status"], "generated")
            self.assertEqual((root / "data" / DATE / "a-7" / "prompt.txt").read_text(), "make a fox, soft")
            self.assertEqual((seen["8"]["status"], seen["8"]["reason"]), ("skipped_no_prompt", "meme"))


class QueueCliTest(PipelineTestBase):
    def cli(self, *args):
        r = subprocess.run([sys.executable, str(self.root / "scripts" / "queue.py"), *args],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_mark_done(self):
        self.run_pipeline()
        self.assertEqual(len(self.cli("list", "--status", "pending")), 1)
        slug = "pixelaigc-9002"
        self.assertEqual(self.cli("show", slug)["slug"], slug)
        e = self.cli("mark", slug, "done", "--video-url", "https://example.com/v.mp4", "--note", "ok")
        self.assertEqual((e["status"], e["video_url"], e["note"]), ("done", "https://example.com/v.mp4", "ok"))
        self.assertEqual(self.cli("list", "--status", "pending"), [])


class PromptTest(unittest.TestCase):
    def test_heuristics(self):
        sys.path.insert(0, str(REPO))
        from pipeline import prompt
        self.assertIsNone(prompt.extract_prompt({"text": "good morning", "replies": []}))
        self.assertEqual(prompt.extract_prompt({"text": "提示词：一只猫 https://t.co/x", "replies": []}), "提示词：一只猫")
        self.assertEqual(prompt.extract_prompt({"text": "a raw b", "prompt_text": " raw ", "replies": []}), " raw ")
        # a bot-supplied prompt_text that is not in any candidate is ignored
        self.assertIsNone(prompt.extract_prompt({"text": "hi", "prompt_text": "invented", "replies": []}))
        long = "，".join(["细节描述"] * 60)
        self.assertEqual(prompt.extract_prompt({"text": "hi", "replies": [long]}), long)


if __name__ == "__main__":
    unittest.main()
