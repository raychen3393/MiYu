from ._base import _V, _Obj, Signal  # noqa
from .QtCore import QObject
from .QtGui import QFontMetrics


class QWidget(QObject):
    # 没有父窗口就被显示出来的标签(在真 Qt 里会变成一个独立的小窗口闪一下)。测试会检查它是空的。
    stray = []

    def __init__(self, *a, **k):
        p = k.get("parent", a[0] if a else None)
        self._parent = p if isinstance(p, QWidget) else None
        self._visible = False
        self._min = False
        self._name = ""
        self._enabled = True
        self._title = ""
        self._deleted = False

    def setObjectName(self, n): self._name = n
    def objectName(self): return self._name
    def isVisible(self): return self._visible
    def _check_stray(self):
        if isinstance(self, QLabel) and self._parent is None:
            QWidget.stray.append(getattr(self, "_text", ""))
    def show(self): self._check_stray(); self._visible = True; self._min = False
    def showNormal(self): self.show()
    def showMinimized(self): self._visible = True; self._min = True
    def hide(self): self._visible = False
    def isMinimized(self): return self._min
    def isActiveWindow(self): return False
    def setEnabled(self, v): self._enabled = bool(v)
    def isEnabled(self): return self._enabled
    def setWindowTitle(self, t): self._title = t
    def windowTitle(self): return self._title
    def deleteLater(self): self._deleted = True
    def fontMetrics(self): return QFontMetrics()
    def setVisible(self, v):
        if v:
            self._check_stray()
        self._visible = bool(v)
    def setParent(self, p, *a): self._parent = p if isinstance(p, QWidget) else None
    def parentWidget(self): return self._parent if self._parent is not None else _V(0)
    def setProperty(self, k, v): self.__dict__.setdefault("_props", {})[k] = v
    def property(self, k): return self.__dict__.get("_props", {}).get(k)


class QFrame(QWidget): pass
class QMainWindow(QWidget): pass
class QDialog(QWidget):
    finished = Signal(int)
    def exec(self): return 1
    def accept(self): self._visible = False
    def reject(self): self._visible = False


class QLabel(QFrame):
    def __init__(self, text="", *a, **k):
        super().__init__(*a, **k)
        self._text = text
        self._fixed_w = None
    def text(self): return self._text
    def setText(self, t): self._text = t
    def setFixedWidth(self, w): self._fixed_w = w


class QPlainTextEdit(QFrame):
    textChanged = Signal()
    def __init__(self, *a, **k):
        super().__init__()
        self._text = ""
        self._ph = ""
    def toPlainText(self): return self._text
    def setPlainText(self, t): self._text = t; self.textChanged.emit()
    def clear(self): self._text = ""; self.textChanged.emit()
    def insertPlainText(self, t): self._text += t; self.textChanged.emit()
    def inputMethodEvent(self, e):
        if e.commitString():
            self.insertPlainText(e.commitString())
    def setPlaceholderText(self, t): self._ph = t
    def placeholderText(self): return self._ph


class QLineEdit(QFrame):
    textChanged = Signal(str)
    def __init__(self, text="", *a, **k):
        super().__init__()
        self._text = text
    def text(self): return self._text
    def setText(self, t): self._text = t; self.textChanged.emit(t)


class QCheckBox(QWidget):
    toggled = Signal(bool)
    def __init__(self, *a, **k):
        super().__init__()
        self._c = False
    def setChecked(self, v): self._c = bool(v)
    def isChecked(self): return self._c


class QAbstractButton(QWidget):
    clicked = Signal()
    toggled = Signal(bool)
    def __init__(self, text="", *a, **k):
        super().__init__()
        self._text = text if isinstance(text, str) else ""
        self._checked = False
    def setText(self, t): self._text = t
    def text(self): return self._text
    def setChecked(self, v):
        v = bool(v)
        if v != self._checked:
            self._checked = v
            if not getattr(self, "_blocked", False):
                self.toggled.emit(v)
    def isChecked(self): return self._checked
    def blockSignals(self, b): self._blocked = bool(b)


class QPushButton(QAbstractButton): pass


class QToolButton(QPushButton): pass


class QComboBox(QWidget):
    def __init__(self, *a, **k):
        super().__init__()
        self._items = []
        self._i = 0
    def addItem(self, label, data=None): self._items.append((label, data))
    def setCurrentIndex(self, i): self._i = i
    def currentData(self): return self._items[self._i][1]


class QListWidgetItem(_Obj):
    def __init__(self, text="", *a, **k):
        self._text = text
        self._data = None
    def setData(self, role, v): self._data = v
    def data(self, role): return self._data
    def text(self): return self._text


