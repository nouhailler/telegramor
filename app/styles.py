"""Application du thème : palette Qt + feuille de style unique générée depuis les jetons.

Toutes les règles visuelles sont ici (aucune feuille de style dispersée dans
les écrans). Les composants se distinguent par leur `objectName` ou par des
propriétés dynamiques :
- `variant` sur les boutons : "primary", "ghost", "danger", "nav", "icon", "chip" ;
- `card="true"` sur un QFrame pour une carte (surface + bordure + rayon) ;
- `muted="true"` / `role="title"|"section"|"caption"` sur les QLabel ;
- `variant="segmented"` sur un QTabBar pour des onglets en pastilles.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from . import design, icons
from .design import (  # noqa: F401  (réexportés pour les écrans)
    DARK, FALLBACK_COLORS, LIGHT, USERPIC_COLORS, Theme, name_color, sender_color, theme_for,
)


def ui_font(size: float = design.FONT_SIZE) -> QFont:
    families = set(QFontDatabase.families())
    f = QFont(next((n for n in design.FONT_FAMILIES if n in families), QFont().family()))
    f.setPointSizeF(size)
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


def apply_theme(app: QApplication, theme: Theme) -> None:
    design.set_current(theme)
    app.setStyle("Fusion")
    if not app.property("tae_font_set"):
        base = app.font()
        f = ui_font(max(base.pointSizeF(), design.FONT_SIZE))
        app.setFont(f)
        app.setProperty("tae_font_set", True)
    pal = QPalette()
    c = QColor
    pal.setColor(QPalette.Window, c(theme.window))
    pal.setColor(QPalette.WindowText, c(theme.text))
    pal.setColor(QPalette.Base, c(theme.surface))
    pal.setColor(QPalette.AlternateBase, c(theme.panel))
    pal.setColor(QPalette.Text, c(theme.text))
    pal.setColor(QPalette.Button, c(theme.surface))
    pal.setColor(QPalette.ButtonText, c(theme.text))
    pal.setColor(QPalette.Highlight, c(theme.accent))
    pal.setColor(QPalette.HighlightedText, c("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, c(theme.tooltip_bg))
    pal.setColor(QPalette.ToolTipText, c(theme.tooltip_text))
    pal.setColor(QPalette.Link, c(theme.accent))
    pal.setColor(QPalette.LinkVisited, c(theme.violet))
    pal.setColor(QPalette.PlaceholderText, c(theme.muted))
    pal.setColor(QPalette.Mid, c(theme.border))
    pal.setColor(QPalette.Midlight, c(theme.border))
    pal.setColor(QPalette.Light, c(theme.surface))
    pal.setColor(QPalette.Dark, c(theme.border_strong))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, c(theme.faint))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(theme))
    icons.retheme()


def stylesheet(t: Theme) -> str:
    chevron = icons.qss_icon("chevron-down", t.muted, 14)
    chevron_up = icons.qss_icon("chevron-up", t.muted, 14)
    check = icons.qss_icon("check", "#ffffff", 14)
    menu_check = icons.qss_icon("check", t.accent, 14)
    left = icons.qss_icon("chevron-left", t.muted, 16)
    right = icons.qss_icon("chevron-right", t.muted, 16)
    r_s, r_m, r_l = design.RADIUS_S, design.RADIUS_M, design.RADIUS_L
    return f"""
/* ------------------------------------------------------------------ Base */
QMainWindow, QDialog {{ background: {t.window}; }}
QWidget {{ color: {t.text}; }}
QLabel {{ background: transparent; }}
QLabel[muted="true"], #Muted {{ color: {t.muted}; }}
QLabel[role="title"] {{ font-size: {design.FONT_TITLE}pt; font-weight: 600; color: {t.text}; }}
QLabel[role="section"] {{ font-size: {design.FONT_SECTION}pt; font-weight: 600; color: {t.text}; }}
QLabel[role="caption"] {{ font-size: {design.FONT_SMALL}pt; color: {t.muted}; }}
QLabel[role="overline"] {{ font-size: {design.FONT_SMALL}pt; font-weight: 600; color: {t.faint};
                          letter-spacing: 0.6px; }}
