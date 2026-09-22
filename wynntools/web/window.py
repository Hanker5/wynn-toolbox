"""The app window: the web app in a borderless native window (pywebview).

The page draws its own title bar (drag area, minimize, maximize, close) and
calls `WindowApi` through `window.pywebview.api`. Borderless windows can't be
moved or resized by the window manager, so:

- on Qt (Linux) the page asks for a native move/resize (`startSystemMove`,
  `startSystemResize`), which also works on Wayland, where a program may not
  position its own windows;
- elsewhere (Windows' WebView2, macOS) pywebview moves the window by its drag
  region and the page resizes it from its edges with `geometry`/`set_geometry`.

The window's size and position are kept in settings.json (`window`).
"""
import logging
from pathlib import Path

from .. import settings as settings_mod

log = logging.getLogger(__name__)

TITLE = "Wynn Toolbox"
DEFAULT_SIZE = (1400, 900)
MIN_SIZE = (900, 600)
EDGES = ("n", "s", "e", "w", "ne", "nw", "se", "sw")

_current = None          # the open window's WindowApi, for focus() from the server


def available():
    """True if pywebview and a GUI backend can be imported (never raises)."""
    try:
        import webview  # noqa: F401
        return True
    except Exception:          # a missing system library raises all sorts
        return False


def focus():
    """Bring the open window to the front. False if there is none."""
    if _current is None:
        return False
    _current.focus()
    return True


def close():
    """Close the open window (the app then exits). False if there is none."""
    if _current is None:
        return False
    _current.close()
    return True


def _report(ok, what):
    if not ok:
        log.warning("the window system refused to %s the window", what)


class _QtCalls:
    """Runs callables on Qt's GUI thread (js_api calls arrive on worker threads)."""

    def __init__(self):
        from qtpy.QtCore import QObject, Signal, Slot
        from qtpy.QtWidgets import QApplication

        class Invoker(QObject):
            call = Signal(object)

            @Slot(object)
            def run(self, fn):
                fn()

        self.invoker = Invoker()
        self.invoker.moveToThread(QApplication.instance().thread())
        # A slot of the invoker, not a lambda: PyQt runs a lambda in the thread
        # that connected it (a worker), where window moves silently do nothing.
        self.invoker.call.connect(self.invoker.run)

    def __call__(self, fn):
        self.invoker.call.emit(fn)


class WindowApi:
    """What the page's title bar can do. Every public method is callable from JS."""

    def __init__(self):
        self._window = None
        self._maximized = False
        self._qt = None

    # ---------------------------------------------------------------- setup
    def _attach(self, window):
        self._window = window
        window.events.maximized += lambda *_: setattr(self, "_maximized", True)
        window.events.restored += lambda *_: setattr(self, "_maximized", False)

    def _qt_view(self):
        try:
            from webview.platforms.qt import BrowserView
        except Exception:
            return None
        return BrowserView.instances.get(self._window.uid)

    def _native(self, fn):
        """Run fn(qt_window_handle) on the GUI thread; False if not on Qt."""
        view = self._qt_view()
        if view is None:
            return False
        if self._qt is None:
            self._qt = _QtCalls()
        self._qt(lambda: fn(view))
        return True

    # ---------------------------------------------------------------- for the page
    def native_moves(self):
        """True if start_move/start_resize work (Qt); otherwise the page falls
        back to pywebview's drag region and geometry()/set_geometry()."""
        return self._qt_view() is not None

    def start_move(self):
        return self._native(lambda v: _report(v.windowHandle().startSystemMove(), "move"))

    def start_resize(self, edge):
        if edge not in EDGES:
            return False
        from qtpy.QtCore import Qt
        bits = {"n": Qt.Edge.TopEdge, "s": Qt.Edge.BottomEdge,
                "e": Qt.Edge.RightEdge, "w": Qt.Edge.LeftEdge}
        edges = bits[edge[0]]
        for ch in edge[1:]:
            edges |= bits[ch]
        return self._native(lambda v: _report(v.windowHandle().startSystemResize(edges),
                                              "resize"))

    def geometry(self):
        w = self._window
        return {"x": w.x, "y": w.y, "width": w.width, "height": w.height}

    def set_geometry(self, x, y, width, height):
        w = self._window
        width, height = max(int(width), MIN_SIZE[0]), max(int(height), MIN_SIZE[1])
        if (int(x), int(y)) != (w.x, w.y):
            w.move(int(x), int(y))
        w.resize(width, height)

    def minimize(self):
        self._window.minimize()

    def toggle_maximize(self):
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized
        return self._maximized

    def is_maximized(self):
        return self._maximized

    def toggle_fullscreen(self):
        self._window.toggle_fullscreen()

    def focus(self):
        w = self._window
        if w is None:
            return
        if self._maximized:
            w.show()
        else:
            w.restore()             # also un-minimizes, raises and focuses
        self._native(lambda v: (v.raise_(), v.activateWindow()))

    def close(self):
        self._window.destroy()


def _saved_geometry(settings_path):
    g = settings_mod.load(settings_path).get("window") or {}
    try:
        width = max(int(g.get("width", DEFAULT_SIZE[0])), MIN_SIZE[0])
        height = max(int(g.get("height", DEFAULT_SIZE[1])), MIN_SIZE[1])
        x = int(g["x"]) if g.get("x") is not None else None
        y = int(g["y"]) if g.get("y") is not None else None
    except (TypeError, ValueError):
        return {"width": DEFAULT_SIZE[0], "height": DEFAULT_SIZE[1], "x": None, "y": None,
                "maximized": False}
    return {"width": width, "height": height, "x": x, "y": y,
            "maximized": bool(g.get("maximized"))}


def run(url, settings_path, on_close):
    """Open the window and block until it closes (must run on the main thread).
    on_close() runs once the window is gone. Raises if no window could be shown."""
    global _current
    import webview

    # Absolute: `wt serve` passes builds/ relative to the working folder, and Qt
    # WebEngine with a relative storage path stalled the page (blank build list
    # and terminal) for up to minutes at every start.
    settings_path = Path(settings_path).resolve()
    g = _saved_geometry(settings_path)
    api = WindowApi()
    window = webview.create_window(
        TITLE, url, js_api=api, width=g["width"], height=g["height"], x=g["x"], y=g["y"],
        min_size=MIN_SIZE, frameless=True, easy_drag=False, maximized=g["maximized"],
        background_color="#121212", text_select=True)
    api._attach(window)
    api._maximized = g["maximized"]
    last = dict(g)

    def remember(*_):
        # Size and position while not maximized, so "restore" goes back there.
        if not api._maximized:
            last.update(width=window.width, height=window.height, x=window.x, y=window.y)

    def save(*_):
        remember()
        try:
            settings_mod.save({"window": {**last, "maximized": api._maximized}}, settings_path)
        except (OSError, ValueError) as e:
            log.warning("couldn't save the window size: %s", e)

    window.events.resized += remember
    window.events.moved += remember
    window.events.closing += save
    _current = api
    try:
        webview.start(private_mode=False, storage_path=str(settings_path.parent / ".webview"))
    finally:
        _current = None
        on_close()
