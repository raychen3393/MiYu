"""
密语 3.9.4 · EasyTier 内核安全校验(纯逻辑,不涉及界面,可单独测试)

为什么需要它:跨网联机要用管理员权限运行 easytier-core.exe(建虚拟网卡)。
以前只看文件名就提权运行,而且程序、启动脚本、配置都放在普通用户能改的目录里,
别人把病毒改名成 easytier-core.exe 放进 zip、或者趁 UAC 弹窗的空档把脚本换掉,
就能借密语拿到管理员权限。现在的做法:

1. 指纹白名单:内核的每个文件(easytier-core.exe / easytier-cli.exe / wintun.dll / packet.dll)
   都要算 SHA-256,和白名单比对。白名单来源只有三个:
     · 打包时由 tools/release.py etpin 根据内置 easytier_bundle.zip 生成的 miyu/_etpin.py
       (打包时会和官方 v2.6.4 发行包逐文件核对,对不上就打包失败);
     · 从 GitHub 下载、且整个压缩包哈希等于下面 OFFICIAL_ZIP_SHA256 的官方包;
     · 用户在弹窗里明确点了"我确认来源可信"的内核(记在加密保存的账户里)。
2. 先复制再校验再运行:提权后由管理员进程把内核复制到 C:\\Program Files\\MiYu-EasyTier\\<指纹>
   (只有管理员能写),对复制出来的文件重新算哈希,对上了才运行。复制之后普通程序改不了它,
   所以"校验完到运行之间被偷换"这条路堵死了。配置文件也由管理员进程写在那里,并收紧权限。
3. 启动脚本防篡改:提权命令本身(-EncodedCommand,UAC 之后就改不了)里写着脚本的 SHA-256,
   管理员进程把脚本读进内存、核对哈希、再执行内存里这一份,磁盘上的文件被换了也没用。
   管理员进程不在用户目录里写入或删除任何东西,避免被符号链接骗去改系统文件。
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
import zipfile

# ---------------------------------------------------------------- 常量
PINNED_VERSION = "2.6.4"
OFFICIAL_ZIP_NAME = f"easytier-windows-x86_64-v{PINNED_VERSION}.zip"
OFFICIAL_ZIP_URL = f"https://github.com/EasyTier/EasyTier/releases/download/v{PINNED_VERSION}/{OFFICIAL_ZIP_NAME}"
# 官方 GitHub Releases 页面公布的 easytier-windows-x86_64-v2.6.4.zip 的 SHA-256
OFFICIAL_ZIP_SHA256 = "27af91e270e554709b048bd32327fefd2dfce5062ae1e8701af7550c6f525f84"
# 可选:锁定内置 assets/easytier_bundle.zip 本身的 SHA-256。留空时,打包脚本会把内置包里的文件
# 和官方发行包逐个核对;如果你的内置包是自己重新压缩过的(哈希和官方 zip 不同),
# 可以把 `python tools/release.py etpin` 打印出来的哈希填在这里,以后换包会被打包脚本拦下来。
EXPECTED_BUNDLE_SHA256 = ""

CORE = "easytier-core.exe"
CLI = "easytier-cli.exe"
KERNEL_FILES = (CORE, CLI, "wintun.dll", "packet.dll")
PROTECTED_DIRNAME = "MiYu-EasyTier"
MAX_TRUSTED = 32

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------- 哈希
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_hash_cache: dict[str, tuple[int, int, str]] = {}


def sha256_file(path: str, cache: bool = False) -> str:
    """算文件的 SHA-256。cache=True 只给界面显示用(按大小+修改时间缓存),真正启动前一律重新算。"""
    st = os.stat(path)
    if cache:
        hit = _hash_cache.get(path)
        if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
            return hit[2]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    digest = h.hexdigest()
    if cache:
        _hash_cache[path] = (st.st_size, st.st_mtime_ns, digest)
    return digest


def short(h: str) -> str:
    """把 64 位哈希缩成 '27AF91E2…6F525F84',给人眼核对用。"""
    h = (h or "").upper()
    return f"{h[:8]}…{h[-8:]}" if len(h) >= 16 else h


def zip_kernel_hashes(zip_path: str) -> dict[str, str]:
    """压缩包里内核文件的 SHA-256(按小写文件名)。同名文件出现两次视为可疑,直接报错。"""
    out: dict[str, str] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename.replace("\\", "/")).lower()
            if base not in KERNEL_FILES:
                continue
            if base in out:
                raise ValueError(f"压缩包里有两个 {base},拒绝使用")
            h = hashlib.sha256()
            with zf.open(info, "r") as src:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    h.update(chunk)
            out[base] = h.hexdigest()
    return out


# ---------------------------------------------------------------- 白名单
def entry(name: str, digest: str) -> str:
    return f"{name.lower()}:{digest.lower()}"


def clean_trusted(raw) -> list[str]:
    """用户确认过的内核指纹,格式 'easytier-core.exe:<64 位十六进制>'。"""
    out: list[str] = []
    for x in (raw or []) if isinstance(raw, (list, tuple)) else []:
        if not isinstance(x, str) or ":" not in x:
            continue
        name, _, digest = x.strip().lower().rpartition(":")
        if name in KERNEL_FILES and _HEX64.match(digest):
            e = entry(name, digest)
            if e not in out:
                out.append(e)
    return out[-MAX_TRUSTED:]


def merge_trusted(old, new) -> list[str]:
    return clean_trusted(list(clean_trusted(old)) + list(new or []))


_builtin_cache: dict[str, str] | None = None


def _bundled_zip() -> str | None:
    roots: list[str] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        roots.append(getattr(sys, "_MEIPASS"))
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for r in roots:
        p = os.path.join(r, "assets", "easytier_bundle.zip")
        if os.path.isfile(p):
            return p
    return None


def builtin_pins() -> dict[str, str]:
    """内置白名单 {文件名: 哈希}。

    打包版:只认打包时生成的 miyu/_etpin.py(它编译在签过名的 exe 里)。
    源码运行:没有 _etpin.py 时,直接按仓库里的 assets/easytier_bundle.zip 计算
    (源码目录本身和代码一样可信,能改它的人也能直接改代码)。"""
    global _builtin_cache
    if _builtin_cache is not None:
        return dict(_builtin_cache)
    pins: dict[str, str] = {}
    try:
        from ._etpin import PINS  # type: ignore
        if isinstance(PINS, dict):
            pins = {str(k).lower(): str(v).lower() for k, v in PINS.items()
                    if str(k).lower() in KERNEL_FILES and _HEX64.match(str(v).lower())}
    except Exception:
        pins = {}
    if not pins and not getattr(sys, "frozen", False):
        zp = _bundled_zip()
        if zp:
            try:
                pins = zip_kernel_hashes(zp)
            except Exception:
                pins = {}
    _builtin_cache = pins
    return dict(pins)


def trusted_map(user_trusted=None) -> dict[str, set[str]]:
    """合并内置白名单和用户确认过的指纹 → {文件名: {哈希, ...}}。"""
    out: dict[str, set[str]] = {n: set() for n in KERNEL_FILES}
    for name, digest in builtin_pins().items():
        out[name].add(digest)
    for e in clean_trusted(user_trusted):
        name, _, digest = e.rpartition(":")
        out[name].add(digest)
    return out


# ---------------------------------------------------------------- 校验内核目录
def kernel_files(et_dir: str) -> dict[str, str]:
    """目录里实际存在的内核文件 {小写名: 实际文件名}(Windows 上大小写可能是 Packet.dll)。"""
    out: dict[str, str] = {}
    try:
        names = os.listdir(et_dir)
    except OSError:
        return out
    for n in names:
        low = n.lower()
        if low in KERNEL_FILES and os.path.isfile(os.path.join(et_dir, n)):
            out[low] = n
    return out


def check_kernel(et_dir: str, trusted: dict[str, set[str]], cache: bool = False):
    """返回 (是否全部可信, {小写名: 哈希}, {小写名: 实际文件名}, [不可信的文件])。
    必须有 easytier-core.exe;目录里出现的每个内核文件都得在白名单里。"""
    files = kernel_files(et_dir)
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for low, real in files.items():
        try:
            hashes[low] = sha256_file(os.path.join(et_dir, real), cache=cache)
        except OSError:
            bad.append(low)
            continue
        if hashes[low] not in trusted.get(low, set()):
            bad.append(low)
    ok = CORE in hashes and not bad
    return ok, hashes, files, bad


def assess_zip(zip_path: str, trusted: dict[str, set[str]]):
    """判断一个压缩包:('official' 官方原包 | 'pinned' 文件全在白名单 | 'unknown', 压缩包哈希, 文件哈希)。"""
    zsha = sha256_file(zip_path)
    members = zip_kernel_hashes(zip_path)
    if zsha == OFFICIAL_ZIP_SHA256:
        return "official", zsha, members
    if members.get(CORE) and all(h in trusted.get(n, set()) for n, h in members.items()):
        return "pinned", zsha, members
    return "unknown", zsha, members


# ---------------------------------------------------------------- 受保护目录与启动脚本(Windows)
def protected_root() -> str:
    """C:\\Program Files\\MiYu-EasyTier。用系统 API 取 Program Files 路径,不读环境变量(用户能改)。"""
    base = ""
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x26, None, 0, buf) == 0:  # CSIDL_PROGRAM_FILES
                base = buf.value
        except Exception:
            base = ""
    if not base:
        base = os.environ.get("ProgramFiles") or r"C:\Program Files"
    return os.path.join(base, PROTECTED_DIRNAME)


def system_dir() -> str:
    """C:\\Windows\\System32。用系统 API 取,不读环境变量。"""
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.kernel32.GetSystemDirectoryW(buf, 260):
                return buf.value
        except Exception:
            pass
    return os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32")


def powershell_exe() -> str:
    """系统自带 Windows PowerShell 的绝对路径。提权时绝不能只写 'powershell.exe':
    那样系统可能先在当前目录 / PATH 里找到别人放的同名程序。"""
    return os.path.join(system_dir(), "WindowsPowerShell", "v1.0", "powershell.exe")


def kernel_tag(hashes: dict[str, str]) -> str:
    """受保护目录下的子目录名:由所有内核文件的哈希决定,换了任何一个文件就换目录。"""
    joined = "|".join(f"{n}={hashes[n]}" for n in sorted(hashes))
    return hashlib.sha256(joined.encode("ascii")).hexdigest()[:16]


def _ps(s: str) -> str:
    """PowerShell 单引号字符串字面量。"""
    return "'" + str(s).replace("'", "''") + "'"


def build_launch_script(src_dir: str, files: dict[str, str], hashes: dict[str, str], *, nonce: str,
                        stop_file: str, parent_pid: int, cfg_bytes: bytes, rpc_port: int) -> str:
    """生成在管理员权限下运行的 PowerShell 脚本(Windows PowerShell 5.1 可用)。

    files: {小写名: 源目录里的实际文件名};hashes: {小写名: 期望的 SHA-256}。"""
    if CORE not in hashes or set(files) != set(hashes):
        raise ValueError("内核文件清单不完整")
    for n, h in hashes.items():
        if n not in KERNEL_FILES or not _HEX64.match(h):
            raise ValueError("内核指纹格式不对")
    if not re.fullmatch(r"[0-9a-f]{6,32}", nonce):
        raise ValueError("nonce 格式不对")
    tag = kernel_tag(hashes)
    table = "; ".join(f"{_ps(files[n])}={_ps(hashes[n])}" for n in sorted(files))
    core_real = files[CORE]
    cfg_b64 = base64.b64encode(cfg_bytes).decode("ascii")
    return "\r\n".join([
        "$ErrorActionPreference = 'Stop'",
        f"$src = {_ps(src_dir)}",
        f"$files = @{{ {table} }}",
        f"$tag = {_ps(tag)}",
        f"$nonce = {_ps(nonce)}",
        f"$stopf = {_ps(stop_file)}",
        f"$parentPid = {int(parent_pid)}",
        f"$root = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) {_ps(PROTECTED_DIRNAME)}",
        "$dst = Join-Path $root $tag",
        "$st = Join-Path $root ('status_' + $nonce + '.txt')",
        "function Say($t) { try { [IO.File]::WriteAllText($st, [string]$t) } catch {} }",
        "$icacls = Join-Path ([Environment]::SystemDirectory) 'icacls.exe'",
        "try {",
        "  New-Item -ItemType Directory -Force -Path $dst | Out-Null",
        # 去掉受保护目录上可能被人加过的显式权限,恢复成继承 Program Files(只有管理员能写)
        "  & $icacls $root /reset /T /C /Q | Out-Null",
        "  Get-ChildItem -LiteralPath $root -Directory | Where-Object { $_.Name -ne $tag } |"
        " Remove-Item -Recurse -Force -ErrorAction SilentlyContinue",
        "  Get-ChildItem -LiteralPath $root -File | Remove-Item -Force -ErrorAction SilentlyContinue",
        "  Get-ChildItem -LiteralPath $dst -File | Where-Object { -not $files.ContainsKey($_.Name) } |"
        " Remove-Item -Force -ErrorAction SilentlyContinue",
        "  foreach ($k in @($files.Keys)) {",
        "    $df = Join-Path $dst $k",
        "    $sf = Join-Path $src $k",
        "    if (-not (Test-Path -LiteralPath $df)) {",
        "      Copy-Item -LiteralPath $sf -Destination $df -Force",
        "    } else {",
        "      try { Copy-Item -LiteralPath $sf -Destination $df -Force -ErrorAction Stop } catch {}",
        "    }",
        "  }",
        # 关键:校验的是复制到受保护目录之后的那一份,校验完别人就改不了了
        "  foreach ($k in @($files.Keys)) {",
        "    $h = (Get-FileHash -LiteralPath (Join-Path $dst $k) -Algorithm SHA256).Hash.ToLower()",
        "    if ($h -ne $files[$k]) {",
        "      Remove-Item -LiteralPath $dst -Recurse -Force -ErrorAction SilentlyContinue",
        "      Say ('hash:' + $k); exit 3",
        "    }",
        "  }",
        "  $cfgf = Join-Path $dst ('cfg_' + $nonce + '.toml')",
        # 先建空文件并收紧权限(只有管理员和 SYSTEM 能读),再写入含密码的内容
        "  New-Item -ItemType File -Force -Path $cfgf | Out-Null",
        "  & $icacls $cfgf /inheritance:r /grant:r '*S-1-5-32-544:F' '*S-1-5-18:F' /Q | Out-Null",
        f"  [IO.File]::WriteAllBytes($cfgf, [Convert]::FromBase64String({_ps(cfg_b64)}))",
        f"  $core = Join-Path $dst {_ps(core_real)}",
        f"  $p = Start-Process -FilePath $core -ArgumentList ('-c \"' + $cfgf + '\" --rpc-portal 127.0.0.1:{int(rpc_port)}')"
        " -WorkingDirectory $dst -WindowStyle Hidden -PassThru",
        "  $null = $p.Handle",
        "} catch { Say ('start:' + $_.Exception.Message); exit 4 }",
        "Say 'running'",
        "while (-not $p.HasExited) {",
        "  if (Test-Path -LiteralPath $stopf) { break }",
        "  if (-not (Get-Process -Id $parentPid -ErrorAction SilentlyContinue)) { break }",
        "  Start-Sleep -Milliseconds 400",
        "}",
        "$code = 0",
        "if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } else { $code = $p.ExitCode }",
        "Start-Sleep -Milliseconds 300",
        "Remove-Item -LiteralPath $cfgf -Force -ErrorAction SilentlyContinue",
        "Say ('exit:' + $code)",
        "exit 0",
        "",
    ])


def bootstrap_command(script_path: str, script_bytes: bytes) -> str:
    """提权命令行里的 -EncodedCommand:读脚本 → 核对 SHA-256 → 执行内存里这一份。
    UAC 之后命令行改不了,所以就算有人在磁盘上换掉了脚本,哈希对不上也不会执行。"""
    digest = sha256_bytes(script_bytes)
    ps = (
        "$ErrorActionPreference='Stop';"
        f"try{{$b=[IO.File]::ReadAllBytes({_ps(script_path)})}}catch{{exit 9}};"
        "$h=-join([Security.Cryptography.SHA256]::Create().ComputeHash($b)|ForEach-Object{$_.ToString('x2')});"
        f"if($h -ne '{digest}'){{exit 9}};"
        "& ([ScriptBlock]::Create([Text.Encoding]::UTF8.GetString($b)))"
    )
    return base64.b64encode(ps.encode("utf-16-le")).decode("ascii")


def powershell_args(encoded: str) -> str:
    return f"-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -EncodedCommand {encoded}"


STATUS_TEXT = {
    "hash": "EasyTier 内核在受保护目录里校验失败(文件可能被替换),已拒绝运行。",
    "start": "EasyTier 内核启动失败",
    "exit": "EasyTier 内核已退出",
}


def read_status(root: str, nonce: str) -> str:
    try:
        with open(os.path.join(root, f"status_{nonce}.txt"), "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()[:300]
    except OSError:
        return ""