QFrame[card="true"] {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r_l}px; }}
QFrame[card="true"] QLabel {{ border: none; }}
QFrame[separator="true"] {{ background: {t.border}; border: none; max-height: 1px; min-height: 1px; }}
QSplitter::handle {{ background: {t.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background: {t.accent}; }}
QSplitter[variant="spaced"]::handle {{ background: transparent; }}

/* ---------------------------------------------------------- Menus natifs */
QMenuBar {{ background: {t.surface}; color: {t.text}; border-bottom: 1px solid {t.border}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: {r_s}px; background: transparent; }}
QMenuBar::item:selected {{ background: {t.hover}; }}
QMenuBar::item:pressed {{ background: {t.accent_soft}; color: {t.accent_text}; }}
QMenu {{ background: {t.surface}; border: 1px solid {t.border_strong}; border-radius: {r_l}px; padding: 6px; }}
QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: {r_s}px; color: {t.text}; }}
QMenu::item:selected {{ background: {t.accent_soft}; color: {t.accent_text}; }}
QMenu::item:disabled {{ color: {t.faint}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 5px 8px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
QMenu::indicator:checked {{ image: url("{menu_check}"); }}
QMenu::right-arrow {{ image: url("{right}"); width: 12px; height: 12px; }}
QToolTip {{ background: {t.tooltip_bg}; color: {t.tooltip_text}; border: none; border-radius: {r_s}px;
            padding: 6px 9px; }}
QStatusBar {{ background: {t.surface}; color: {t.muted}; border-top: 1px solid {t.border}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {t.muted}; padding: 0 6px; }}

/* --------------------------------------------------------------- Boutons */
QPushButton {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong};
               border-radius: {r_m}px; padding: 7px 14px; min-height: 18px; }}
QPushButton:hover {{ background: {t.hover}; border-color: {t.faint}; }}
QPushButton:pressed {{ background: {t.panel}; }}
QPushButton:focus {{ border-color: {t.accent}; }}
QPushButton:disabled {{ color: {t.faint}; background: {t.panel}; border-color: {t.border}; }}
QPushButton:default {{ border-color: {t.accent}; }}
QPushButton[variant="primary"], QPushButton#Primary {{ background: {t.primary_bg}; color: #ffffff;
               border: 1px solid {t.primary_bg}; font-weight: 600; }}
QPushButton[variant="primary"]:hover, QPushButton#Primary:hover {{ background: {t.primary_hover};
               border-color: {t.primary_hover}; }}
QPushButton[variant="primary"]:pressed, QPushButton#Primary:pressed {{ background: {t.accent_pressed}; }}
QPushButton[variant="primary"]:focus {{ border: 1px solid {t.accent_text}; }}
QPushButton[variant="primary"]:disabled {{ background: {t.border}; border-color: {t.border}; color: {t.faint}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {t.text}; }}
QPushButton[variant="ghost"]:hover {{ background: {t.hover}; }}
QPushButton[variant="ghost"]:pressed {{ background: {t.panel}; }}
QPushButton[variant="danger"] {{ color: {t.danger}; border-color: {t.border_strong}; }}
QPushButton[variant="danger"]:hover {{ background: {t.danger_soft}; border-color: {t.danger}; }}
QPushButton[variant="chip"] {{ border-radius: 14px; padding: 4px 12px; background: {t.surface};
               color: {t.muted}; border: 1px solid {t.border}; }}
QPushButton[variant="chip"]:checked {{ background: {t.accent_soft}; color: {t.accent_text};
               border-color: {t.accent_soft}; }}

QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {r_m}px;
               padding: 5px 7px; color: {t.text}; }}
QToolButton:hover {{ background: {t.hover}; }}
QToolButton:pressed {{ background: {t.panel}; }}
QToolButton:checked {{ background: {t.accent_soft}; color: {t.accent_text}; }}
QToolButton:focus {{ border-color: {t.accent}; }}
QToolButton:disabled {{ color: {t.faint}; }}
QToolButton::menu-indicator {{ image: url("{chevron}"); width: 10px; height: 10px;
               subcontrol-position: right center; subcontrol-origin: padding; right: 4px; }}
QToolButton[popupMode="2"] {{ padding-right: 18px; }}
QToolButton[variant="pill"] {{ border: 1px solid {t.border}; border-radius: 14px; padding: 4px 12px;
               background: {t.surface}; color: {t.text}; font-weight: 600; }}
QToolButton[variant="pill"]:hover {{ border-color: {t.border_strong}; background: {t.hover}; }}
QToolButton[variant="secondary"] {{ border: 1px solid {t.border_strong}; background: {t.surface};
               padding: 6px 12px; }}
QToolButton[variant="secondary"]:hover {{ background: {t.hover}; }}
QToolButton[variant="secondary"]:checked {{ background: {t.accent_soft}; color: {t.accent_text};
               border-color: {t.accent}; }}

