"""
密语 · Python 新版本兼容

Python 3.15 起,标准库的 concurrent.futures 用"延迟导入"提供 ThreadPoolExecutor / ProcessPoolExecutor。
用 PyInstaller 打包成 exe 后,这两个名字可能变成一个不能调用、也不能拿来做类型检查的占位对象
('lazy_import' object is not callable / isinstance() arg 2 must be a type)。
连 asyncio 自己的代码都会被它卡住,所以启动时直接从子模块取出真正的类,放回原处。
"""
from __future__ import annotations


def fix_lazy_imports() -> list[str]:
    """把 concurrent.futures 里的占位对象换成真正的类。返回修好了哪些名字(测试用)。可以重复调用。"""
    fixed = []
    try:
        import concurrent.futures as cf
        from concurrent.futures.thread import ThreadPoolExecutor
    except Exception:
        return fixed
    targets = {"ThreadPoolExecutor": ThreadPoolExecutor}
    try:
        from concurrent.futures.process import ProcessPoolExecutor
        targets["ProcessPoolExecutor"] = ProcessPoolExecutor
    except Exception:                       # 有些环境没有多进程支持,不影响聊天
        pass
    for name, real in targets.items():
        cur = cf.__dict__.get(name)
        if cur is not real:
            try:
                setattr(cf, name, real)
                fixed.append(name)
            except Exception:
                pass
    return fixed


fix_lazy_imports()
