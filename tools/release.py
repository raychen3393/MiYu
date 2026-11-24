"""
密语 · 发布工具(build.bat 自动调用,一般不用手动运行)

  python tools/release.py prepare        准备发布密钥,把公钥写进 miyu/_pubkey.py
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
    elif len(sys.argv) >= 3 and sys.argv[1] == "sign":
        sign(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)