/* ---------------------------------------------------- Navigation latérale */
#NavRail {{ background: {t.nav}; border-right: 1px solid {t.border}; }}
#NavRail QToolButton {{ border-radius: {r_l}px; padding: 8px 2px 6px 2px; color: {t.muted};
               font-size: {design.FONT_SMALL}pt; font-weight: 600; }}
#NavRail QToolButton:hover {{ background: {t.hover}; color: {t.text}; }}
#NavRail QToolButton:checked {{ background: {t.accent_soft}; color: {t.accent_text}; }}
#NavRail QToolButton:focus {{ border: 1px solid {t.accent}; }}
#NavLogo {{ padding: 6px; }}

/* -------------------------------------------------------- Barre du haut */
#TopBar {{ background: {t.surface}; border-bottom: 1px solid {t.border}; }}
#TopBarTitle {{ font-size: {design.FONT_SECTION + 0.5}pt; font-weight: 600; color: {t.text}; }}
#TopBarSubtitle {{ color: {t.muted}; font-size: {design.FONT_SMALL}pt; }}
QLineEdit#GlobalSearch {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 11px;
               padding: 8px 12px 8px 6px; font-size: {design.FONT_SIZE + 0.5}pt; }}
QLineEdit#GlobalSearch:hover {{ border-color: {t.border_strong}; }}
QLineEdit#GlobalSearch:focus {{ background: {t.surface}; border: 1px solid {t.accent}; }}
#ShortcutHint {{ color: {t.faint}; background: {t.surface}; border: 1px solid {t.border}; border-radius: 5px;
               padding: 1px 6px; font-size: {design.FONT_SMALL - 0.4}pt; }}

/* ------------------------------------------------------------ Saisie */
QLineEdit, QSpinBox, QDateEdit, QDateTimeEdit, QPlainTextEdit, QTextEdit {{
               background: {t.input_bg}; color: {t.text}; border: 1px solid {t.border_strong};
               border-radius: {r_m}px; padding: 6px 10px; selection-background-color: {t.accent};
               selection-color: #ffffff; }}
QLineEdit:hover, QSpinBox:hover, QDateEdit:hover {{ border-color: {t.faint}; }}
QLineEdit:focus, QSpinBox:focus, QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
               border: 1px solid {t.accent}; }}
QLineEdit:disabled, QDateEdit:disabled {{ color: {t.faint}; background: {t.panel}; }}
QLineEdit[variant="search"] {{ background: {t.panel}; border-color: {t.border}; border-radius: 10px; }}
QLineEdit[variant="search"]:focus {{ background: {t.surface}; border-color: {t.accent}; }}
QDateEdit::drop-down, QSpinBox::up-button, QSpinBox::down-button {{ border: none; width: 20px; }}
QDateEdit::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}

QComboBox {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong};
               border-radius: {r_m}px; padding: 6px 30px 6px 10px; min-height: 18px; }}
QComboBox:hover {{ border-color: {t.faint}; }}
QComboBox:focus {{ border-color: {t.accent}; }}
QComboBox:on {{ border-color: {t.accent}; }}
QComboBox:disabled {{ color: {t.faint}; background: {t.panel}; }}
QComboBox::drop-down {{ border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: right center; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:on {{ image: url("{chevron_up}"); }}
QComboBox[variant="ghost"] {{ background: transparent; border-color: transparent; color: {t.muted};
               font-weight: 600; }}
QComboBox[variant="ghost"]:hover {{ background: {t.hover}; }}
QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.border_strong};
               border-radius: {r_m}px; padding: 4px; outline: 0; selection-background-color: {t.accent_soft};
               selection-color: {t.accent_text}; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; border-radius: {r_s}px; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {t.text}; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 1.5px solid {t.border_strong};
               background: {t.surface}; }}
QCheckBox::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url("{check}"); }}
QRadioButton::indicator:checked {{ background: {t.surface}; border: 5px solid {t.accent}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t.faint}; }}

QSlider::groove:horizontal {{ height: 4px; background: {t.border_strong}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
               background: {t.surface}; border: 2px solid {t.accent}; }}
QSlider::handle:horizontal:hover {{ background: {t.accent_soft}; }}
QProgressBar {{ background: {t.panel}; border: none; border-radius: 5px; height: 10px; text-align: center;
               color: {t.muted}; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 5px; }}

