"""
密语 · 消息提示音
用代码合成一段柔和的双音"叮咚"(类似 Apple 风格的轻提示音),不需要任何声音文件,也不写硬盘。
Windows 上用系统自带的 winsound 播放;其他系统退回到系统默认提示音。
"""
from __future__ import annotations

import io
import math
import struct
import sys
import threading
import time
import wave

RATE = 44100


SOUND_THEMES = [("default", "默认", 1), ("muyu", "木鱼", 4), ("8bit", "游戏机", 8), ("cat", "猫叫", 11)]
SOUND_THEME_IDS = {t[0] for t in SOUND_THEMES}


def _wav(samples: list[float]) -> bytes:
    from array import array
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(array("h", [int(max(-1.0, min(1.0, x)) * 32767) for x in samples]).tobytes())
    return buf.getvalue()


def _square(ph: float) -> float:
    return 1.0 if math.sin(ph) >= 0 else -1.0


def _meow(dur: float, f0: float, f1: float, f2: float, vol: float) -> list[float]:
    """一声"喵":音高先升后降,带几层泛音和一点颤音。"""
    n = int(RATE * dur)
    out, ph = [], 0.0
    for i in range(n):
        u = i / n
        f = (f0 + (f1 - f0) * (u / 0.35)) if u < 0.35 else (f1 + (f2 - f1) * ((u - 0.35) / 0.65))
        f *= 1 + 0.012 * math.sin(2 * math.pi * 28 * i / RATE)
        ph += 2 * math.pi * f / RATE
        env = min(1.0, u / 0.08) * min(1.0, (1 - u) / 0.25)
        v = math.sin(ph) + 0.55 * math.sin(2 * ph) + 0.35 * math.sin(3 * ph) + 0.15 * math.sin(5 * ph)
        out.append(v * env * vol * 0.45)
    return out


def chime_samples(theme: str = "default", volume: float = 0.55) -> list[float]:
    if theme == "muyu":                         # 木鱼:两下"笃、笃"
        n = int(RATE * 0.5)
        out = [0.0] * n
        for start, freq in ((0.0, 560.0), (0.2, 600.0)):
            for i in range(int(start * RATE), n):
                t = i / RATE - start
                env = math.exp(-t * 26) * min(1.0, t / 0.002)
                out[i] += env * (math.sin(2 * math.pi * freq * t) + 0.4 * math.sin(2 * math.pi * freq * 2.42 * t)
                                 * math.exp(-t * 40)) * volume * 0.9
        return out
    if theme == "8bit":                         # 游戏机:两个方波音
        n = int(RATE * 0.42)
        out = []
        for i in range(n):
            t = i / RATE
            f = 988.0 if t < 0.08 else 1319.0
            env = 1.0 if t < 0.08 else max(0.0, 1 - (t - 0.08) / 0.34)
            out.append(_square(2 * math.pi * f * t) * env * volume * 0.32)
        return out
    if theme == "cat":
        return _meow(0.5, 620.0, 980.0, 560.0, volume * 1.5)
    return []


def chime_wav(volume: float = 0.55, theme: str = "default") -> bytes:
    """两个音(C6 → G6),每个都快速起音、指数衰减,带一点泛音,听起来像玻璃轻敲。其它主题见 chime_samples。"""
    themed = chime_samples(theme, volume)
    if themed:
        return _wav(themed)
    dur = 0.55
    notes = ((0.00, 1046.5, 0.50), (0.11, 1568.0, 0.42))
    n = int(RATE * dur)
    frames = bytearray()
    for i in range(n):
        t = i / RATE
        v = 0.0
        for start, freq, amp in notes:
            if t >= start:
                tt = t - start
                env = math.exp(-tt * 7.5) * min(1.0, tt / 0.006)
                v += amp * env * (math.sin(2 * math.pi * freq * tt) + 0.18 * math.sin(4 * math.pi * freq * tt))
        fade = min(1.0, (dur - t) / 0.05)                  # 结尾淡出,避免爆音
        frames += struct.pack("<h", int(max(-1.0, min(1.0, v * fade * volume)) * 32767))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return buf.getvalue()


