"""极简 PySide6 替身:只用于在没有 Qt 的环境里跑界面逻辑测试。"""


class _V(int):
    """万能值:可当 0 用,可取任意属性、可调用,用来顶替枚举和不关心的返回值。"""
    def __new__(cls, v=0):
        return int.__new__(cls, v)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _V(0)

    def __call__(self, *a, **k):
        return _V(0)

    def __iter__(self):
        return iter(())


def _fn(*a, **k):
    return _V(0)


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _V(0)


class _Bound:
    def __init__(self):
        self.slots = []

    def connect(self, fn):
        self.slots.append(fn)

    def emit(self, *a):
        for s in list(self.slots):
            s(*a)


class Signal:
    def __init__(self, *types):
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        key = "_sig_" + self.name
        d = obj.__dict__
        if key not in d:
            d[key] = _Bound()
        return d[key]


class _Obj(metaclass=_Meta):
    def __init__(self, *a, **k):
        pass

    # 几何类型(QPointF 之类)在真 Qt 里能做加减乘除和取负,替身也要能算(结果是什么不重要)
    def __neg__(self):
        return self

    def __add__(self, other):
        return self

    __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __add__

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        # Qt 的方法都是驼峰命名(raise_ 这种只在末尾带下划线)。带下划线的名字一定是程序自己的属性,
        # 找不到就该报错,不能默默返回假值 —— 否则"先用后建"这类错误测试发现不了。
        if name.startswith("_") or "_" in name.rstrip("_"):
            raise AttributeError(f"{type(self).__name__} 没有属性 {name}")
        return _V(0)          # 可调用、可取属性(比如 xxx.finished.connect)
