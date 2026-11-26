# -*- mode: python ; coding: utf-8 -*-
"""
密语 MiYu 精简打包配置:
  · 剔除纯 2D/2.5D QPainter 绘制完全用不到的 opengl32sw.dll(~20MB)、QtNetwork/TLS、Direct2D、SVG/TIFF 等冗余二进制
  · 移除不存在的 QtMultimedia 隐藏导入报错，排除 tkinter/unittest 等无关标准库
  · 体积直降 10+ MB，单文件冷启动解压更快
"""

_DROP_BINS = (
    "opengl32sw.dll",
    "qt6network.dll",
    "qt6svg.dll",
    "qdirect2d.dll",
    "qtiff.dll",
    "qsvg.dll",
    "qsvgicon.dll",
    "qicns.dll",
    "qtga.dll",
    "qwbmp.dll",
    "qtuiotouchplugin.dll",
    "qnetworklistmanager.dll",
    "qopensslbackend.dll",
    "qschannelbackend.dll",
    "qcertonlybackend.dll",
)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets", "assets")],
    hiddenimports=[
        "concurrent.futures.thread",
        "miyu.arcade",
        "miyu.pettd",
        "miyu.petpvz",
        "miyu.petmerge",
        "miyu.petpass",
        "miyu.petphoto",
        "miyu.easytier",
        "miyu.etguard",
        "miyu._etpin",      # 打包时由 tools/release.py etpin 生成的内置 EasyTier 内核指纹白名单
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "_tkinter", "unittest", "pydoc", "doctest", "pdb", "xmlrpc",
        "ftplib", "imaplib", "poplib", "smtplib", "nntplib", "telnetlib", "turtle",
        "PySide6.QtNetwork", "PySide6.QtSvg", "PySide6.QtSvgWidgets",
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.QtSql", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtPrintSupport", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    ],
    noarchive=False,
    optimize=0,
)

# 精准剔除未使用的重型 Qt 二进制与非必要插件
a.binaries = [
    item for item in a.binaries
    if not any(item[0].lower().replace("/", "\\").endswith(drop) for drop in _DROP_BINS)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MiYu",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["assets/icon.ico"],
)
