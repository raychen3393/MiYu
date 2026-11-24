from ._base import _V, _Obj, Signal, _Bound  # noqa

Qt = _V(0)


class QObject(_Obj):
    def __init__(self, parent=None, *a, **k):
        pass


class QTimer(QObject):
    timeout = Signal()
    pending = []

    def start(self, *a):
        self.active = True

    def stop(self):
        self.active = False

    @staticmethod
    def singleShot(ms, fn):
        QTimer.pending.append(fn)

    @staticmethod
    def run_pending():
        while QTimer.pending:
            QTimer.pending.pop(0)()


class QRect(_Obj):
    pass


class QRectF(_Obj):
    pass


class QSize(_Obj):
    pass


class QTranslator(QObject):
    def load(self, *a):
        return False


class QLibraryInfo(_Obj):
    pass


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    cls = type(name, (_Obj,), {})
    globals()[name] = cls
    return cls