class Notifier:
    MIN_GAP = 1.2       # 秒,连续来很多消息时不会响成一片

    def __init__(self) -> None:
        self._wav: bytes | None = None
        self._last = 0.0
        self._busy = False
        self.played = 0
        self.theme = "default"
        if sys.platform == "win32":
            threading.Thread(target=self._prepare, name="miyu-sound", daemon=True).start()

    def set_theme(self, theme: str) -> None:
        theme = theme if theme in SOUND_THEME_IDS else "default"
        if theme != self.theme:
            self.theme = theme
            self._wav = None

    def _prepare(self) -> None:
        if self._wav is None:
            self._wav = chime_wav(theme=self.theme)

    def play(self, force: bool = False) -> bool:
        now = time.monotonic()
        if self._busy or (not force and now - self._last < self.MIN_GAP):
            return False
        self._last = now
        self.played += 1
        if sys.platform == "win32":
            threading.Thread(target=self._play_win, name="miyu-sound", daemon=True).start()
        else:
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.beep()
            except Exception:
                pass
        return True

    def _play_win(self) -> None:
        self._busy = True
        try:
            import winsound
            self._prepare()
            # SND_MEMORY 不能和 SND_ASYNC 一起用,所以放在后台线程里同步播放
            winsound.PlaySound(self._wav, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
        except Exception:
            pass
        finally:
            self._busy = False


# ---------------------------------------------------------------- 打字音效
_KIND_SEED = {"char": 1, "space": 2, "enter": 3, "delete": 4}
_KEY_PARAMS = {
    #          机身共振频率  时长   共振衰减  触底时间  音量
    "char":   (360.0,      0.045, 120.0,    0.006,    0.42),
    "space":  (185.0,      0.075, 65.0,     0.009,    0.50),
    "enter":  (155.0,      0.085, 55.0,     0.010,    0.52),
    "delete": (520.0,      0.035, 170.0,    0.005,    0.34),
}


def _themed_key(kind: str, variant: int, theme: str) -> list[float]:
    import random as _r
    rng = _r.Random(_KIND_SEED.get(kind, 1) * 131 + variant * 7 + len(theme))
    if theme == "muyu":                         # 木鱼:一声短促的"笃"
        f = {"char": 640.0, "space": 430.0, "enter": 380.0, "delete": 820.0}.get(kind, 640.0) * rng.uniform(0.96, 1.04)
        n = int(RATE * 0.11)
        out = []
        for i in range(n):
            t = i / RATE
            env = math.exp(-t * 48) * min(1.0, t / 0.0015)
            v = math.sin(2 * math.pi * f * t) + 0.35 * math.sin(2 * math.pi * f * 2.42 * t) * math.exp(-t * 70)
            out.append(v * env * 0.5 * min(1.0, (0.11 - t) / 0.004) * 32767)
        return out
    if theme == "8bit":                         # 游戏机:方波"哔"
        f = {"char": 880.0, "space": 440.0, "enter": 660.0, "delete": 330.0}.get(kind, 880.0)
        f *= (1.0, 1.122, 1.26, 0.891)[variant % 4]
        dur = 0.07 if kind == "enter" else 0.035
        n = int(RATE * dur)
        out = []
        for i in range(n):
            t = i / RATE
            ff = f * (1.5 if kind == "enter" and t > dur / 2 else 1.0)
            out.append(_square(2 * math.pi * ff * t) * 0.16 * min(1.0, (dur - t) / 0.004) * 32767)
        return out
    # 猫叫:普通键是很短的"咪",回车是一声完整的"喵"
    if kind == "enter":
        return [x * 32767 for x in _meow(0.26, 650.0, 1000.0, 600.0, 0.75)]
    base = {"char": 1050.0, "space": 760.0, "delete": 1250.0}.get(kind, 1050.0) * rng.uniform(0.92, 1.08)
    return [x * 32767 for x in _meow(0.07, base, base * 1.25, base * 1.05, 0.55)]


def key_pcm(kind: str = "char", variant: int = 0, theme: str = "default") -> list[float]:
    """合成一声机械键盘声(16 位幅度的浮点列表):
    按下的"咔"(短噪声)+ 键帽触底的第二下 + 机身的低频共振。每个 variant 音高和噪声都略有不同。"""
    if theme in ("muyu", "8bit", "cat"):
        return _themed_key(kind, variant, theme)
    import random as _r
    rng = _r.Random(_KIND_SEED.get(kind, 1) * 101 + variant)
    base, dur, decay, bottom_t, vol = _KEY_PARAMS.get(kind, _KEY_PARAMS["char"])
    f = base * rng.uniform(0.93, 1.07)
    n = int(RATE * dur)
    out = []
    lp1 = lp2 = 0.0
    for i in range(n):
        t = i / RATE
        lp1 = lp1 * 0.35 + rng.uniform(-1, 1) * 0.65
        click = lp1 * math.exp(-t * 900)
        bottom = 0.0
        if t >= bottom_t:
            lp2 = lp2 * 0.5 + rng.uniform(-1, 1) * 0.5
            bottom = lp2 * math.exp(-(t - bottom_t) * 1300) * 0.6
        body = (0.55 * math.sin(2 * math.pi * f * t) * math.exp(-t * decay)
                + 0.18 * math.sin(2 * math.pi * f * 2.7 * t) * math.exp(-t * decay * 1.7))
        if kind == "space" and t >= 0.022:                     # 空格键的稳定杆会多一下轻响
            body += 0.12 * math.sin(2 * math.pi * f * 3.3 * t) * math.exp(-(t - 0.022) * 300)
        fade = min(1.0, (dur - t) / 0.004)
        out.append(max(-1.0, min(1.0, (click * 0.7 + bottom * 0.45 + body) * vol * fade)) * 32767)
    return out


def key_wav(kind: str = "char", variant: int = 0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        from array import array
        w.writeframes(array("h", [int(x) for x in key_pcm(kind, variant)]).tobytes())
    return buf.getvalue()


class _Mixer:
    """常驻的低延迟混音器(Windows waveOut)。
    声卡只打开一次,每 5 毫秒送一小块;几个按键声可以叠在一起播放,不会互相掐断。
    没声音 2 秒后自动关掉声卡,下次有声音再打开。"""
    BLOCK = 220          # 每块 220 个采样 ≈ 5 毫秒
    NBUF = 4             # 排队 4 块 ≈ 20 毫秒延迟
    MAX_VOICES = 10

    def __init__(self) -> None:
        self.voices: list[list] = []
        self.lock = threading.Lock()
        self.alive = False
        self.failed = False

    def play(self, pcm: list[float], gain: float = 1.0) -> bool:
        if self.failed:
            return False
        with self.lock:
            if len(self.voices) >= self.MAX_VOICES:
                self.voices.pop(0)
            self.voices.append([pcm, 0, gain])
            if not self.alive:
                self.alive = True
                threading.Thread(target=self._run, name="miyu-mixer", daemon=True).start()
        return True

    def _mix(self) -> bytes:
        from array import array
        n = self.BLOCK
        out = [0.0] * n
        with self.lock:
            keep = []
            for v in self.voices:
                pcm, pos, gain = v
                for i, x in enumerate(pcm[pos:pos + n]):
                    out[i] += x * gain
                v[1] = pos + n
                if v[1] < len(pcm):
                    keep.append(v)
            self.voices = keep
        return array("h", [int(-32767 if x < -32767 else 32767 if x > 32767 else x) for x in out]).tobytes()

    def _run(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes

            winmm = ctypes.WinDLL("winmm")
            kernel32 = ctypes.WinDLL("kernel32")

            class WAVEFORMATEX(ctypes.Structure):
                _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                            ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                            ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                            ("cbSize", wintypes.WORD)]

            class WAVEHDR(ctypes.Structure):
                pass

            WAVEHDR._fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                                ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
                                ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD),
                                ("lpNext", ctypes.POINTER(WAVEHDR)), ("reserved", ctypes.c_size_t)]
            hwo_t = ctypes.c_void_p
            winmm.waveOutOpen.argtypes = [ctypes.POINTER(hwo_t), wintypes.UINT, ctypes.POINTER(WAVEFORMATEX),
                                          ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
            winmm.waveOutOpen.restype = wintypes.UINT
            for name in ("waveOutPrepareHeader", "waveOutUnprepareHeader", "waveOutWrite"):
                fn = getattr(winmm, name)
                fn.argtypes = [hwo_t, ctypes.POINTER(WAVEHDR), wintypes.UINT]
                fn.restype = wintypes.UINT
            for name in ("waveOutReset", "waveOutClose"):
                getattr(winmm, name).argtypes = [hwo_t]
                getattr(winmm, name).restype = wintypes.UINT
            kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, ctypes.c_wchar_p]
            kernel32.CreateEventW.restype = ctypes.c_void_p
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

            fmt = WAVEFORMATEX(1, 1, RATE, RATE * 2, 2, 16, 0)
            event = kernel32.CreateEventW(None, False, False, None)
            hwo = hwo_t()
            if winmm.waveOutOpen(ctypes.byref(hwo), 0xFFFFFFFF, ctypes.byref(fmt), event or 0, 0, 0x00050000) != 0:
                raise OSError("waveOutOpen 失败")
            size = ctypes.sizeof(WAVEHDR)
            bufs = [ctypes.create_string_buffer(self.BLOCK * 2) for _ in range(self.NBUF)]
            hdrs = [WAVEHDR() for _ in range(self.NBUF)]
            for b, h in zip(bufs, hdrs):
                h.lpData = ctypes.cast(b, ctypes.c_void_p)
                h.dwBufferLength = self.BLOCK * 2
                winmm.waveOutPrepareHeader(hwo, ctypes.byref(h), size)

            def submit(i: int) -> None:
                data = self._mix()
                ctypes.memmove(bufs[i], data, len(data))
                winmm.waveOutWrite(hwo, ctypes.byref(hdrs[i]), size)

            for i in range(self.NBUF):
                submit(i)
            idle_since = time.monotonic()
            while True:
                kernel32.WaitForSingleObject(event, 15)
                for i, h in enumerate(hdrs):
                    if h.dwFlags & 0x1:                       # WHDR_DONE:这块播完了,补下一块
                        submit(i)
                now = time.monotonic()
                with self.lock:
                    if self.voices:
                        idle_since = now
                    elif now - idle_since > 2.0:
                        self.alive = False
                        break
            winmm.waveOutReset(hwo)
            for h in hdrs:
                winmm.waveOutUnprepareHeader(hwo, ctypes.byref(h), size)
            winmm.waveOutClose(hwo)
            if event:
                kernel32.CloseHandle(event)
        except Exception:
            with self.lock:
                self.failed = True
                self.alive = False
                self.voices.clear()


