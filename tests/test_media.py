"""Original-video size cap: oversize files are deleted and the post keeps going with no original."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline import media


class FakeResponse:
    def __init__(self, chunks):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, _size):
        return iter(self.chunks)


VIDEO_POST = {"tweet_id": "7001", "author": "a", "media": [
    {"type": "video", "variants": [{"content_type": "video/mp4", "bit_rate": 1, "url": "https://video.twimg.com/v.mp4"}]}]}


class MediaCapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.logs = []

    def tearDown(self):
        self.tmp.cleanup()

    def download(self, chunks, cap):
        with mock.patch.object(media, "MAX_BYTES", cap), \
                mock.patch.object(media.requests, "get", return_value=FakeResponse(chunks)):
            return media.download_all(VIDEO_POST, self.folder, False, self.logs.append)

    def test_oversize_video_is_deleted_and_skipped(self):
        got = self.download([b"x" * 6, b"x" * 6], cap=10)
        self.assertIsNone(got["video"])
        self.assertFalse((self.folder / "orig-video.mp4").exists())
        self.assertEqual(len(self.logs), 1)
        self.assertIn("警告", self.logs[0])
        self.assertTrue(media.has_video(VIDEO_POST))

    def test_video_within_cap_is_kept(self):
        got = self.download([b"x" * 6, b"x" * 4], cap=10)
        self.assertEqual(got["video"], self.folder / "orig-video.mp4")
        self.assertEqual((self.folder / "orig-video.mp4").stat().st_size, 10)
        self.assertEqual(self.logs, [])


if __name__ == "__main__":
    unittest.main()
