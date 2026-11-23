"""Thèmes clair et sombre (palette Qt + feuille de style)."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    name: str
    window: str
    panel: str
    chat_bg: str
    text: str
    muted: str
    accent: str
    bubble_in: str
    bubble_out: str
    bubble_border: str
    selection: str
    pill: str
    pill_text: str
    quote_bg: str
    highlight: str
    missing: str
    input_bg: str


LIGHT = Theme(
    name="clair", window="#ffffff", panel="#f4f4f5", chat_bg="#dfe7ee", text="#1b1d1f",
    muted="#707579", accent="#3390ec", bubble_in="#ffffff", bubble_out="#e3f6d5",
    bubble_border="#d5dbe0", selection="#cfe3fb", pill="#8fa3b4", pill_text="#ffffff",
    quote_bg="rgba(51,144,236,0.10)", highlight="#ffe58a", missing="#b3261e", input_bg="#ffffff",
)
DARK = Theme(
    name="sombre", window="#17212b", panel="#0e1621", chat_bg="#0e1621", text="#e6ebef",
    muted="#8596a6", accent="#5eb5f7", bubble_in="#182533", bubble_out="#2b5278",
    bubble_border="#22303e", selection="#2b5278", pill="#1f2f3f", pill_text="#cfd8e0",
    quote_bg="rgba(94,181,247,0.14)", highlight="#7a6a1f", missing="#ff8a80", input_bg="#242f3d",
)

# Couleurs d'avatar inspirées des classes userpic1..8 des exports
USERPIC_COLORS = {
    "userpic1": "#e17076", "userpic2": "#eda86c", "userpic3": "#a695e7", "userpic4": "#7bc862",
    "userpic5": "#6ec9cb", "userpic6": "#65aadd", "userpic7": "#ee7aae", "userpic8": "#faa774",
}
FALLBACK_COLORS = list(USERPIC_COLORS.values())


def sender_color(userpic_class: str | None, name: str | None) -> str:
    if userpic_class in USERPIC_COLORS:
        return USERPIC_COLORS[userpic_class]
    if not name:
        return FALLBACK_COLORS[0]
    return FALLBACK_COLORS[sum(map(ord, name)) % len(FALLBACK_COLORS)]


def theme_for(dark: bool) -> Theme:
    return DARK if dark else LIGHT


def apply_theme(app: QApplication, theme: Theme) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(theme.window))
    pal.setColor(QPalette.WindowText, QColor(theme.text))
    pal.setColor(QPalette.Base, QColor(theme.input_bg))
    pal.setColor(QPalette.AlternateBase, QColor(theme.panel))
    pal.setColor(QPalette.Text, QColor(theme.text))
    pal.setColor(QPalette.Button, QColor(theme.panel))
    pal.setColor(QPalette.ButtonText, QColor(theme.text))
    pal.setColor(QPalette.Highlight, QColor(theme.accent))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor(theme.panel))
    pal.setColor(QPalette.ToolTipText, QColor(theme.text))
    pal.setColor(QPalette.Link, QColor(theme.accent))
    pal.setColor(QPalette.PlaceholderText, QColor(theme.muted))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(theme.muted))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(theme))


def stylesheet(t: Theme) -> str:
    return f"""
QMainWindow, QDialog {{ background: {t.window}; }}
QSplitter::handle {{ background: {t.bubble_border}; }}
#SidePanel {{ background: {t.window}; }}
#ChatHeader {{ background: {t.window}; border-bottom: 1px solid {t.bubble_border}; }}
#ChatTitle {{ font-weight: 600; font-size: 12pt; }}
#Muted, QLabel[muted="true"] {{ color: {t.muted}; }}
#ChatArea, #ChatArea > QWidget > QWidget {{ background: {t.chat_bg}; }}
QLineEdit {{ border: 1px solid {t.bubble_border}; border-radius: 14px; padding: 5px 10px;
            background: {t.input_bg}; color: {t.text}; }}
QLineEdit:focus {{ border-color: {t.accent}; }}
QListView, QTreeWidget, QListWidget {{ border: none; background: {t.window}; outline: 0; }}
QToolButton {{ border: none; border-radius: 6px; padding: 4px 6px; color: {t.text}; }}
QToolButton:hover {{ background: {t.panel}; }}
QToolButton:checked {{ background: {t.selection}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ padding: 6px 10px; background: transparent; color: {t.muted}; border: none; }}
QTabBar::tab:selected {{ color: {t.accent}; border-bottom: 2px solid {t.accent}; }}

#Bubble {{ border-radius: 12px; border: 1px solid {t.bubble_border}; background: {t.bubble_in}; }}
#Bubble[outgoing="true"] {{ background: {t.bubble_out}; border-color: {t.bubble_out}; }}
#Bubble[highlighted="true"] {{ background: {t.highlight}; border-color: {t.highlight}; }}
#BubbleText {{ color: {t.text}; }}
#BubbleMeta {{ color: {t.muted}; font-size: 8pt; }}
#Pill {{ background: {t.pill}; color: {t.pill_text}; border-radius: 9px; padding: 2px 12px; }}
#Pill[highlighted="true"] {{ background: {t.highlight}; color: {t.text}; }}
#Quote {{ background: {t.quote_bg}; border-left: 3px solid {t.accent}; border-radius: 4px; }}
#Quote:hover {{ border-left-color: {t.text}; }}
#Forwarded {{ color: {t.accent}; font-size: 9pt; }}
#Missing {{ border: 1px dashed {t.missing}; border-radius: 8px; color: {t.missing}; padding: 8px; }}
#FileCard {{ background: {t.quote_bg}; border-radius: 8px; }}
#ReactionChip {{ background: {t.quote_bg}; border-radius: 10px; padding: 1px 8px; }}
#ReactionChip[active="true"] {{ background: {t.selection}; border: 1px solid {t.accent}; }}
#DateBadge {{ background: {t.pill}; color: {t.pill_text}; border-radius: 11px; padding: 3px 12px; }}
#Welcome QLabel {{ color: {t.muted}; }}
QPushButton#Primary {{ background: {t.accent}; color: white; border: none; border-radius: 8px;
                       padding: 8px 18px; font-weight: 600; }}
"""