def stone_pcm(variant: int = 0) -> list[float]:
    """五子棋落子声:很短的一声"嗒",像棋子落在木头棋盘上。"""
    import random as _r
    rng = _r.Random(900 + variant)
    n = int(RATE * 0.11)
    f1, f2 = 1180.0 * rng.uniform(0.95, 1.05), 2350.0 * rng.uniform(0.95, 1.05)
    out = []
    for i in range(n):
        t = i / RATE
        body = 0.55 * math.sin(2 * math.pi * f1 * t) * math.exp(-t * 55) + 0.25 * math.sin(2 * math.pi * f2 * t) * math.exp(-t * 90)
        click = rng.uniform(-1, 1) * math.exp(-t * 900) * 0.5
        out.append((body + click) * 0.6)
    return out


_FX_CACHE: dict[str, list[float]] = {}


def fx_pcm(kind: str) -> list[float]:
    """扔东西 / 揍宠物的音效,全部现场合成:
    whack 啪(拖鞋)  splat 噗叽(番茄、蛋、奶油)  boom 砰(炸弹)  puff 噗(雪球、枕头)
    chime 叮(玫瑰、爱心)  bonk 咚(拳头、锤子)  swish 嗖(躲开)  flick 嘣(弹脑门)"""
    if kind in _FX_CACHE:
        return _FX_CACHE[kind]
    import random as _r
    rng = _r.Random(hash(kind) & 0xFFFF)
    out: list[float] = []
    if kind == "whack":
        n = int(RATE * 0.16)
        for i in range(n):
            t = i / RATE
            out.append((rng.uniform(-1, 1) * math.exp(-t * 60) * 0.8 + math.sin(2 * math.pi * 180 * t) * math.exp(-t * 30) * 0.5))
    elif kind == "splat":
        n = int(RATE * 0.28)
        lp = 0.0
        for i in range(n):
            t = i / RATE
            lp += (rng.uniform(-1, 1) - lp) * 0.18                 # 低通的噪声:湿乎乎的一声
            wob = math.sin(2 * math.pi * (140 - t * 200) * t) * math.exp(-t * 18) * 0.35
            out.append(lp * math.exp(-t * 16) * 1.6 + wob)
    elif kind == "boom":
        n = int(RATE * 0.7)
        lp = 0.0
        for i in range(n):
            t = i / RATE
            lp += (rng.uniform(-1, 1) - lp) * 0.08
            out.append(lp * math.exp(-t * 5) * 2.2 + math.sin(2 * math.pi * (70 - t * 40) * t) * math.exp(-t * 6) * 0.7)
    elif kind == "puff":
        n = int(RATE * 0.2)
        lp = 0.0
        for i in range(n):
            t = i / RATE
            lp += (rng.uniform(-1, 1) - lp) * 0.3
            out.append(lp * math.sin(math.pi * min(1.0, t / 0.2)) * 0.9)
    elif kind == "chime":
        n = int(RATE * 0.6)
        for i in range(n):
            t = i / RATE
            v = sum(a * math.sin(2 * math.pi * f * t) * math.exp(-t * d) for f, a, d in
                    ((1046.5, 0.35, 5), (1568.0, 0.25, 7), (2093.0, 0.15, 9)))
            if t > 0.08:
                v += 0.3 * math.sin(2 * math.pi * 1318.5 * (t - 0.08)) * math.exp(-(t - 0.08) * 6)
            out.append(v)
    elif kind == "bonk":
        n = int(RATE * 0.22)
        for i in range(n):
            t = i / RATE
            f = 320 * math.exp(-t * 9) + 90
            out.append(math.sin(2 * math.pi * f * t) * math.exp(-t * 14) * 0.9 + rng.uniform(-1, 1) * math.exp(-t * 300) * 0.4)
    elif kind == "swish":
        n = int(RATE * 0.22)
        lp = 0.0
        for i in range(n):
            t = i / RATE
            k = 0.05 + 0.5 * (t / 0.22)
            lp += (rng.uniform(-1, 1) - lp) * k
            out.append(lp * math.sin(math.pi * t / 0.22) * 0.8)
    elif kind == "flick":
        n = int(RATE * 0.18)
        for i in range(n):
            t = i / RATE
            out.append(math.sin(2 * math.pi * (900 - t * 3000) * t) * math.exp(-t * 25) * 0.6)
    peak = max((abs(v) for v in out), default=1.0) or 1.0
    out = [v / peak * 0.7 for v in out]
    _FX_CACHE[kind] = out
    return out


