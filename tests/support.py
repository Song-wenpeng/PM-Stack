"""Isolated application paths and one Qt application per test process.

Import before application modules: review paths are resolved at import time.
Never destroy and recreate QApplication between tests; native Qt resources may
still be retained by test tracebacks or queued deferred-delete events.
"""

import atexit
import os
from pathlib import Path
import tempfile

_sandbox = tempfile.TemporaryDirectory(prefix="pm-stack-tests-")
DATA_ROOT = Path(_sandbox.name).resolve()
_original_env = {key: os.environ.get(key) for key in
                 ("LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP", "QT_QPA_PLATFORM")}
_original_tempdir = tempfile.tempdir
for key in ("LOCALAPPDATA", "USERPROFILE", "TEMP", "TMP"):
    os.environ[key] = str(DATA_ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
tempfile.tempdir = str(DATA_ROOT)
_app = None


def qt_app():
    """Keep a strong reference until process shutdown, even after a failed test."""
    global _app
    from PyQt6.QtWidgets import QApplication
    if _app is None:
        _app = QApplication.instance() or QApplication([])
        _app.setQuitOnLastWindowClosed(False)
    return _app


def cleanup_qt_widgets():
    """Release windows, bridge resources and deferred deletes before the next test."""
    if _app is None:
        return
    from PyQt6 import sip
    from PyQt6.QtCore import QCoreApplication, QEvent, QTimer
    from core.reviews.extension_panel import ExtensionPanel
    for widget in list(_app.topLevelWidgets()):
        if sip.isdeleted(widget):
            continue
        for panel in widget.findChildren(ExtensionPanel):
            panel.disconnect()
        for timer in widget.findChildren(QTimer):
            timer.stop()
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _cleanup():
    try:
        cleanup_qt_widgets()
    finally:
        tempfile.tempdir = _original_tempdir
        for key, value in _original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _sandbox.cleanup()


atexit.register(_cleanup)
