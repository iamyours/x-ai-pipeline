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
        shutil.copytree(REPO, self.root, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", "data", "tests"))
        (self.root / "data").mkdir()
        (self.root / "inbox" / f"{DATE}.json").write_text((FIX / "inbox.json").read_text(encoding="utf-8"))
        self.gallery = Path(self.tmp.name) / "gallery"
        (self.gallery / "works").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_pipeline(self, with_x=True, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ("X_BEARER_TOKEN", "BYTECAT_API_KEY", "GALLERY_PUSH_TOKEN")}
        env.update(DRY_RUN="1", PIPELINE_DATE=DATE, GALLERY_DIR=str(self.gallery), **extra)
        if with_x:
            env.update(X_BEARER_TOKEN="fake", FAKE_X_FIXTURE=str(FIX / "x_fixture.json"))
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
        self.assertEqual(self.state()["last_since_id"]["sandmrk"], "1005")
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

    def test_inbox_only_without_token(self):
        out = self.run_pipeline(with_x=False)
        self.assertIn("X_BEARER_TOKEN 未设置：跳过 X API 抓取，只处理 inbox/", out)
        self.assertNotIn("1001", self.state()["seen"])

    def test_cap_defers_posts(self):
        cfg = self.root / "config" / "accounts.yml"
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        data["max_images_per_run"] = 1
        cfg.write_text(yaml.safe_dump(data), encoding="utf-8")
        out = self.run_pipeline(with_x=False)
        self.assertIn("generated=1", out)
        seen = self.state()["seen"]
        self.assertEqual(seen["9001"]["status"], "generated")
        self.assertNotIn("9002", seen)  # left for the next run
        self.assertNotIn(f"{DATE}.json", self.state()["processed_inbox"])
        out = self.run_pipeline(with_x=False)  # next run picks up the rest
        self.assertEqual(self.state()["seen"]["9002"]["status"], "queued_video")


class QueueCliTest(PipelineTestBase):
    def cli(self, *args):
        r = subprocess.run([sys.executable, str(self.root / "scripts" / "queue.py"), *args],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_mark_done(self):
        self.run_pipeline(with_x=False)
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
        self.assertEqual(prompt.extract_prompt({"text": "x", "prompt_text": " raw ", "replies": []}), " raw ")
        long = "，".join(["细节描述"] * 60)
        self.assertEqual(prompt.extract_prompt({"text": "hi", "replies": [long]}), long)


if __name__ == "__main__":
    unittest.main()