class KeySound:
    """打字音效(默认关闭)。每个按键立即出声,快速连打时声音会叠在一起,不会掐断或丢失。"""
    VARIANTS = 4

    def __init__(self) -> None:
        self._pcm: dict[str, list] = {}
        self._mixer = _Mixer() if sys.platform == "win32" else None
        self._fallback: dict[str, bytes] = {}
        self._last = 0.0
        self.played = 0
        self.theme = "default"

    def set_theme(self, theme: str) -> None:
        theme = theme if theme in SOUND_THEME_IDS else "default"
        if theme != self.theme:
            self.theme = theme
            self._pcm = {}
            self._fallback = {}

    def prepare(self) -> None:
        """提前合成好所有声音(开启音效时在后台调用),第一下按键就不会卡。"""
        for kind in _KEY_PARAMS:
            self._variants(kind)

    def _variants(self, kind: str) -> list:
        v = self._pcm.get(kind)
        if v is None:
            v = self._pcm[kind] = [key_pcm(kind, i, self.theme) for i in range(self.VARIANTS)]
        return v

    def play(self, kind: str = "char") -> bool:
        import random as _r
        now = time.monotonic()
        if now - self._last < 0.012:          # 只过滤同一次按键被重复上报
            return False
        self._last = now
        self.played += 1
        if self._mixer is None:
            return True
        kind = kind if kind in _KEY_PARAMS else "char"
        pcm = _r.choice(self._variants(kind))
        if not self._mixer.play(pcm, _r.uniform(0.82, 1.0)):
            self._play_fallback(kind)
        return True

    def play_pcm(self, pcm: list[float], gain: float = 1.0) -> bool:
        """直接播放一段合成好的声音(五子棋落子声等),和打字声共用低延迟混音器。"""
        if self._mixer is None:
            return False
        return self._mixer.play(pcm, gain)

    def _play_fallback(self, kind: str) -> None:
        """混音器不可用时退回 PlaySound(异步,内存里的声音一直留着,不会被回收)。"""
        try:
            import ctypes
            data = self._fallback.get(kind)
            if data is None:
                data = self._fallback[kind] = key_wav(kind)
            ctypes.windll.winmm.PlaySoundW(ctypes.c_char_p(data), None, 0x0004 | 0x0001 | 0x0002)
        except Exception:
            pass


