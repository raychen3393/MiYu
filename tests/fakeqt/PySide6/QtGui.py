from ._base import _V, _Obj, Signal  # noqa


class QFontMetrics(_Obj):
    def horizontalAdvance(self, s):
        return len(s) * 8

    def lineSpacing(self):
        return 16

    def elidedText(self, s, mode, w):
        return s


class QAction(_Obj):
    triggered = Signal(bool)

    def __init__(self, *a, **k):
        self._checked = False
        self._text = next((x for x in a if isinstance(x, str)), "")
        self._enabled = True

    def text(self):
        return self._text

    def setText(self, t):
        self._text = t

    def setEnabled(self, v):
        self._enabled = bool(v)

    def isEnabled(self):
        return self._enabled

    def setChecked(self, v):
        self._checked = bool(v)

    def isChecked(self):
        return self._checked

    def setCheckable(self, v):
        self._checkable = bool(v)

    def trigger(self):                       # 和真 Qt 一样:可勾选的先翻转,再发 triggered(勾选状态)
        if not self._enabled:
            return
        if getattr(self, "_checkable", False):
            self._checked = not self._checked
        self.triggered.emit(self._checked)


class QShortcut(_Obj):
    activated = Signal()


class QFont(_Obj): pass
class QColor(_Obj): pass
class QBrush(_Obj): pass
class QIcon(_Obj): pass
class QPixmap(_Obj): pass
class QPainter(_Obj): pass
class QPainterPath(_Obj): pass
class QLinearGradient(_Obj): pass
class QPalette(_Obj): pass
class QKeySequence(_Obj): pass
class QTextOption(_Obj): pass


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    cls = type(name, (_Obj,), {})
    globals()[name] = cls
    return cls
