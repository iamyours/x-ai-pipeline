"""Gallery publishing: original X images alongside the generated work."""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from pipeline import gallery

POST = {"author": "alice", "tweet_id": "123", "url": "https://x.com/alice/status/123"}


def make_jpg(path, size, color=(200, 30, 30)):
    Image.new("RGB", size, color).save(path, "JPEG")


class GalleryOriginalsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.gallery = self.root / "gallery"
        self.src = self.root / "data" / "alice-123"
        self.src.mkdir(parents=True)
        self.png = self.src / "gen.png"
        Image.new("RGB", (64, 48), (0, 0, 255)).save(self.png)

    def write(self):
        wid = gallery.write_work(self.gallery, "2026-10-25", POST, "prompt text", self.png, "tag")
        out = self.gallery / "works" / wid
        return wid, out, json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    def test_originals_converted_and_resized(self):
        make_jpg(self.src / "orig-1.jpg", (3200, 1600))
        make_jpg(self.src / "orig-2.jpg", (800, 600))
        (self.src / "orig-video.mp4").write_bytes(b"x")
        _, out, m = self.write()
        self.assertEqual(m["originals"], ["orig-1.webp", "orig-2.webp"])
        self.assertEqual(m["originals_credit"], {"author": "@alice", "url": POST["url"]})
        with Image.open(out / "orig-1.webp") as im:
            self.assertEqual(im.format, "WEBP")
            self.assertEqual(im.size, (1600, 800))
        with Image.open(out / "orig-2.webp") as im:
            self.assertEqual(im.size, (800, 600))
        self.assertFalse((out / "orig-video.webp").exists())

    def test_numeric_sort(self):
        for i in (10, 2, 1):
            make_jpg(self.src / f"orig-{i}.jpg", (50, 50))
        _, _, m = self.write()
        self.assertEqual(m["originals"], ["orig-1.webp", "orig-2.webp", "orig-10.webp"])

    def test_no_originals_no_key(self):
        _, out, m = self.write()
        self.assertNotIn("originals", m)
        self.assertNotIn("originals_credit", m)
        self.assertEqual(m["file"], "image.webp")
        self.assertEqual([p.name for p in out.glob("orig-*")], [])


class BackfillTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.gallery = root / "gallery"
        self.date_dir = root / "data" / "2026-10-25"
        src = self.date_dir / "alice-123"
        src.mkdir(parents=True)
        make_jpg(src / "orig-1.jpg", (2400, 1200))
        make_jpg(src / "orig-2.jpg", (100, 100))
        (src / "post.json").write_text(json.dumps(POST), encoding="utf-8")
        # existing work (no originals) + unrelated ones
        self.wdir = self.gallery / "works" / "2026-10-25-x-alice-123"
        self.wdir.mkdir(parents=True)
        (self.wdir / "image.webp").write_bytes(b"IMG")
        (self.wdir / "thumb.webp").write_bytes(b"THUMB")
        self.manifest = {"id": self.wdir.name, "title": "t", "file": "image.webp", "thumb": "thumb.webp",
                         "date": "2026-10-25", "source": POST["url"], "author": "@alice"}
        (self.wdir / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        other = self.gallery / "works" / "2026-10-25-x-bob-999"  # no data folder
        other.mkdir()
        (other / "manifest.json").write_text('{"id": "x"}', encoding="utf-8")
        manual = self.gallery / "works" / "manual-work"
        manual.mkdir()
        (manual / "manifest.json").write_text('{"id": "manual"}', encoding="utf-8")

    def test_backfill_updates_and_is_idempotent(self):
        self.assertEqual(gallery.backfill_originals(self.gallery, self.date_dir, log=lambda *_: None), 1)
        text = (self.wdir / "manifest.json").read_text(encoding="utf-8")
        m = json.loads(text)
        self.assertEqual(list(m), list(self.manifest) + ["originals", "originals_credit"])
        for k, v in self.manifest.items():
            self.assertEqual(m[k], v)
        self.assertEqual(m["originals"], ["orig-1.webp", "orig-2.webp"])
        self.assertEqual(m["originals_credit"], {"author": "@alice", "url": POST["url"]})
        with Image.open(self.wdir / "orig-1.webp") as im:
            self.assertEqual(im.size, (1600, 800))
        self.assertEqual((self.wdir / "image.webp").read_bytes(), b"IMG")
        self.assertEqual((self.wdir / "thumb.webp").read_bytes(), b"THUMB")
        # second run: no change
        self.assertEqual(gallery.backfill_originals(self.gallery, self.date_dir, log=lambda *_: None), 0)
        self.assertEqual((self.wdir / "manifest.json").read_text(encoding="utf-8"), text)
        # untouched works
        self.assertEqual((self.gallery / "works" / "manual-work" / "manifest.json").read_text(), '{"id": "manual"}')
        self.assertFalse(list((self.gallery / "works" / "2026-10-25-x-bob-999").glob("orig-*")))


if __name__ == "__main__":
    unittest.main()