# ---------------------------------------------------------------- 白噪音 / 环境音
AMBIENT = [("rain", "雨声"), ("fire", "篝火"), ("waves", "海浪")]
AMBIENT_IDS = {a[0] for a in AMBIENT}
AMBIENT_RATE = 22050
AMBIENT_SECS = 10.0


def ambient_pcm(kind: str, secs: float = AMBIENT_SECS, seed: int = 7) -> list[float]:
    """合成一段可以无缝循环的环境音(-1~1 的浮点)。全部由噪声算出来,不需要声音文件。"""
    import random as _r
    rng = _r.Random(seed + len(kind))
    rate = AMBIENT_RATE
    n = int(rate * secs)
    fade = int(rate * 0.6)
    total = n + fade
    out = [0.0] * total
    if kind == "fire":                          # 低沉的呼呼声 + 噼啪
        brown = lp = crack = 0.0
        for i in range(total):
            w = rng.uniform(-1, 1)
            brown = brown * 0.995 + w * 0.06
            lp = lp * 0.9 + w * 0.1
            if rng.random() < 0.0009:
                crack = rng.uniform(0.25, 1.0)
            crack *= 0.985
            out[i] = brown * 0.9 + lp * 0.05 + rng.uniform(-1, 1) * crack * 0.5
    elif kind == "waves":                       # 一涨一落:5 秒一个浪,正好循环
        lp1 = lp2 = 0.0
        for i in range(total):
            w = rng.uniform(-1, 1)
            lp1 = lp1 * 0.86 + w * 0.14
            lp2 = lp2 * 0.97 + w * 0.03
            env = 0.12 + 0.88 * math.sin(math.pi * (i / rate) / 5.0) ** 2
            out[i] = (lp1 * 0.75 + lp2 * 1.4) * env
    else:                                       # 雨:沙沙的底噪 + 零星的雨点
        lp = drop = 0.0
        for i in range(total):
            w = rng.uniform(-1, 1)
            lp = lp * 0.55 + w * 0.45
            if rng.random() < 0.003:
                drop = rng.uniform(0.3, 1.0)
            drop *= 0.93
            out[i] = (w - lp) * 0.34 + lp * 0.12 + rng.uniform(-1, 1) * drop * 0.3
    for i in range(fade):                       # 尾巴和开头交叉淡化 → 循环处听不出接缝
        k = i / fade
        out[i] = out[i] * k + out[n + i] * (1 - k)
    out = out[:n]
    peak = max(1e-6, max(abs(x) for x in out))
    return [x / peak * 0.8 for x in out]


