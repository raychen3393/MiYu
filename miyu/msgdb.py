"""
密语 · 加密聊天记录数据库(2.0)

用 Python 自带的 sqlite。sqlite 本身不加密,所以:
  · 每条消息单独用 ChaCha20-Poly1305 加密后再存(和会话、消息 ID 绑定,不能挪到别处冒充)
  · 会话和消息 ID 存的是带密钥的哈希:别人拿到数据库文件,只能看到"大概有多少条、什么时间",
    看不到内容,也看不出是和谁聊的
  · 数据库密钥随机生成,存在账户文件里(账户文件本身有 DPAPI 和启动密码保护)

性能:按 (会话, 时间) 建索引,分页读取;WAL 日志;过期记录定期删除,空间增量回收。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DB_FILE = "m.db"
DB_FILES = (DB_FILE, DB_FILE + "-wal", DB_FILE + "-shm", DB_FILE + "-journal")
SCHEMA = 1
CHECK = b"miyu-db-ok"


class WrongKey(Exception):
    """数据库不是用这把钥匙加密的(比如账户被重建过)。"""


class MsgDB:
    def __init__(self, path: str, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("bad key")
        km = HKDF(algorithm=hashes.SHA256(), length=64, salt=None, info=b"miyu-msgdb-v1").derive(key)
        self._aead = ChaCha20Poly1305(km[:32])
        self._mac = km[32:]
        self.path = path
        new = not os.path.exists(path)
        self.con = sqlite3.connect(path, isolation_level=None, check_same_thread=False, timeout=10)
        c = self.con
        c.execute("PRAGMA busy_timeout=10000")
        if new:
            c.execute("PRAGMA auto_vacuum=INCREMENTAL")             # 必须在建表之前设
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA temp_store=MEMORY")
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v BLOB NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS convs(c BLOB PRIMARY KEY, data BLOB NOT NULL)")
        c.execute("CREATE TABLE IF NOT EXISTS msgs(id INTEGER PRIMARY KEY AUTOINCREMENT, c BLOB NOT NULL, "
                  "m BLOB NOT NULL UNIQUE, ts REAL NOT NULL, data BLOB NOT NULL)")
        c.execute("CREATE INDEX IF NOT EXISTS msgs_c_ts ON msgs(c, ts, id)")
        c.execute("CREATE INDEX IF NOT EXISTS msgs_ts ON msgs(ts)")
        row = c.execute("SELECT v FROM meta WHERE k='check'").fetchone()
        if row is None:
            c.execute("INSERT INTO meta(k, v) VALUES('check', ?)", (self._seal(CHECK, b"check"),))
            c.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('schema', ?)", (str(SCHEMA).encode(),))
        elif self._open(row[0], b"check") != CHECK:
            self.con.close()
            raise WrongKey(path)

    # ---------------------------------------------------------------- 加密
    def _h(self, kind: str, s: str) -> bytes:
        return hmac.new(self._mac, f"{kind}:{s}".encode(), hashlib.sha256).digest()[:16]

    def _seal(self, data: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, data, aad)

    def _open(self, blob: bytes, aad: bytes) -> bytes | None:
        try:
            return self._aead.decrypt(bytes(blob[:12]), bytes(blob[12:]), aad)
        except Exception:                                       # noqa: BLE001  被改过 / 不是这把钥匙
            return None

    def _enc(self, obj, aad: bytes) -> bytes:
        return self._seal(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), aad)

    def _dec(self, blob: bytes, aad: bytes):
        raw = self._open(blob, aad)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    # ---------------------------------------------------------------- 会话
    def put_conv(self, key: str, info: dict) -> None:
        c = self._h("c", key)
        self.con.execute("INSERT INTO convs(c, data) VALUES(?, ?) ON CONFLICT(c) DO UPDATE SET data=excluded.data",
                         (c, self._enc({**info, "key": key}, c)))

    def convs(self) -> list[dict]:
        out = []
        for c, data in self.con.execute("SELECT c, data FROM convs"):
            d = self._dec(data, bytes(c))
            if isinstance(d, dict) and isinstance(d.get("key"), str):
                out.append(d)
        return out

    def delete_conv(self, key: str) -> None:
        c = self._h("c", key)
        self.con.execute("BEGIN")
        self.con.execute("DELETE FROM msgs WHERE c=?", (c,))
        self.con.execute("DELETE FROM convs WHERE c=?", (c,))
        self.con.execute("COMMIT")

    # ---------------------------------------------------------------- 消息
    def upsert_many(self, conv_key: str, rows: list[dict]) -> int:
        """写入 / 更新消息(按消息 ID 去重)。rows 是 storage.msg_to_dict 的结果。"""
        if not rows:
            return 0
        c = self._h("c", conv_key)
        args = []
        for d in rows:
            m = self._h("m", d["mid"])
            args.append((c, m, float(d.get("time") or 0), self._enc(d, c + m)))
        self.con.execute("BEGIN")
        self.con.executemany("INSERT INTO msgs(c, m, ts, data) VALUES(?, ?, ?, ?) "
                             "ON CONFLICT(m) DO UPDATE SET c=excluded.c, ts=excluded.ts, data=excluded.data", args)
        self.con.execute("COMMIT")
        return len(args)

    def delete_mids(self, mids) -> None:
        hs = [(self._h("m", mid),) for mid in mids]
        if hs:
            self.con.execute("BEGIN")
            self.con.executemany("DELETE FROM msgs WHERE m=?", hs)
            self.con.execute("COMMIT")

    def _rows(self, cur, c: bytes) -> list[dict]:
        out = []
        for m, data in cur:
            d = self._dec(data, c + bytes(m))
            if isinstance(d, dict) and isinstance(d.get("mid"), str):
                out.append(d)
        return out

    def _cursor(self, conv_key: str, before_mid: str | None, before_ts: float | None):
        """"比某条消息更早"的位置:(时间, 行号)。那条消息不在库里时只按时间。"""
        if before_mid:
            row = self.con.execute("SELECT ts, id FROM msgs WHERE m=?", (self._h("m", before_mid),)).fetchone()
            if row is not None:
                return row[0], row[1]
        if before_ts is None:
            return None
        return float(before_ts), -1

    def recent(self, conv_key: str, n: int) -> list[dict]:
        """最新的 n 条(从旧到新)。"""
        c = self._h("c", conv_key)
        cur = self.con.execute("SELECT m, data FROM msgs WHERE c=? ORDER BY ts DESC, id DESC LIMIT ?", (c, int(n)))
        return self._rows(cur, c)[::-1]

    def older(self, conv_key: str, before_mid: str | None, before_ts: float | None, n: int) -> list[dict]:
        """比 before 更早的 n 条(从旧到新)。"""
        c = self._h("c", conv_key)
        pos = self._cursor(conv_key, before_mid, before_ts)
        if pos is None:
            return self.recent(conv_key, n)
        ts, rid = pos
        cur = self.con.execute("SELECT m, data FROM msgs WHERE c=? AND (ts < ? OR (ts = ? AND id < ?)) "
                               "ORDER BY ts DESC, id DESC LIMIT ?", (c, ts, ts, rid, int(n)))
        return self._rows(cur, c)[::-1]

    def count_older(self, conv_key: str, before_mid: str | None, before_ts: float | None) -> int:
        c = self._h("c", conv_key)
        pos = self._cursor(conv_key, before_mid, before_ts)
        if pos is None:
            return self.count(conv_key)
        ts, rid = pos
        return self.con.execute("SELECT COUNT(*) FROM msgs WHERE c=? AND (ts < ? OR (ts = ? AND id < ?))",
                                (c, ts, ts, rid)).fetchone()[0]

    def count(self, conv_key: str | None = None) -> int:
        if conv_key is None:
            return self.con.execute("SELECT COUNT(*) FROM msgs").fetchone()[0]
        return self.con.execute("SELECT COUNT(*) FROM msgs WHERE c=?", (self._h("c", conv_key),)).fetchone()[0]

    def has(self, mid: str) -> bool:
        return self.con.execute("SELECT 1 FROM msgs WHERE m=?", (self._h("m", mid),)).fetchone() is not None

    def scan_older(self, conv_key: str, before_mid: str | None, before_ts: float | None, batch: int = 500):
        """从 before 往前一批批读(从新到旧),给会话内搜索用。"""
        while True:
            rows = self.older(conv_key, before_mid, before_ts, batch)
            if not rows:
                return
            for d in reversed(rows):
                yield d
            before_mid, before_ts = rows[0]["mid"], rows[0].get("time")
            if len(rows) < batch:
                return

    # ---------------------------------------------------------------- 杂项数据(文件传输状态、游戏和投票)
    def set_meta(self, name: str, obj) -> None:
        self.con.execute("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                         ("x:" + name, self._enc(obj, b"meta:" + name.encode())))

    def get_meta(self, name: str, default=None):
        row = self.con.execute("SELECT v FROM meta WHERE k=?", ("x:" + name,)).fetchone()
        if row is None:
            return default
        v = self._dec(row[0], b"meta:" + name.encode())
        return default if v is None else v

    # ---------------------------------------------------------------- 维护
    def prune(self, days: int, now: float | None = None) -> int:
        """删掉 days 天以前的消息。days <= 0 = 全部保留。"""
        if days <= 0:
            return 0
        cut = (time.time() if now is None else now) - days * 86400
        cur = self.con.execute("DELETE FROM msgs WHERE ts < ?", (cut,))
        return cur.rowcount or 0

    def maintain(self) -> None:
        """回收删掉的空间、更新查询统计(很快,可以定期跑)。"""
        self.con.execute("PRAGMA incremental_vacuum(4000)")
        self.con.execute("PRAGMA optimize")
        try:
            self.con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error:
            pass

    def compact(self) -> None:
        """彻底整理(VACUUM),记录很多时要几秒。"""
        self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.con.execute("VACUUM")

    def size(self) -> int:
        total = 0
        for name in DB_FILES:
            p = self.path[: -len(DB_FILE)] + name if self.path.endswith(DB_FILE) else self.path + name[len(DB_FILE):]
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
        return total

    def close(self) -> None:
        try:
            self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.con.close()


def remove_files(folder: str) -> None:
    """删掉数据库文件(关闭之后调用)。先用随机数据覆盖一遍再删。"""
    for name in DB_FILES:
        p = os.path.join(folder, name)
        if not os.path.exists(p):
            continue
        try:
            size = os.path.getsize(p)
            with open(p, "r+b") as f:
                left = size
                while left > 0:
                    n = min(left, 1 << 20)
                    f.write(os.urandom(n))
                    left -= n
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass
        try:
            os.remove(p)
        except OSError:
            pass