/* -------------------------------------------------------- Défilement */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px 1px 2px 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0 2px 1px 2px; }}
QScrollBar::handle:vertical {{ background: {t.scrollbar}; border-radius: 4px; min-height: 36px; margin: 0 2px; }}
QScrollBar::handle:horizontal {{ background: {t.scrollbar}; border-radius: 4px; min-width: 36px; margin: 2px 0; }}
QScrollBar::handle:hover {{ background: {t.scrollbar_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollArea {{ border: none; }}

/* --------------------------------------------------- Listes et tableaux */
QListView, QListWidget, QTreeView, QTreeWidget, QTableView, QTableWidget {{
               background: {t.surface}; border: none; outline: 0; alternate-background-color: {t.panel};
               selection-background-color: {t.accent_soft}; selection-color: {t.text}; gridline-color: {t.border}; }}
QListWidget::item, QTreeWidget::item, QTreeView::item {{ padding: 5px 6px; border-radius: {r_s}px; }}
QTableView::item, QTableWidget::item {{ padding: 6px 8px; border: none; }}
QListWidget::item:hover, QTreeWidget::item:hover, QTreeView::item:hover, QTableView::item:hover {{
               background: {t.hover}; }}
QListWidget::item:selected, QTreeWidget::item:selected, QTreeView::item:selected, QTableView::item:selected {{
               background: {t.accent_soft}; color: {t.text}; }}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:closed {{ image: url("{right}"); }}
QTreeView::branch:has-children:open {{ image: url("{chevron}"); }}
QHeaderView {{ background: {t.surface}; border: none; }}
QHeaderView::section {{ background: {t.surface}; color: {t.muted}; border: none;
               border-bottom: 1px solid {t.border}; padding: 9px 8px; font-weight: 600;
               font-size: {design.FONT_SMALL + 0.2}pt; }}
QHeaderView::section:hover {{ color: {t.text}; }}
QHeaderView::up-arrow {{ image: url("{chevron_up}"); width: 10px; height: 10px; }}
QHeaderView::down-arrow {{ image: url("{chevron}"); width: 10px; height: 10px; }}
QTableCornerButton::section {{ background: {t.surface}; border: none; }}

/* ------------------------------------------------------------ Onglets */
QTabWidget::pane {{ border: none; background: transparent; }}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar {{ background: transparent; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {t.muted}; border: none; border-bottom: 2px solid transparent;
               padding: 8px 12px; margin-right: 2px; font-weight: 600; }}
QTabBar::tab:hover {{ color: {t.text}; }}
QTabBar::tab:selected {{ color: {t.accent_text}; border-bottom: 2px solid {t.accent}; }}
QTabBar[variant="segmented"] {{ background: {t.panel}; border-radius: 10px; }}
QTabBar[variant="segmented"]::tab {{ border: none; border-radius: 8px; margin: 3px 2px; padding: 6px 10px;
               color: {t.muted}; }}
QTabBar[variant="segmented"]::tab:hover {{ color: {t.text}; }}
QTabBar[variant="segmented"]::tab:selected {{ background: {t.surface}; color: {t.text};
               border: 1px solid {t.border}; }}
QTabBar::scroller {{ width: 24px; }}
QTabBar QToolButton {{ background: {t.surface}; border: 1px solid {t.border}; }}
QTabBar QToolButton::left-arrow {{ image: url("{left}"); }}
QTabBar QToolButton::right-arrow {{ image: url("{right}"); }}

/* ----------------------------------------------------------- Calendrier */
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {t.surface}; border-bottom: 1px solid {t.border}; }}
QCalendarWidget QToolButton {{ color: {t.text}; font-weight: 600; padding: 6px 10px; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth {{ qproperty-icon: url("{left}"); }}
QCalendarWidget QToolButton#qt_calendar_nextmonth {{ qproperty-icon: url("{right}"); }}
QCalendarWidget QAbstractItemView {{ background: {t.surface}; selection-background-color: {t.accent};
               selection-color: #ffffff; outline: 0; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {t.faint}; }}

/* ------------------------------------------------------ Liste des conv. */
#SidePanel {{ background: {t.surface}; }}
#PanelHeader {{ background: {t.surface}; }}
#CountBadge {{ background: {t.panel}; color: {t.muted}; border-radius: 9px; padding: 1px 8px;
               font-size: {design.FONT_SMALL}pt; font-weight: 600; }}

/* ------------------------------------------------------- Conversation */
#ChatHeader {{ background: {t.surface}; border-bottom: 1px solid {t.border}; }}
#ChatTitle {{ font-weight: 600; font-size: {design.FONT_SECTION + 0.5}pt; }}
#ChatArea, #ChatArea > QWidget > QWidget {{ background: {t.chat_bg}; }}
#Bubble {{ border-radius: 14px; border: 1px solid {t.bubble_border}; background: {t.bubble_in}; }}
#Bubble[outgoing="true"] {{ background: {t.bubble_out}; border-color: {t.bubble_out_border}; }}
#Bubble[highlighted="true"] {{ background: {t.highlight}; border-color: {t.highlight_border}; }}
#BubbleText {{ color: {t.text}; }}
#BubbleMeta {{ color: {t.faint}; }}
#SenderName {{ font-weight: 600; }}
#Pill {{ background: {t.pill}; color: {t.pill_text}; border: 1px solid {t.border}; border-radius: 12px;
               padding: 4px 14px; font-weight: 600; }}
#Pill[service="true"] {{ font-weight: normal; background: {t.panel}; border-color: transparent; }}
#Pill[highlighted="true"] {{ background: {t.highlight}; color: {t.text}; border-color: {t.highlight_border}; }}
#DayRule {{ background: {t.border}; max-height: 1px; min-height: 1px; }}
#Quote {{ background: {t.quote_bg}; border-left: 3px solid {t.accent}; border-radius: 6px; }}
#Quote:hover {{ background: {t.accent_soft}; }}
#Forwarded {{ color: {t.accent_text}; }}
#Missing {{ background: {t.danger_soft}; border: 1px dashed {t.danger}; border-radius: 10px; color: {t.danger};
               padding: 9px 11px; }}