class QListWidget(QFrame):
    currentItemChanged = Signal(object, object)
    itemDoubleClicked = Signal(object)
    customContextMenuRequested = Signal(object)
    def __init__(self, *a, **k):
        super().__init__()
        self._items = []
        self._cur = None
        self._blocked = False
    def blockSignals(self, b): self._blocked = b
    def clear(self): self._items = []; self._cur = None
    def addItem(self, item): self._items.append(item)
    def count(self): return len(self._items)
    def item(self, i): return self._items[i]
    def setCurrentItem(self, it):
        prev, self._cur = self._cur, it
        if not self._blocked:
            self.currentItemChanged.emit(it, prev)
    def currentItem(self): return self._cur
    def itemAt(self, pos): return None


class _LayoutItem:
    def __init__(self, w): self._w = w
    def widget(self): return self._w
    def layout(self): return None


class QBoxLayout(QObject):
    # 和真 Qt 一样:布局装在某个控件上以后,加进来的控件(包括子布局里的)都归这个控件管
    def __init__(self, parent=None, *a, **k):
        self._items = []
        self._subs = []
        self._owner = parent if isinstance(parent, QWidget) else None
    def _adopt(self, owner):
        self._owner = owner
        for w in self._items:
            if w is not None and owner is not None:
                w._parent = owner
        for l in self._subs:
            l._adopt(owner)
    def addWidget(self, w, *a, **k):
        self._items.append(w)
        if w is not None and self._owner is not None:
            w._parent = self._owner
    def addStretch(self, *a): self._items.append(None)
    def addLayout(self, l, *a):
        self._subs.append(l)
        if self._owner is not None and isinstance(l, QBoxLayout):
            l._adopt(self._owner)
    def count(self): return len(self._items)
    def takeAt(self, i): return _LayoutItem(self._items.pop(i))
    def widgets(self): return [w for w in self._items if w is not None]


class QVBoxLayout(QBoxLayout): pass
class QHBoxLayout(QBoxLayout): pass


class _ScrollBar(QObject):
    rangeChanged = Signal(int, int)
    valueChanged = Signal(int)
    def __init__(self):
        self._v = 0
        self._max = 0
    def value(self): return self._v
    def maximum(self): return self._max
    def setValue(self, v): self._v = v; self.valueChanged.emit(v)


class _Viewport(_Obj):
    def width(self): return 800


class QScrollArea(QFrame):
    def __init__(self, *a, **k):
        super().__init__()
        self._sb = _ScrollBar()
        self._vp = _Viewport()
    def verticalScrollBar(self): return self._sb
    def viewport(self): return self._vp


class QStyledItemDelegate(QObject): pass
class QAbstractItemView(_Obj): pass
class QStyle(_Obj): pass
class QSizePolicy(_Obj): pass


class QMenu(QWidget):
    aboutToShow = Signal()
    def addAction(self, *a, **k):
        from .QtGui import QAction
        if a and isinstance(a[0], QAction):
            act = a[0]
        else:
            act = QAction(next((x for x in a if isinstance(x, str)), ""))
            cb = next((x for x in a if callable(x) and not isinstance(x, str)), None)
            if cb is not None:
                act.triggered.connect(lambda *_: cb())
        self.__dict__.setdefault("_acts", []).append(act)
        return act
    def addMenu(self, m):
        from .QtGui import QAction
        act = QAction(getattr(m, "_title", ""))
        act._menu = m
        self.__dict__.setdefault("_acts", []).append(act)
        return act
    def setTitle(self, t): self._title = t
    def title(self): return getattr(self, "_title", "")
    def clear(self): self.__dict__["_acts"] = []
    def actions(self): return list(self.__dict__.get("_acts", []))


class QMessageBox(QDialog):
    def __init__(self, *a, **k):
        super().__init__()
        self._btns = []
    def addButton(self, *a):
        b = object()
        self._btns.append(b)
        return b
    def clickedButton(self):
        return self._btns[0] if self._btns else None


class QInputDialog(_Obj):
    @staticmethod
    def getText(*a, **k): return ("", False)


class QApplication(QObject):
    alerts = 0
    def __init__(self, *a, **k): pass
    @staticmethod
    def alert(w, ms=0): QApplication.alerts += 1
    @staticmethod
    def clipboard(): return _V(0)
    @staticmethod
    def topLevelWidgets(): return []
    @staticmethod
    def quit(): pass


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    cls = type(name, (_Obj,), {})
    globals()[name] = cls
    return cls
