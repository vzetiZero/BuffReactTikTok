"""Style chung cho toàn app — dựa trên bảng quản lý dạng admin.

Màu chủ đạo: xanh navy cho header/đường viền, xanh lá cho trạng thái tốt,
đỏ cho lỗi, cam cho cảnh báo. Nền sáng, chữ nhỏ, mật độ cao để nhìn được
nhiều dòng.
"""

PRIMARY = "#1e5eb8"
PRIMARY_DK = "#164a92"
PRIMARY_LT = "#e8f1fc"
BORDER = "#d3dce6"
BG = "#f4f6f9"
CARD = "#ffffff"

OK = "#1a8a4e"
FAIL = "#c62828"
WARN = "#c77800"
INFO = "#54606e"
MUTED = "#8a95a1"

# Cỡ chữ kiểu webapp: 11px nội dung, 10px chú thích, 9px phụ tốn.
# Dùng px (không pt) để không bị lệch theo DPI từng máy.
FS_BASE = 11
FS_SMALL = 10
FS_TINY = 9
ROW_H = 44

QSS = f"""
QWidget {{
    background: {BG};
    color: #1e2530;
    font-family: "Segoe UI", "Helvetica Neue", "Inter", Arial, sans-serif;
    font-size: {FS_BASE}px;
}}
QMainWindow, QDialog {{ background: {BG}; }}

/* ---------- khung nhóm ---------- */
QGroupBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 3px;
    margin-top: 15px;
    padding-top: 4px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 7px;
    padding: 0 4px;
    color: {PRIMARY};
    font-size: {FS_BASE}px;
}}

/* ---------- tab ---------- */
QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {CARD};
    top: -1px;
}}
QTabBar::tab {{
    background: #e7ecf2;
    color: {INFO};
    border: 1px solid {BORDER};
    border-bottom: none;
    padding: 5px 18px;
    margin-right: 2px;
    font-weight: 600;
    font-size: {FS_BASE}px;
}}
QTabBar::tab:selected {{
    background: {CARD};
    color: {PRIMARY};
    border-top: 2px solid {PRIMARY};
}}
QTabBar::tab:hover:!selected {{ background: #dde4ec; }}

/* ---------- nút ---------- */
QPushButton {{
    background: #fdfefe;
    border: 1px solid #b9c6d4;
    border-radius: 3px;
    padding: 3px 10px;
    color: #1e2530;
    font-size: {FS_BASE}px;
    min-height: 15px;
}}
QPushButton:hover {{ background: #eef4fb; border-color: {PRIMARY}; }}
QPushButton:pressed {{ background: #dbe8f7; }}
QPushButton:disabled {{
    background: #eef1f4; color: #a9b3bd; border-color: #d5dce3;
}}
QPushButton#primary {{
    background: {PRIMARY}; color: #fff; border-color: {PRIMARY_DK};
    font-weight: 700; padding: 4px 16px;
}}
QPushButton#primary:hover {{ background: #2a6fcc; }}
QPushButton#danger {{
    background: {FAIL}; color: #fff; border-color: #a51f1f;
    font-weight: 700; padding: 4px 16px;
}}
QPushButton#danger:hover {{ background: #d93a3a; }}
QPushButton#ghost {{
    background: transparent; border: 1px solid {BORDER}; color: {INFO};
    padding: 2px 8px;
}}
QPushButton#ghost:hover {{ background: {PRIMARY_LT}; color: {PRIMARY}; }}

/* ---------- bảng ---------- */
QTableView {{
    background: {CARD};
    alternate-background-color: #fafbfd;
    border: 1px solid {BORDER};
    gridline-color: #e8edf2;
    selection-background-color: #cfe3f9;
    selection-color: #10233a;
    outline: none;
    font-size: {FS_BASE}px;
}}
QTableView::item {{ padding: 0px 4px; border: 0px; }}
QTableView::item:selected {{ background: #cfe3f9; color: #10233a; }}
QHeaderView {{ background: {PRIMARY}; }}
QHeaderView::section {{
    background: {PRIMARY};
    color: #fff;
    border: none;
    border-right: 1px solid rgba(255,255,255,0.22);
    padding: 4px 6px;
    font-weight: 700;
    font-size: {FS_BASE}px;
}}
QHeaderView::section:hover {{ background: {PRIMARY_DK}; }}
QHeaderView::section:checked {{ background: {PRIMARY_DK}; }}

/* ---------- ô nhập ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox,
QComboBox, QDateTimeEdit {{
    background: #fff;
    border: 1px solid #b9c6d4;
    border-radius: 3px;
    padding: 2px 5px;
    font-size: {FS_BASE}px;
    selection-background-color: {PRIMARY};
    selection-color: #fff;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {PRIMARY};
}}
QLineEdit:read-only, QTextEdit:read-only, QPlainTextEdit:read-only {{
    background: #f2f4f7; color: {INFO};
}}
QComboBox::drop-down {{ border: none; width: 15px; }}
QComboBox QAbstractItemView {{
    background: #fff; border: 1px solid {BORDER};
    selection-background-color: {PRIMARY_LT};
    selection-color: #10233a;
    outline: none;
    font-size: {FS_BASE}px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: #e7ecf2; border: none; width: 13px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{ background: #d3dde8; }}
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: #d3dde8; }}

/* ---------- checkbox ---------- */
QCheckBox {{ spacing: 5px; font-size: {FS_BASE}px; }}
QCheckBox::indicator {{
    width: 12px; height: 12px;
    border: 1px solid #9fb0c0; border-radius: 2px; background: #fff;
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY_DK};
    image: url(:/qt-project.org/styles/commonstyle/images/standardbutton-apply-16.png);
}}

/* ---------- nhật ký ---------- */
QPlainTextEdit#log {{
    background: #1c2530; color: #cfd8e3;
    border: 1px solid #101820;
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: {FS_SMALL}px;
}}

/* ---------- thanh trạng thái ---------- */
QStatusBar {{
    background: #e9eef4;
    border-top: 1px solid {BORDER};
    color: {INFO};
    font-size: {FS_SMALL}px;
}}
QStatusBar::item {{ border: none; }}
QProgressBar {{
    background: #dfe6ee; border: 1px solid {BORDER};
    border-radius: 3px; height: 11px; text-align: center;
    font-size: {FS_TINY}px; color: {INFO};
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 2px; }}

/* ---------- khác ---------- */
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}
QScrollBar:vertical {{
    background: #f0f3f7; width: 9px; margin: 0; border: none;
}}
QScrollBar::handle:vertical {{
    background: #c2cdd9; border-radius: 4px; min-height: 24px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: #a4b2c2; }}
QScrollBar:horizontal {{ background: #f0f3f7; height: 9px; border: none; }}
QScrollBar::handle:horizontal {{
    background: #c2cdd9; border-radius: 4px; min-width: 24px; margin: 2px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QToolTip {{
    background: #1c2530; color: #fff; border: 1px solid #0d141b;
    padding: 3px 5px; font-size: {FS_SMALL}px;
}}
QMenu {{ background: #fff; border: 1px solid {BORDER}; font-size: {FS_BASE}px; }}
QMenu::item {{ padding: 4px 20px; }}
QMenu::item:selected {{ background: {PRIMARY_LT}; color: {PRIMARY}; }}

/* ---------- nhãn theo vai trò ---------- */
QLabel[role="hint"] {{ color: {MUTED}; font-size: {FS_SMALL}px; }}
QLabel[role="ok"] {{ color: {OK}; font-weight: 600; }}
QLabel[role="warn"] {{ color: {WARN}; font-weight: 600; }}
QLabel[role="err"] {{ color: {FAIL}; font-weight: 600; }}
QLabel[role="h1"] {{
    color: {PRIMARY}; font-size: 12px; font-weight: 700;
    border-bottom: 1px solid {BORDER}; padding-bottom: 4px;
}}
QLabel[role="k"] {{ color: {MUTED}; font-size: {FS_SMALL}px; }}
QLabel[role="v"] {{ color: #1e2530; font-size: {FS_BASE}px; }}
QFrame[role="card"] {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 3px;
}}
"""