#FileCard {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 10px; }}
#FileCard:hover {{ border-color: {t.border_strong}; }}
#Bubble[outgoing="true"] #FileCard {{ background: rgba(255,255,255,{0.06 if t.dark else 0.55}); }}
#FileIcon {{ background: {t.accent_soft}; border-radius: 9px; }}
#FileIcon[missing="true"] {{ background: {t.danger_soft}; }}
#ReactionChip {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 11px; padding: 1px 8px; }}
#ReactionChip[active="true"] {{ background: {t.accent_soft}; border-color: {t.accent}; }}
#DateBadge {{ background: {t.panel}; color: {t.text}; border-radius: 13px; padding: 4px 12px; font-weight: 600; }}
#DateBadge:hover {{ background: {t.accent_soft}; color: {t.accent_text}; }}
#FindBar {{ background: {t.surface}; border-bottom: 1px solid {t.border}; }}
#Welcome QLabel {{ color: {t.muted}; }}
#Welcome QLabel[role="title"] {{ color: {t.text}; }}
#EmptyState {{ color: {t.muted}; }}

/* ---------------------------------------------------- Panneau d'infos */
#InfoPanel {{ background: {t.surface}; }}
#InfoName {{ font-size: {design.FONT_SECTION + 1}pt; font-weight: 600; }}
#StatTile {{ background: {t.panel}; border-radius: 10px; }}
#StatValue {{ font-weight: 600; font-size: {design.FONT_SIZE + 0.5}pt; }}
#StatLabel {{ color: {t.muted}; font-size: {design.FONT_SMALL}pt; }}

/* --------------------------------------------------------- Statistiques */
#KpiCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r_l}px; }}
#KpiValue {{ font-size: 20pt; font-weight: 700; color: {t.text}; }}
#KpiLabel {{ color: {t.text}; font-weight: 600; }}
#KpiDetail {{ color: {t.muted}; font-size: {design.FONT_SMALL}pt; }}
#KpiIcon {{ border-radius: 10px; }}
#ChartCard {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r_l}px; }}

/* -------------------------------------------------------- Bibliothèque */
#Toolbar {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {r_l}px; }}
#ActionBar {{ background: {t.surface}; border-top: 1px solid {t.border}; }}
#SummaryChip {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; padding: 6px 12px; }}

/* -------------------------------------------------------- Visionneuse */
#Viewer {{ background: {t.viewer_bg}; }}
#Viewer QScrollArea, #ViewerArea {{ background: {t.viewer_bg}; }}
#ViewerBar {{ background: rgba(14,20,31,0.92); border-top: 1px solid rgba(255,255,255,0.08); }}
#ViewerBar QLabel {{ color: #C9D3E2; }}
#ViewerBar QToolButton {{ color: #E4EAF3; border-radius: {r_m}px; padding: 6px 8px; }}
#ViewerBar QToolButton:hover {{ background: rgba(255,255,255,0.10); }}
#ViewerBar QPushButton {{ background: rgba(255,255,255,0.08); color: #E4EAF3;
               border: 1px solid rgba(255,255,255,0.14); }}
#ViewerBar QPushButton:hover {{ background: rgba(255,255,255,0.16); }}
#ViewerBar QSlider::groove:horizontal {{ background: rgba(255,255,255,0.18); }}
#ViewerMessage {{ color: #FF9A94; }}
"""
