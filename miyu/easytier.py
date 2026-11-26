"""
密语 3.9 · 「🌐 跨网联机（EasyTier 异地组网引擎）」
  · 默认彻底关闭（保持纯局域网零外网隐私）；用户手动开启后在后台托管开源 EasyTier 内核建立加密虚拟局域网
  · 聊天内容叠加「EasyTier 隧道加密 + 密语端到端加密」双重保护
  · 定时同步 EasyTier 在线成员虚拟 IP 喂给 core.set_mesh_targets() 单播兜底，就算防火墙拦广播也能 100% 秒发现
  · 退出密语或关闭开关时自动终止后台内核（含非管理员提权防孤儿看门狗），绝不残留后台进程
  · 支持一键邀请口令（MIYU-ET1:...）、一键下载/本地导入官方 EasyTier 内核，以及持久化手动直连 IP 列表
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from .dialogs import Dialog, info
from .ui import button, label

INVITE_PREFIX = "MIYU-ET1:"
DEFAULT_PEERS = [
    "tcp://et.sumnight.top:11010",
    "tcp://easytier.weiai.org.cn:11010",
    "tcp://183.230.36.171:11010",
    "tcp://225284.xyz:11010",
]
RETIRED_PEERS = {
    "tcp://public.easytier.cn:11010",
    "tcp://public.easytier.top:11010",
    "udp://public.easytier.cn:11010",
    "udp://public.easytier.top:11010",
}
UPTIME_STATUS_URL = "https://info.qtet.cn/uptime/api/status-page/easytier"
UPTIME_HEARTBEAT_URL = "https://info.qtet.cn/uptime/api/status-page/heartbeat/easytier"
CORE_EXE = "easytier-core.exe" if sys.platform == "win32" else "easytier-core"
CLI_EXE = "easytier-cli.exe" if sys.platform == "win32" else "easytier-cli"
_IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_NODE_URI_RE = re.compile(r"(tcp|udp)://([A-Za-z0-9.\-]+:\d+)", re.I)


def default_config() -> dict:
    return {
        "network_name": "",
        "network_secret": "",
        "peers": list(DEFAULT_PEERS),
        "manual_ips": [],
        "auto_start": False,
    }


def _filter_peers(raw_peers) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in (raw_peers or []):
        if not isinstance(p, str):
            continue
        s = p.strip()[:120]
        if "://" not in s or s.lower() in RETIRED_PEERS or s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
        if len(out) >= 8:
            break
    return out or list(DEFAULT_PEERS)


def clean_config(raw) -> dict:
    base = default_config()
    if not isinstance(raw, dict):
        return base
    name = str(raw.get("network_name") or "").strip()[:48]
    secret = str(raw.get("network_secret") or "").strip()[:64]
    peers = _filter_peers(raw.get("peers"))
    mips = [str(x).strip()[:48] for x in (raw.get("manual_ips") or []) if isinstance(x, str) and x.strip()][:30]
    return {
        "network_name": name,
        "network_secret": secret,
        "peers": peers,
        "manual_ips": mips,
        "auto_start": bool(raw.get("auto_start", False)),
    }


def render_toml(cfg: dict) -> str:
    """生成 UTF-8 TOML 配置，彻底避免 Windows PowerShell / 命令行编码弄乱中文房间名与特殊字符。"""
    c = clean_config(cfg)
    lines = [
        "dhcp = true",
        "",
        "[network_identity]",
        f"network_name = {json.dumps(c['network_name'], ensure_ascii=False)}",
        f"network_secret = {json.dumps(c['network_secret'], ensure_ascii=False)}",
        "",
    ]
    for uri in c["peers"]:
        lines.append("[[peer]]")
        lines.append(f"uri = {json.dumps(uri, ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines)


def encode_invite(name: str, secret: str, peers: list[str] | None = None) -> str:
    payload = {
        "n": (name or "").strip()[:48],
        "s": (secret or "").strip()[:64],
        "p": _filter_peers(peers)[:4],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return INVITE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_invite(text: str) -> dict | None:
    s = (text or "").strip()
    if not s.startswith(INVITE_PREFIX):
        return None
    b64 = s[len(INVITE_PREFIX):].strip()
    pad = "=" * (-len(b64) % 4)
    try:
        d = json.loads(base64.urlsafe_b64decode(b64 + pad).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict) or not str(d.get("n") or "").strip():
        return None
    return {
        "network_name": str(d.get("n", "")).strip()[:48],
        "network_secret": str(d.get("s", "")).strip()[:64],
        "peers": _filter_peers(d.get("p"))[:4],
    }


def _http_get_bytes(url: str, headers: dict[str, str] | None = None, timeout: float = 15.0) -> bytes:
    """优先使用 urllib，遇到本地代理 TLS 异常时自动回退系统 curl.exe。"""
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", "MiYu-EasyTier-Fetcher")
    try:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as first_err:
        curl = shutil.which("curl.exe" if sys.platform == "win32" else "curl")
        if not curl:
            raise first_err
        cmd = [curl, "-sSL", "--fail", "--max-time", str(max(5, int(timeout)))]
        for k, v in hdrs.items():
            cmd += ["-H", f"{k}: {v}"]
        cmd.append(url)
        flags = 0x08000000 if sys.platform == "win32" else 0
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout + 5, creationflags=flags)


def fetch_live_public_peers(max_count: int = 4) -> tuple[bool, list[str], str]:
    """从 EasyTier 社区监控实时拉取健康率 ≥95%、延迟最低的可用公共打洞节点。"""
    try:
        sp = json.loads(_http_get_bytes(UPTIME_STATUS_URL, timeout=10.0).decode("utf-8"))
        hb = json.loads(_http_get_bytes(UPTIME_HEARTBEAT_URL, timeout=10.0).decode("utf-8"))
        hlist = hb.get("heartbeatList") or {}
        uptimes = hb.get("uptimeList") or {}
        cands: list[tuple[float, float, str]] = []
        for g in sp.get("publicGroupList") or []:
            gname = str(g.get("name") or "")
            if "网站" in gname or "控制台" in gname:
                continue
            for m in g.get("monitorList") or []:
                title = str(m.get("name") or "")
                if "禁中转" in title or "*" in title or "[后端]" in title or "[web]" in title:
                    continue
                match = _NODE_URI_RE.search(title)
                if not match:
                    continue
                uri = f"{match.group(1).lower()}://{match.group(2)}"
                if uri.endswith(":22020") or uri.lower() in RETIRED_PEERS:
                    continue
                mid = str(m.get("id") or "")
                beats = hlist.get(mid) or []
                last = beats[-1] if beats else {}
                up = float(uptimes.get(f"{mid}_24") or 0.0)
                if last.get("status") != 1 or up < 0.95:
                    continue
                ping = float(last.get("ping") or 9999.0)
                cands.append((ping, -up, uri))
        cands.sort()
        picked: list[str] = []
        seen: set[str] = set()
        for ping, _nup, uri in cands:
            if uri.lower() in seen:
                continue
            seen.add(uri.lower())
            picked.append(uri)
            if len(picked) >= max_count:
                break
        if picked:
            best_ms = int(round(cands[0][0]))
            return True, picked, f"已实时获取 {len(picked)} 个在线公共节点（最快延迟约 {best_ms} ms）。"
        return False, list(DEFAULT_PEERS), "监控站暂未返回合适节点，已恢复内置高可用节点。"
    except Exception as e:
        return False, list(DEFAULT_PEERS), f"在线节点列表拉取失败（{e}），已使用内置高可用节点。"


def easytier_data_dir(data_dir: str) -> str:
    return os.path.join(data_dir, "easytier")


def bundled_easytier_zip() -> str | None:
    """查找随 MiYu.exe 一同内置打包的 easytier_bundle.zip（零外网即可秒解使用）。"""
    roots: list[str] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        roots.append(getattr(sys, "_MEIPASS"))
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for r in roots:
        p = os.path.join(r, "assets", "easytier_bundle.zip")
        if os.path.isfile(p):
            return p
    return None


def ensure_bundled_easytier(data_dir: str) -> str | None:
    """若本机尚未安装 EasyTier 内核，自动从内置压缩包秒解到数据目录（按需解压、不拖慢启动）。"""
    existing = find_easytier_dir(data_dir)
    if existing:
        return existing
    zp = bundled_easytier_zip()
    if not zp or not data_dir:
        return None
    target = easytier_data_dir(data_dir)
    ok, _msg = import_local_zip(zp, target)
    return target if ok and os.path.isfile(os.path.join(target, CORE_EXE)) else None


def find_easytier_dir(data_dir: str) -> str | None:
    """按顺序查找 easytier-core: 软件同目录 easytier/ → 数据目录 easytier/ → 系统 PATH。"""
    cands: list[str] = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(os.path.dirname(sys.executable), "easytier"))
    else:
        cands.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "easytier"))
    if data_dir:
        cands.append(easytier_data_dir(data_dir))
    for d in cands:
        if os.path.isfile(os.path.join(d, CORE_EXE)):
            return d
    found = shutil.which(CORE_EXE)
    if found:
        return os.path.dirname(found)
    return None


def import_local_zip(zip_path: str, target_dir: str) -> tuple[bool, str]:
    """安全解压官方 easytier-windows-x86_64-*.zip 中的核心文件到 target_dir（防 Zip Slip）。"""
    wanted = {CORE_EXE.lower(), CLI_EXE.lower(), "wintun.dll", "packet.dll"}
    os.makedirs(target_dir, exist_ok=True)
    extracted: list[str] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info_item in zf.infolist():
                if info_item.is_dir():
                    continue
                base = os.path.basename(info_item.filename.replace("\\", "/"))
                if base.lower() not in wanted:
                    continue
                dst = os.path.join(target_dir, base)
                with zf.open(info_item, "r") as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)
                extracted.append(base)
    except Exception as e:
        return False, f"解压失败：{e}"
    if CORE_EXE.lower() not in {x.lower() for x in extracted}:
        return False, f"压缩包里未找到 {CORE_EXE}，请确认选择的是 EasyTier Windows x86_64 发行包。"
    return True, f"已导入 {', '.join(sorted(extracted))}"


def download_latest_easytier(target_dir: str, on_progress=None) -> tuple[bool, str]:
    """从 EasyTier 官方 GitHub Releases 下载最新 Windows x86_64 核心包并安全解压。"""
    def _prog(msg: str) -> None:
        if callable(on_progress):
            try:
                on_progress(msg)
            except Exception:
                pass

    hdrs = {"User-Agent": "MiYu-EasyTier-Fetcher", "Accept": "application/vnd.github+json"}
    try:
        _prog("正在查询 EasyTier 官方最新版本…")
        rel = json.loads(_http_get_bytes(
            "https://api.github.com/repos/EasyTier/EasyTier/releases/latest", headers=hdrs, timeout=20.0
        ).decode("utf-8"))
        tag = str(rel.get("tag_name") or "latest")
        asset = None
        for a in rel.get("assets") or []:
            nm = str(a.get("name") or "").lower()
            if "windows-x86_64" in nm and nm.endswith(".zip") and "gui" not in nm:
                asset = a
                break
        if asset is None:
            return False, "未找到 Windows x86_64 内核压缩包，请点「本地导入」手动选择官网下载的 zip。"
        url = asset["browser_download_url"]
        total = int(asset.get("size") or 0)
        _prog(f"正在下载 EasyTier {tag}（{total / 1048576:.1f} MB）…")
        buf = io.BytesIO()
        try:
            dreq = urllib.request.Request(url, headers={"User-Agent": "MiYu-EasyTier-Fetcher"})
            with urllib.request.urlopen(dreq, timeout=120) as resp:
                got = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    buf.write(chunk)
                    got += len(chunk)
                    if total > 0:
                        _prog(f"正在下载 EasyTier {tag}… {got * 100 // total}% ({got / 1048576:.1f}/{total / 1048576:.1f} MB)")
        except Exception:
            _prog(f"正在通过备用通道下载 EasyTier {tag}（{total / 1048576:.1f} MB）…")
            buf = io.BytesIO(_http_get_bytes(url, timeout=120.0))
        os.makedirs(target_dir, exist_ok=True)
        tmp_zip = os.path.join(target_dir, f".dl_{os.getpid()}.zip")
        try:
            with open(tmp_zip, "wb") as f:
                f.write(buf.getvalue())
            _prog("下载完成，正在解压内核…")
            ok, msg = import_local_zip(tmp_zip, target_dir)
            return ok, (f"EasyTier {tag} 安装成功（{msg}）" if ok else msg)
        finally:
            if os.path.exists(tmp_zip):
                try:
                    os.remove(tmp_zip)
                except OSError:
                    pass
    except Exception as e:
        return False, f"自动下载失败（可能是 GitHub 网络超时）：{e}\n可自行下载 easytier-windows-x86_64-*.zip 后点「导入本地压缩包」。"


def _strip_cidr(val: str) -> str:
    s = str(val or "").strip().split("/")[0].strip()
    m = _IPV4_RE.search(s)
    return m.group(1) if m else ""


def parse_peers_output(raw: str) -> tuple[str, list[dict]]:
    """解析 `easytier-cli -o json peer`（兼容表格文本回退），返回 (本机虚拟IPv4, 远端节点列表)。"""
    text = (raw or "").strip()
    if not text:
        return "", []
    local_ip = ""
    peers: list[dict] = []

    # 1) 优先解析 JSON 格式
    if text.startswith("[") or text.startswith("{"):
        try:
            obj = json.loads(text)
            rows = obj if isinstance(obj, list) else (obj.get("peers") or obj.get("routes") or [])
            if isinstance(rows, list):
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    ip = _strip_cidr(r.get("ipv4") or r.get("ip") or "")
                    if not ip:
                        continue
                    cost = str(r.get("cost") or "").strip()
                    host = str(r.get("hostname") or r.get("host") or "").strip()[:28]
                    lat = str(r.get("lat_ms") or r.get("lat") or r.get("cost_ms") or "-").strip()
                    tun = str(r.get("tunnel_proto") or r.get("tunnel") or "").strip()
                    loss = str(r.get("loss_rate") or r.get("loss") or "").strip()
                    if cost.lower() == "local":
                        local_ip = ip
                    else:
                        peers.append({"ipv4": ip, "hostname": host, "cost": cost or "p2p",
                                      "lat_ms": lat, "tunnel": tun, "loss": loss})
                return local_ip, peers
        except ValueError:
            pass

    # 2) 回退解析 ASCII 表格输出（兼容旧版 easytier-cli）
    for line in text.splitlines():
        if "|" not in line or "ipv4" in line.lower() or set(line.strip()) <= set("+-=| "):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 3:
            continue
        ip = _strip_cidr(cols[0])
        if not ip:
            continue
        host = cols[1][:28] if len(cols) > 1 else ""
        cost = cols[2] if len(cols) > 2 else ""
        lat = cols[3] if len(cols) > 3 else "-"
        loss = cols[4] if len(cols) > 4 else ""
        tun = cols[7] if len(cols) > 7 else ""
        if cost.lower() == "local":
            local_ip = ip
        else:
            peers.append({"ipv4": ip, "hostname": host, "cost": cost or "p2p",
                          "lat_ms": lat, "tunnel": tun, "loss": loss})
    return local_ip, peers


def parse_connectors_output(raw: str) -> list[dict]:
    """解析 `easytier-cli -o json connector`（兼容文本回退），返回 [{'url': ..., 'status': 'Connected'|'Connecting'|'Disconnected'}]。"""
    text = (raw or "").strip()
    if not text:
        return []
    code_map = {0: "Connected", 1: "Disconnected", 2: "Connecting"}
    out: list[dict] = []
    if text.startswith("[") or text.startswith("{"):
        try:
            obj = json.loads(text)
            rows = obj if isinstance(obj, list) else (obj.get("connectors") or [])
            if isinstance(rows, list):
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    u = r.get("url")
                    url_s = str(u.get("url") if isinstance(u, dict) else (u or "")).strip()
                    st_raw = r.get("status")
                    if isinstance(st_raw, int):
                        st = code_map.get(st_raw, "Connecting")
                    else:
                        st = str(st_raw or "Connecting").strip()
                    if url_s:
                        out.append({"url": url_s, "status": st})
                return out
        except ValueError:
            pass
    urls = re.findall(r'url:\s*"([^"]+)"', text)
    sts = re.findall(r"status:\s*([A-Za-z]+)", text)
    for u, st in zip(urls, sts):
        out.append({"url": u, "status": st})
    return out


def _is_windows_admin() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class EasyTierManager:
    """后台托管 easytier-core 生命周期，支持 UTF-8 TOML 配置、直启与 Windows 隐藏提权防孤儿看门狗。"""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir
        self.running = False
        self.state = "stopped"          # stopped / starting / connected / timeout / error
        self.error = ""
        self.local_ip = ""
        self.peers: list[dict] = []
        self.connectors: list[dict] = []
        self.relay_ok = 0
        self.started_at = 0.0
        self.rpc_port = 15888
        self._proc: subprocess.Popen | None = None
        self._stop_file = ""
        self._cfg_file = ""
        self._et_dir = ""
        self._lock = threading.Lock()

    def build_args(self, cfg_path: str, rpc_port: int) -> list[str]:
        return ["-c", cfg_path, "--rpc-portal", f"127.0.0.1:{rpc_port}"]

    def start(self, cfg: dict) -> tuple[bool, str]:
        cfg = clean_config(cfg)
        if not cfg["network_name"]:
            return False, "请先填写「跨网房间名」。"
        if len(cfg["network_secret"]) < 4:
            return False, "为保障安全，请设置至少 4 位的「跨网密码」。"
        et_dir = ensure_bundled_easytier(self.data_dir)
        if not et_dir:
            return False, "尚未安装 EasyTier 内核，请先点击「一键下载内核」或「导入本地压缩包」。"

        self.stop()
        self._et_dir = et_dir
        self.rpc_port = _pick_free_port()
        core_path = os.path.join(et_dir, CORE_EXE)
        et_tmp_dir = easytier_data_dir(self.data_dir)
        os.makedirs(et_tmp_dir, exist_ok=True)
        nonce = secrets.token_hex(6)
        cfg_path = os.path.join(et_tmp_dir, f".cfg_{nonce}.toml")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(render_toml(cfg))
        self._cfg_file = cfg_path
        args = self.build_args(cfg_path, self.rpc_port)
        self.error = ""
        self.local_ip = ""
        self.peers = []
        self.connectors = []
        self.relay_ok = 0

        try:
            if sys.platform != "win32" or _is_windows_admin():
                flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
                self._proc = subprocess.Popen(
                    [core_path, *args],
                    cwd=et_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                )
            else:
                # 非管理员 Windows:通过 UAC 启动隐藏看门狗(UTF-8 BOM),监听 stop 文件或主进程退出自动清理内核与临时配置
                self._stop_file = os.path.join(et_tmp_dir, f".stop_{nonce}")
                ps_path = os.path.join(et_tmp_dir, f".watch_{nonce}.ps1")
                if os.path.exists(self._stop_file):
                    os.remove(self._stop_file)
                arg_list_ps = ", ".join("'" + a.replace("'", "''") + "'" for a in args)
                ps_script = (
                    "$ErrorActionPreference='SilentlyContinue'\n"
                    f"$core = '{core_path.replace(chr(39), chr(39)*2)}'\n"
                    f"$wd = '{et_dir.replace(chr(39), chr(39)*2)}'\n"
                    f"$stopf = '{self._stop_file.replace(chr(39), chr(39)*2)}'\n"
                    f"$cfgf = '{cfg_path.replace(chr(39), chr(39)*2)}'\n"
                    f"$selfps = '{ps_path.replace(chr(39), chr(39)*2)}'\n"
                    f"$parentPid = {os.getpid()}\n"
                    f"$p = Start-Process -FilePath $core -ArgumentList @({arg_list_ps}) -WorkingDirectory $wd -WindowStyle Hidden -PassThru\n"
                    "while ($p -and -not $p.HasExited) {\n"
                    "  if (Test-Path $stopf) { break }\n"
                    "  if (-not (Get-Process -Id $parentPid -ErrorAction SilentlyContinue)) { break }\n"
                    "  Start-Sleep -Milliseconds 400\n"
                    "}\n"
                    "if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force }\n"
                    "Remove-Item $stopf,$cfgf,$selfps -Force -ErrorAction SilentlyContinue\n"
                )
                with open(ps_path, "w", encoding="utf-8-sig") as f:
                    f.write(ps_script)
                import ctypes
                rc = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", "powershell.exe",
                    f'-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{ps_path}"',
                    et_dir, 0,
                )
                if rc <= 32:
                    for fp in (ps_path, cfg_path):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass
                    self._stop_file = ""
                    self._cfg_file = ""
                    return False, "已取消 Windows 管理员授权，未开启跨网联机。"
            self.running = True
            self.state = "starting"
            self.started_at = time.monotonic()
            return True, "正在启动跨网虚拟通道并连接公共节点…"
        except Exception as e:
            self._remove_cfg_file()
            self.state = "error"
            self.error = str(e)
            return False, f"启动失败：{e}"

    def _remove_cfg_file(self) -> None:
        if self._cfg_file:
            try:
                if os.path.exists(self._cfg_file):
                    os.remove(self._cfg_file)
            except OSError:
                pass
            self._cfg_file = ""

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            self._remove_cfg_file()
        if self._stop_file:
            try:
                with open(self._stop_file, "w", encoding="utf-8") as f:
                    f.write("stop")
            except OSError:
                pass
            self._stop_file = ""
            self._cfg_file = ""
        self.running = False
        self.state = "stopped"
        self.local_ip = ""
        self.peers = []
        self.connectors = []
        self.relay_ok = 0

    def _run_cli(self, cli_path: str, args: list[str]) -> str:
        flags = 0x08000000 if sys.platform == "win32" else 0
        try:
            out = subprocess.check_output(
                [cli_path, "-p", f"127.0.0.1:{self.rpc_port}", *args],
                stderr=subprocess.DEVNULL,
                timeout=2.5,
                creationflags=flags,
            )
            return out.decode("utf-8", errors="replace").strip()
        except Exception:
            return ""

    def poll_status(self) -> tuple[str, str, list[dict]]:
        """通过 easytier-cli 查询实时本机虚拟 IP、公共节点连通状态与在线好友列表。"""
        if not self.running:
            return "stopped", "", []
        if self._proc is not None and self._proc.poll() is not None:
            self.running = False
            self.state = "error"
            self.error = f"EasyTier 内核已退出（代码 {self._proc.returncode}）"
            return self.state, "", []
        cli_path = os.path.join(self._et_dir, CLI_EXE) if self._et_dir else ""
        if not cli_path or not os.path.isfile(cli_path):
            return self.state, self.local_ip, self.peers

        raw_conn = self._run_cli(cli_path, ["-o", "json", "connector"]) or self._run_cli(cli_path, ["connector"])
        if raw_conn:
            self.connectors = parse_connectors_output(raw_conn)
            self.relay_ok = sum(1 for c in self.connectors if str(c.get("status")).lower() == "connected")

        raw = self._run_cli(cli_path, ["-o", "json", "peer"]) or self._run_cli(cli_path, ["peer"])
        if raw:
            lip, peers = parse_peers_output(raw)
            if lip:
                self.local_ip = lip
                self.state = "connected"
                self.error = ""
            self.peers = peers

        if not self.local_ip and self.started_at and (time.monotonic() - self.started_at) >= 12.0:
            if self.connectors and self.relay_ok == 0:
                self.state = "timeout"
                self.error = "公共打洞节点均未连通，请点击「🌐 刷新在线节点」更换节点，或检查代理软件/防火墙设置。"
        return self.state, self.local_ip, self.peers


class EasyTierDialog(Dialog):
    """「🌐 跨网联机（EasyTier 异地组网）」配置与实时监控窗口。"""
    _dl_done = Signal(bool, str)
    _dl_prog = Signal(str)
    _nodes_done = Signal(bool, object, str)

    def __init__(self, win) -> None:
        super().__init__(win, "跨网联机 · EasyTier 异地组网")
        self.win = win
        self.setFixedWidth(560)
        cfg = clean_config(getattr(win, "easytier_cfg", None))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(label("🌐 跨网联机（EasyTier 异地组网）", "dialogTitle"))
        head.addStretch(1)
        self.state_lab = label("", "cardTitle")
        head.addWidget(self.state_lab)
        lay.addLayout(head)

        # 内核状态卡片
        bin_card = QFrame(self)
        bin_card.setObjectName("plainCard")
        bl = QHBoxLayout(bin_card)
        bl.setContentsMargins(14, 9, 12, 9)
        bl.setSpacing(8)
        self.bin_lab = label("", "hint", wrap=True)
        bl.addWidget(self.bin_lab, 1)
        self.dl_btn = button("⬇ 一键下载内核", "primary", self._start_download, 118)
        self.imp_btn = button("📂 本地导入", "", self._import_zip, 92)
        bl.addWidget(self.dl_btn)
        bl.addWidget(self.imp_btn)
        lay.addWidget(bin_card)

        # 房间配置卡片
        cfg_card = QFrame(self)
        cfg_card.setObjectName("plainCard")
        cl = QVBoxLayout(cfg_card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)

        r1 = QHBoxLayout()
        r1.addWidget(label("跨网房间名", "section"))
        self.name_edit = QLineEdit(cfg["network_name"], self)
        self.name_edit.setPlaceholderText("例如：miyu-friends-2026（好友填相同的即可）")
        self.name_edit.setMaxLength(48)
        r1.addWidget(self.name_edit, 1)
        cl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(label("跨网密码　", "section"))
        self.sec_edit = QLineEdit(cfg["network_secret"], self)
        self.sec_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.sec_edit.setPlaceholderText("至少 4 位，建议字母+数字防外人猜中")
        self.sec_edit.setMaxLength(64)
        r2.addWidget(self.sec_edit, 1)
        self.eye_btn = button("👁", "", self._toggle_eye, 34)
        r2.addWidget(self.eye_btn)
        cl.addLayout(r2)

        p_head = QHBoxLayout()
        p_head.addWidget(label("公共打洞节点（每行一个，已内置高可用公益节点）：", "hint"))
        p_head.addStretch(1)
        self.nodes_btn = button("🌐 刷新在线节点", "", self._refresh_public_nodes, 118)
        p_head.addWidget(self.nodes_btn)
        cl.addLayout(p_head)
        self.peers_edit = QPlainTextEdit("\n".join(cfg["peers"]), self)
        self.peers_edit.setFixedHeight(68)
        cl.addWidget(self.peers_edit)

        inv_row = QHBoxLayout()
        inv_row.setSpacing(6)
        inv_row.addWidget(button("📋 复制邀请口令", "", self._copy_invite, 124))
        inv_row.addWidget(button("📥 粘贴口令填入", "", self._paste_invite, 124))
        inv_row.addStretch(1)
        inv_row.addWidget(label("配置会自动加密保存", "faint"))
        cl.addLayout(inv_row)
        lay.addWidget(cfg_card)

        # 实时在线跨网节点列表
        lay.addWidget(label("实时跨网节点（已自动单播同步到密语发现，防火墙拦广播也能秒连）：", "section"))
        self.peer_box = QWidget(self)
        self.peer_lay = QVBoxLayout(self.peer_box)
        self.peer_lay.setContentsMargins(6, 4, 6, 4)
        self.peer_lay.setSpacing(4)
        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setFixedHeight(96)
        area.setWidget(self.peer_box)
        lay.addWidget(area)

        # 持久化手动直连 IP（兼容 ZeroTier / Tailscale / 外置 EasyTier）
        lay.addWidget(label("常驻直连 IP（可选，每行一个，兼容 Tailscale / ZeroTier，重启自动记住）：", "hint"))
        self.manual_edit = QPlainTextEdit("\n".join(cfg.get("manual_ips") or []), self)
        self.manual_edit.setPlaceholderText("例如：10.126.126.2 或 100.64.0.5:47820")
        self.manual_edit.setFixedHeight(52)
        lay.addWidget(self.manual_edit)

        self.tip_lab = label("隐私说明：默认关闭时密语 100% 纯局域网不连外网；开启后叠加 EasyTier 隧道 + 密语端到端双重加密。",
                             "faint", wrap=True)
        lay.addWidget(self.tip_lab)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.toggle_btn = button("🌐 开启跨网联机", "primary", self._toggle_mesh, 138)
        foot.addWidget(self.toggle_btn)
        foot.addWidget(button("💾 仅保存配置", "", self._save_only, 108))
        foot.addStretch(1)
        foot.addWidget(button("关闭", "", self.accept, 76))
        lay.addLayout(foot)

        self._dl_prog.connect(self._on_dl_prog)
        self._dl_done.connect(self._on_dl_done)
        self._nodes_done.connect(self._on_nodes_done)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1500)
        self._poll_timer.timeout.connect(self.refresh)
        self._poll_timer.start()
        self.refresh()

    def _data_dir(self) -> str:
        st = getattr(self.win, "store", None)
        return st.folder if st is not None else os.path.expanduser("~")

    def _collect_cfg(self) -> dict:
        peers = [ln.strip() for ln in self.peers_edit.toPlainText().splitlines() if "://" in ln.strip()]
        mips = [ln.strip() for ln in self.manual_edit.toPlainText().splitlines() if ln.strip()]
        return clean_config({
            "network_name": self.name_edit.text().strip(),
            "network_secret": self.sec_edit.text().strip(),
            "peers": peers or list(DEFAULT_PEERS),
            "manual_ips": mips,
        })

    def _apply_cfg(self) -> dict:
        cfg = self._collect_cfg()
        self.win.easytier_cfg = cfg
        if hasattr(self.win, "apply_manual_mesh_ips"):
            self.win.apply_manual_mesh_ips()
        if hasattr(self.win, "save_account"):
            self.win.save_account(force=True)
        return cfg

    def _save_only(self) -> None:
        self._apply_cfg()
        self.tip_lab.setText("✅ 配置与常驻直连 IP 已加密保存，并已立即刷新发现列表。")

    def _toggle_eye(self) -> None:
        show = self.sec_edit.echoMode() == QLineEdit.EchoMode.Password
        self.sec_edit.setEchoMode(QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password)

    def _copy_invite(self) -> None:
        cfg = self._collect_cfg()
        if not cfg["network_name"] or len(cfg["network_secret"]) < 4:
            self.tip_lab.setText("请先填好房间名和至少 4 位密码再复制邀请口令。")
            return
        code = encode_invite(cfg["network_name"], cfg["network_secret"], cfg["peers"])
        QApplication.clipboard().setText(code)
        self.tip_lab.setText("📋 跨网邀请口令已复制！发给朋友点「粘贴口令填入」即可一键加入。")

    def _paste_invite(self) -> None:
        d = decode_invite(QApplication.clipboard().text() or "")
        if d is None:
            self.tip_lab.setText("剪贴板里没有识别到有效口令（需以 MIYU-ET1: 开头）。")
            return
        self.name_edit.setText(d["network_name"])
        self.sec_edit.setText(d["network_secret"])
        self.peers_edit.setPlainText("\n".join(d["peers"]))
        self.tip_lab.setText("✅ 已从邀请口令自动填入房间名、密码和节点，点「开启跨网联机」即可！")

    def _start_download(self) -> None:
        self.dl_btn.setEnabled(False)
        self.imp_btn.setEnabled(False)
        target = easytier_data_dir(self._data_dir())

        def _worker() -> None:
            ok, msg = download_latest_easytier(target, on_progress=self._dl_prog.emit)
            self._dl_done.emit(ok, msg)

        threading.Thread(target=_worker, name="miyu-et-dl", daemon=True).start()

    def _on_dl_prog(self, msg: str) -> None:
        self.bin_lab.setText(msg)

    def _on_dl_done(self, ok: bool, msg: str) -> None:
        self.dl_btn.setEnabled(True)
        self.imp_btn.setEnabled(True)
        self.tip_lab.setText(("✅ " if ok else "⚠️ ") + msg)
        self.refresh()

    def _refresh_public_nodes(self) -> None:
        self.nodes_btn.setEnabled(False)
        self.tip_lab.setText("🌐 正在从 EasyTier 社区监控拉取最新高可用节点…")

        def _worker() -> None:
            ok, peers, msg = fetch_live_public_peers(4)
            self._nodes_done.emit(ok, peers, msg)

        threading.Thread(target=_worker, name="miyu-et-nodes", daemon=True).start()

    def _on_nodes_done(self, ok: bool, peers, msg: str) -> None:
        self.nodes_btn.setEnabled(True)
        if isinstance(peers, list) and peers:
            self.peers_edit.setPlainText("\n".join(peers))
            self._apply_cfg()
        self.tip_lab.setText(("✅ " if ok else "⚠️ ") + msg)

    def _import_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 EasyTier Windows x86_64 压缩包", "", "Zip 压缩包 (*.zip);;所有文件 (*.*)",
        )
        if not path:
            return
        ok, msg = import_local_zip(path, easytier_data_dir(self._data_dir()))
        self.tip_lab.setText(("✅ " if ok else "⚠️ ") + msg)
        self.refresh()

    def _toggle_mesh(self) -> None:
        mgr = getattr(self.win, "easytier_mgr", None)
        if mgr is not None and mgr.running:
            self.win.stop_easytier()
            self.tip_lab.setText("⏹ 已断开跨网联机并关闭后台内核，已恢复纯局域网模式。")
        else:
            cfg = self._apply_cfg()
            ok, msg = self.win.start_easytier(cfg)
            self.tip_lab.setText(("🚀 " if ok else "⚠️ ") + msg)
            if not ok and "内核" in msg:
                info(self, "需要 EasyTier 内核", msg)
        self.refresh()

    def refresh(self) -> None:
        et_dir = ensure_bundled_easytier(self._data_dir())
        if et_dir:
            tag = "内置自带 · 已就绪" if bundled_easytier_zip() else os.path.basename(et_dir)
            self.bin_lab.setText(f"✅ EasyTier 内核已就绪（{tag}）")
            self.dl_btn.setText("🔄 更新内核")
        else:
            self.bin_lab.setText("⬇️ 尚未安装 EasyTier 内核（约 10 MB，仅需安装一次）")
            self.dl_btn.setText("⬇ 一键下载内核")

        mgr: EasyTierManager | None = getattr(self.win, "easytier_mgr", None)
        total_relays = len(mgr.connectors) if mgr else 0
        ok_relays = mgr.relay_ok if mgr else 0
        if mgr is None or not mgr.running:
            self.state_lab.setText("🔴 未开启（纯局域网）")
            self.toggle_btn.setText("🌐 开启跨网联机")
        elif mgr.state == "connected":
            self.state_lab.setText(f"🟢 已连入 {mgr.local_ip} · {len(mgr.peers)} 位好友")
            self.toggle_btn.setText("⏹ 断开跨网")
        elif mgr.state == "timeout":
            self.state_lab.setText("⚠️ 公共节点连接超时")
            self.toggle_btn.setText("⏹ 取消连接")
            if mgr.error:
                self.tip_lab.setText("⚠️ " + mgr.error)
        elif mgr.state == "error":
            self.state_lab.setText("🔴 内核异常")
            self.toggle_btn.setText("🌐 重新连接")
            if mgr.error:
                self.tip_lab.setText("⚠️ " + mgr.error)
        else:
            sub = f"（节点 {ok_relays}/{total_relays}）" if total_relays else ""
            self.state_lab.setText(f"🟡 正在连接打洞…{sub}")
            self.toggle_btn.setText("⏹ 取消连接")

        while self.peer_lay.count():
            it = self.peer_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        peers = mgr.peers if mgr and mgr.running else []
        if not peers:
            if mgr and mgr.running and mgr.state == "connected":
                relay_txt = f"（已连通 {ok_relays}/{total_relays} 个公共节点）" if total_relays else ""
                msg = f"✅ 本机已接入跨网虚拟通道 {mgr.local_ip}{relay_txt}。\n等朋友输入同一房间名与密码后会自动出现并直连~"
            elif mgr and mgr.running and mgr.state == "timeout":
                msg = "⚠️ 公共节点暂时全部不可达，请点上方「🌐 刷新在线节点」，断开后重新开启。"
            elif mgr and mgr.running:
                msg = "正在握手并分配本机虚拟 IP（约 2~4 秒），请稍候…"
            else:
                msg = "开启跨网联机后，此处会实时显示跨城好友的 P2P 直连状态与延迟。"
            self.peer_lay.addWidget(label(msg, "faint", wrap=True))
        else:
            for pr in peers:
                is_p2p = "p2p" in pr["cost"].lower()
                tag = "🟢 P2P直连" if is_p2p else f"🟡 中继({pr['cost']})"
                row_txt = f"{tag}   {pr['ipv4']}   {pr['hostname'] or '好友节点'}   延迟 {pr['lat_ms']} ms"
                self.peer_lay.addWidget(label(row_txt, "hint"))
        self.peer_lay.addStretch(1)

    def closeEvent(self, e) -> None:
        self._poll_timer.stop()
        super().closeEvent(e)

    def accept(self) -> None:
        self._poll_timer.stop()
        super().accept()

    def reject(self) -> None:
        self._poll_timer.stop()
        super().reject()
