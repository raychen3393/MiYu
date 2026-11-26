"""2.5 长视频:20GB 上限、边下边看的本机小服务器、MP4 索引位置判断。不需要 Qt。"""
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from miyu import core, stream    # noqa: E402

GB = 1024 * 1024 * 1024


def box(kind: bytes, body: bytes) -> bytes:
    return (8 + len(body)).to_bytes(4, "big") + kind + body


def mp4(moov_first: bool, mdat: int = 4096) -> bytes:
    ftyp = box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    moov = box(b"moov", box(b"mvhd", bytes(100)))
    data = box(b"mdat", bytes(range(256)) * (mdat // 256))
    return ftyp + (moov + data if moov_first else data + moov)


class LimitTests(unittest.TestCase):
    def test_video_20gb_others_4gb(self):
        self.assertEqual(core.max_size_for("电影.MKV"), core.MAX_VIDEO)
        self.assertEqual(core.max_size_for("录屏.mp4"), 20 * GB)
        self.assertEqual(core.max_size_for("资料.zip"), 4 * GB)
        self.assertEqual(core.max_size_for("打包.mp4", folder=True), 4 * GB)
        fid = "a" * 32
        self.assertIsNotNone(core.clean_file({"fid": fid, "name": "一小时录屏.mp4", "size": 12 * GB}))
        self.assertIsNone(core.clean_file({"fid": fid, "name": "一小时录屏.mp4", "size": 21 * GB}))
        self.assertIsNone(core.clean_file({"fid": fid, "name": "备份.zip", "size": 5 * GB}))
        self.assertIsNone(core.clean_file({"fid": fid, "name": "x.mp4", "size": 5 * GB, "dir": True}))

    def test_replace_retry(self):
        d = tempfile.mkdtemp()
        a, b = os.path.join(d, "a.part"), os.path.join(d, "a.mp4")
        with open(a, "wb") as f:
            f.write(b"x")
        core._replace_retry(a, b)
        self.assertTrue(os.path.exists(b) and not os.path.exists(a))


class Mp4Tests(unittest.TestCase):
    def write(self, data: bytes) -> str:
        fd, p = tempfile.mkstemp(suffix=".mp4.part")
        os.write(fd, data)
        os.close(fd)
        return p

    def test_index_position(self):
        self.assertTrue(stream.mp4_streamable(self.write(mp4(True))))
        self.assertFalse(stream.mp4_streamable(self.write(mp4(False))))
        self.assertFalse(stream.mp4_streamable(self.write(b"RIFF....AVI LIST" * 4)))
        whole = mp4(False)
        p = self.write(whole[:30])                            # 只下载了开头:还判断不了
        self.assertIsNone(stream.mp4_streamable(p))
        p = self.write(mp4(True))
        self.assertIsNone(stream.mp4_streamable(p, have=20))  # 按"已下载多少"判断,不看文件实际多大
        self.assertTrue(stream.can_stream("a.MOV"))
        self.assertFalse(stream.can_stream("a.mkv"))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.srv = stream.StreamServer()
        self.dir = tempfile.mkdtemp()
        self.part = os.path.join(self.dir, "v.mp4.part")
        self.final = os.path.join(self.dir, "v.mp4")
        self.data = os.urandom(600 * 1024)
        self.state = {"have": 0, "s": "down"}
        with open(self.part, "wb") as f:
            f.write(self.data[:100 * 1024])
        self.state["have"] = 100 * 1024

    def tearDown(self):
        self.srv.stop()

    def info(self):
        if self.state["s"] == "done":
            return self.final, len(self.data), len(self.data), "done"
        return self.part, self.state["have"], len(self.data), self.state["s"]

    def get(self, url, rng=None, method="GET"):
        req = urllib.request.Request(url, method=method)
        if rng:
            req.add_header("Range", rng)
        return urllib.request.urlopen(req, timeout=10)

    def test_range_and_wait_for_download(self):
        url = self.srv.add(self.info, "电影.mp4")
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        with self.get(url, "bytes=0-1023") as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.headers["Content-Range"], f"bytes 0-1023/{len(self.data)}")
            self.assertEqual(r.headers["Content-Type"], "video/mp4")
            self.assertEqual(r.read(), self.data[:1024])
        with self.get(url, method="HEAD") as h:
            self.assertEqual(int(h.headers["Content-Length"]), len(self.data))

        def grow():                                          # 一边下载一边写,最后改名成正式文件
            for end in (250, 400, 600):
                time.sleep(0.25)
                with open(self.part, "ab") as f:
                    f.write(self.data[self.state["have"]:end * 1024])
                self.state["have"] = end * 1024
            os.replace(self.part, self.final)
            self.state["s"] = "done"
        threading.Thread(target=grow, daemon=True).start()
        with self.get(url, "bytes=200000-") as r:            # 拖到还没下载到的地方:等数据到了再给
            body = r.read()
        self.assertEqual(body, self.data[200000:])
        with self.get(url) as r_all:
            self.assertEqual(r_all.read(), self.data)        # 下完以后从正式文件读

    def test_errors(self):
        url = self.srv.add(self.info)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(url, f"bytes={len(self.data) + 5}-")
        self.assertEqual(cm.exception.code, 416)
        cm.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(url.replace(url.split("/")[3], "wrongtoken"))
        self.assertEqual(cm.exception.code, 404)            # 口令不对
        cm.exception.close()
        self.state["s"] = "fail"
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(url)
        cm.exception.close()
        self.state["s"] = "down"
        self.srv.remove(url)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get(url)
        cm.exception.close()

    def test_suffix_range(self):
        self.state["s"] = "done"
        with open(self.final, "wb") as f:
            f.write(self.data)
        url = self.srv.add(self.info)
        with self.get(url, "bytes=-100") as r:
            self.assertEqual(r.read(), self.data[-100:])


if __name__ == "__main__":
    unittest.main()
