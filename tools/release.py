"""
密语 · 发布工具(build.bat 自动调用,一般不用手动运行)

  python tools/release.py prepare        准备发布密钥,把公钥写进 miyu/_pubkey.py
  python tools/release.py etpin          核对内置 EasyTier 内核并把各文件 SHA-256 写进 miyu/_etpin.py
  python tools/release.py sign <exe>     给打包好的 exe 加上签名

发布私钥放在你的用户目录:  %USERPROFILE%\\.miyu_release\\key.bin
  · 只有拿着这个文件的人能发布"局域网自动更新"会接受的新版。
  · 请备份它。丢了的话,以后打包的新版别人的软件不会自动接受,只能再手动发一次 exe。
  · 不要把它发给别人。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization                              # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_DIR = os.environ.get("MIYU_RELEASE_DIR") or os.path.join(os.path.expanduser("~"), ".miyu_release")
KEY_FILE = os.path.join(KEY_DIR, "key.bin")


def load_key(create: bool = True) -> Ed25519PrivateKey:
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return Ed25519PrivateKey.from_private_bytes(f.read())
    if not create:
        raise SystemExit("没有找到发布密钥: " + KEY_FILE)
    os.makedirs(KEY_DIR, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    with open(KEY_FILE, "wb") as f:
        f.write(raw)
    print("已生成新的发布密钥(请备份):", KEY_FILE)
    return key


def prepare() -> None:
    key = load_key()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    with open(os.path.join(ROOT, "miyu", "_pubkey.py"), "w", encoding="utf-8") as f:
        f.write('"""发布公钥(build.bat 自动生成,不要手改)。"""\nRELEASE_PUBKEY = "%s"\n' % pub)
    print("发布公钥已写入 miyu/_pubkey.py")


def _download_official(G) -> bytes:
    """下载官方 EasyTier 发行包,整包哈希必须等于 etguard.OFFICIAL_ZIP_SHA256。"""
    import urllib.request
    req = urllib.request.Request(G.OFFICIAL_ZIP_URL, headers={"User-Agent": "MiYu-Release-Tool"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    if G.sha256_bytes(data) != G.OFFICIAL_ZIP_SHA256:
        raise RuntimeError("下载到的官方包指纹不对(" + G.sha256_bytes(data) + ")")
    return data


def etpin() -> None:
    """核对 assets/easytier_bundle.zip,生成 miyu/_etpin.py(内置内核指纹白名单)。

    · 内置包和官方 easytier-windows-x86_64-v<PINNED_VERSION>.zip 一模一样 → 直接通过;
    · 不一样(比如你自己重新压缩过)→ 联网下载官方包,逐文件比对 SHA-256,有任何不同就打包失败;
      连不上网时同样失败(设置环境变量 MIYU_ETPIN_OFFLINE=1 可以跳过联网核对,只按内置包生成);
    · etguard.EXPECTED_BUNDLE_SHA256 不为空时,内置包哈希必须等于它;
    · 确实要用改过的内核:设置 MIYU_ETPIN_ALLOW_CUSTOM=1。
    没有内置包时写一个空白名单(跨网联机会提示下载官方校验版)。"""
    import tempfile

    from miyu import etguard as G
    bundle = os.path.join(ROOT, "assets", "easytier_bundle.zip")
    out = os.path.join(ROOT, "miyu", "_etpin.py")
    head = '"""内置 EasyTier 内核指纹白名单(build.bat 调用 tools/release.py etpin 自动生成,不要手改)。"""\n'
    if not os.path.isfile(bundle):
        with open(out, "w", encoding="utf-8") as f:
            f.write(head + 'VERSION = ""\nBUNDLE_SHA256 = ""\nPINS = {}\n')
        print("没有 assets/easytier_bundle.zip:已写入空白名单,跨网联机需要用户自行下载官方校验版内核")
        return
    zsha = G.sha256_file(bundle)
    pins = G.zip_kernel_hashes(bundle)
    print(f"内置 EasyTier 包 SHA-256: {zsha}")
    if G.CORE not in pins:
        raise SystemExit("内置 easytier_bundle.zip 里没有 easytier-core.exe")
    if G.EXPECTED_BUNDLE_SHA256 and zsha != G.EXPECTED_BUNDLE_SHA256.lower():
        raise SystemExit("内置 easytier_bundle.zip 和 miyu/etguard.py 里 EXPECTED_BUNDLE_SHA256 锁定的不一致,已停止打包")
    allow_custom = os.environ.get("MIYU_ETPIN_ALLOW_CUSTOM") == "1"
    if zsha == G.OFFICIAL_ZIP_SHA256:
        print(f"✓ 与官方 {G.OFFICIAL_ZIP_NAME} 完全一致")
    elif os.environ.get("MIYU_ETPIN_OFFLINE") == "1":
        print("⚠ 已跳过联网核对(MIYU_ETPIN_OFFLINE=1),按内置包生成白名单")
    else:
        print(f"内置包不是官方原始 zip,正在下载官方 {G.OFFICIAL_ZIP_NAME} 逐文件核对……")
        try:
            data = _download_official(G)
        except Exception as e:
            raise SystemExit(f"无法下载官方包做核对:{e}\n可以设置 MIYU_ETPIN_OFFLINE=1 跳过联网核对后重新打包")
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "official.zip")
            with open(zp, "wb") as f:
                f.write(data)
            official = G.zip_kernel_hashes(zp)
        diff = [n for n, h in pins.items() if official.get(n) != h]
        if diff and not allow_custom:
            raise SystemExit("内置包里这些文件和官方 v" + G.PINNED_VERSION + " 不一致:" + ", ".join(diff)
                             + "\n如果确定要用改过的内核,设置 MIYU_ETPIN_ALLOW_CUSTOM=1 后重新打包")
        print("✓ 内置包里的内核文件与官方 v" + G.PINNED_VERSION + " 逐个一致" if not diff
              else "⚠ 存在与官方不同的文件(已按 MIYU_ETPIN_ALLOW_CUSTOM=1 放行):" + ", ".join(diff))
        if not G.EXPECTED_BUNDLE_SHA256:
            print(f"提示:可以把 EXPECTED_BUNDLE_SHA256 = \"{zsha}\" 写进 miyu/etguard.py 锁定这份内置包")
    lines = [head, f'VERSION = "{G.PINNED_VERSION}"', f'BUNDLE_SHA256 = "{zsha}"', "PINS = {"]
    lines += [f'    "{n}": "{h}",' for n, h in sorted(pins.items())]
    lines.append("}")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    for n, h in sorted(pins.items()):
        print(f"  {n:<20} {h}")
    print("内置内核指纹已写入 miyu/_etpin.py")


def sign(path: str) -> None:
    from miyu import update
    from miyu.version import VERSION
    key = load_key(create=False)
    update.sign_file(path, VERSION, key)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    if update.read_release(path, pub) != VERSION:
        raise SystemExit("签名校验没通过")
    print(f"已签名: {path}  (版本 {VERSION})")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "prepare":
        prepare()
    elif len(sys.argv) >= 2 and sys.argv[1] == "etpin":
        etpin()
    elif len(sys.argv) >= 3 and sys.argv[1] == "sign":
        sign(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
