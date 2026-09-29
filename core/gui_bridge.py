"""Cầu nối để gọi hàm của GUI thread từ thread nền.

Qt yêu cầu mọi thao tác widget phải nằm trên GUI thread. Signal của một QObject
sống ở GUI thread sẽ tự động dùng queued connection khi được emit từ thread
khác — đó là cách chuẩn để "đóng gói" một hàm bất kỳ rồi đưa về GUI thread.

    from core.gui_bridge import init_bridge, call_on_gui

    init_bridge()                      # gọi 1 lần trong GUI thread
    ...
    call_on_gui(lambda: self.model.reload())   # gọi được từ thread nền
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class _Bridge(QObject):
    # PySide6 dùng `Signal` (đã tự cài đặt theo metaclass của QObject),
    # không có `pyqtSignal` như PyQt.
    called = Signal(object)


_bridge: _Bridge | None = None


def init_bridge() -> None:
    """Khởi tạo. Bắt buộc gọi trên GUI thread, trước khi tạo cửa sổ."""
    global _bridge
    if _bridge is None:
        _bridge = _Bridge()


def call_on_gui(fn) -> None:
    """Chạy `fn()` trên GUI thread. Nếu chưa init thì bỏ qua."""
    if _bridge is not None:
        _bridge.called.emit(fn)