def ui_font_family() -> str:
    """Font giao diện, chọn theo những font CÓ THẬT trên máy.

    "Segoe UI" là font của Windows, không có trên macOS. Gọi
    `QFont().setFamily("Segoe UI")` trên Mac sẽ âm thầm rơi về font mặc
    định của hệ thống (thường là serif — trông lạc lõng) mà KHÔNG báo lỗi.
    Vì vậy phải dò xem font nào thực sự tồn tại rồi mới dùng.
    """
    from PySide6.QtGui import QFont, QFontDatabase

    try:
        have = set(QFontDatabase.families())
    except Exception:      # pragma: no cover - môi trường lạ
        have = set()
    for name in ("Segoe UI",          # Windows
                 "SF Pro Text",       # macOS (system font)
                 "Helvetica Neue",    # macOS
                 "Inter",             # có thể đã cài
                 "DejaVu Sans",       # Linux
                 "Arial"):            # chắc chắn có ở mọi nơi
        if name in have:
            return name
    # Danh sách rỗng (ví dụ chạy headless/offscreen) thì không có cách nào
    # dò font — trả về rỗng và để Qt tự chọn, thay vì trả tên bịa.
    return QFont().defaultFamily() or ""


def apply(app) -> None:
    """Đặt font mặc định nhỏ trước, rồi áp stylesheet."""
    from PySide6.QtGui import QFont

    f = QFont()
    f.setFamily(ui_font_family())
    f.setPixelSize(FS_BASE)
    app.setFont(f)
    app.setStyleSheet(QSS)