class Ambient:
    """循环播放环境音。Windows 上单独开一个 waveOut,用声卡自带的循环功能,不占 CPU。"""

    def __init__(self) -> None:
        self.kind: str | None = None
        self.volume = 0.5
        self._cache: dict[str, list[float]] = {}
        self._stop: threading.Event | None = None
        self.failed = False

    def play(self, kind: str, volume: float | None = None) -> bool:
        if kind not in AMBIENT_IDS:
            return False
        if volume is not None:
            self.volume = max(0.05, min(1.0, volume))
        self.stop()
        self.kind = kind
        self._stop = threading.Event()
        if sys.platform == "win32":
            threading.Thread(target=self._run, args=(kind, self.volume, self._stop), name="miyu-ambient",
                             daemon=True).start()
        return True

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
            self._stop = None
        self.kind = None

    def _run(self, kind: str, volume: float, stop: threading.Event) -> None:
        try:
            pcm = self._cache.get(kind)
            if pcm is None:
                pcm = self._cache[kind] = ambient_pcm(kind)
            if stop.is_set():
                return
            import ctypes
            from array import array
            from ctypes import wintypes
            data = array("h", [int(x * volume * 30000) for x in pcm]).tobytes()
            winmm = ctypes.WinDLL("winmm")

            class WAVEFORMATEX(ctypes.Structure):
                _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                            ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                            ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                            ("cbSize", wintypes.WORD)]

            class WAVEHDR(ctypes.Structure):
                _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", wintypes.DWORD),
                            ("dwBytesRecorded", wintypes.DWORD), ("dwUser", ctypes.c_size_t),
                            ("dwFlags", wintypes.DWORD), ("dwLoops", wintypes.DWORD),
                            ("lpNext", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]
            hwo_t = ctypes.c_void_p
            winmm.waveOutOpen.argtypes = [ctypes.POINTER(hwo_t), wintypes.UINT, ctypes.POINTER(WAVEFORMATEX),
                                          ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
            for name in ("waveOutPrepareHeader", "waveOutUnprepareHeader", "waveOutWrite"):
                getattr(winmm, name).argtypes = [hwo_t, ctypes.POINTER(WAVEHDR), wintypes.UINT]
            for name in ("waveOutReset", "waveOutClose"):
                getattr(winmm, name).argtypes = [hwo_t]
            fmt = WAVEFORMATEX(1, 1, AMBIENT_RATE, AMBIENT_RATE * 2, 2, 16, 0)
            hwo = hwo_t()
            if winmm.waveOutOpen(ctypes.byref(hwo), 0xFFFFFFFF, ctypes.byref(fmt), 0, 0, 0) != 0:
                raise OSError("waveOutOpen 失败")
            buf = ctypes.create_string_buffer(data, len(data))
            hdr = WAVEHDR()
            hdr.lpData = ctypes.cast(buf, ctypes.c_void_p)
            hdr.dwBufferLength = len(data)
            hdr.dwFlags = 0x4 | 0x8                    # WHDR_BEGINLOOP | WHDR_ENDLOOP
            hdr.dwLoops = 0xFFFFFFFF
            size = ctypes.sizeof(WAVEHDR)
            winmm.waveOutPrepareHeader(hwo, ctypes.byref(hdr), size)
            hdr.dwFlags |= 0x4 | 0x8
            winmm.waveOutWrite(hwo, ctypes.byref(hdr), size)
            stop.wait()
            winmm.waveOutReset(hwo)
            winmm.waveOutUnprepareHeader(hwo, ctypes.byref(hdr), size)
            winmm.waveOutClose(hwo)
        except Exception:
            self.failed = True
