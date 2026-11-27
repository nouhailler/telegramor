"""Système de design Telegramor : jetons de couleurs, typographie, espacements, rayons.

Toute l'apparence de l'application découle de ce module :
- `app/styles.py` construit la feuille de style Qt (QSS) à partir des jetons ;
- `app/icons.py` colore les icônes SVG avec ces mêmes jetons ;
- les composants dessinés à la main (bulles, graphiques, miniatures) lisent le
  thème courant via `current()`.

Les deux thèmes sont conçus indépendamment : le thème sombre n'est pas une
inversion du thème clair (surfaces bleu nuit étagées, accents éclaircis pour
garder un contraste suffisant, bordures discrètes).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor

# --------------------------------------------------------------------------- #
# Dimensions (pixels logiques)
# --------------------------------------------------------------------------- #

SPACE_XS, SPACE_S, SPACE_M, SPACE_L, SPACE_XL, SPACE_XXL = 4, 8, 12, 16, 24, 32
RADIUS_S, RADIUS_M, RADIUS_L, RADIUS_XL = 6, 8, 12, 16

NAV_WIDTH = 96            # barre latérale de navigation
TOPBAR_HEIGHT = 56
CONV_LIST_MIN = 270
INFO_PANEL_MIN = 290

# Typographie : première police installée de la liste (Inter si présente,
# sinon Cantarell sur GNOME/Debian, puis les polices Linux courantes).
FONT_FAMILIES = ["Inter", "Noto Sans", "Cantarell", "Ubuntu", "Segoe UI", "DejaVu Sans"]
FONT_SIZE = 10            # points
FONT_TITLE = 15
FONT_SECTION = 11.5
FONT_SMALL = 8.6


@dataclass(frozen=True)
class Theme:
    name: str
    dark: bool
    # Surfaces
    window: str           # fond général de l'application
    surface: str          # panneaux, cartes, listes
    panel: str            # fonds discrets (survol, zones secondaires)
    hover: str            # survol d'un élément
    nav: str              # barre latérale
    chat_bg: str          # fond de la zone de lecture
    border: str
    border_strong: str
    # Texte
    text: str
    muted: str
    faint: str
    # Marque
    accent: str           # bleu principal
    accent_hover: str
    accent_pressed: str
    accent_soft: str      # fond teinté (sélection, éléments actifs)
    accent_text: str      # texte sur fond teinté
    primary_bg: str       # fond des boutons principaux (texte blanc lisible)
    primary_hover: str
    secondary: str
    violet: str
    turquoise: str
    # États
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    # Conversation
    bubble_in: str
    bubble_out: str
    bubble_border: str
    bubble_out_border: str
    selection: str
    pill: str
    pill_text: str
    quote_bg: str
    highlight: str
    highlight_border: str
    input_bg: str
    tooltip_bg: str
    tooltip_text: str
    scrollbar: str
    scrollbar_hover: str
    viewer_bg: str        # visionneuse de photos (immersive)

    @property
    def missing(self) -> str:
        return self.danger

    def color(self, name: str, alpha: int | None = None) -> QColor:
        c = QColor(getattr(self, name))
        if alpha is not None:
            c.setAlpha(alpha)
        return c


LIGHT = Theme(
    name="clair", dark=False,
    window="#F5F7FB", surface="#FFFFFF", panel="#F0F3F8", hover="#F2F5FA", nav="#FFFFFF",
    chat_bg="#F3F6FA", border="#E7ECF3", border_strong="#D6DEE9",
    text="#202B3C", muted="#738096", faint="#A3ADBD",
    accent="#3986D8", accent_hover="#2F79C8", accent_pressed="#286AB0", accent_soft="#EAF2FC",
    accent_text="#2A6DB8", primary_bg="#3986D8", primary_hover="#2F79C8", secondary="#5B9DE6", violet="#8170D8", turquoise="#36B9B0",
    success="#2E9C6A", success_soft="#E5F5EC", warning="#C9801F", warning_soft="#FDF2E2",
    danger="#C9463F", danger_soft="#FBEBEA",
    bubble_in="#FFFFFF", bubble_out="#E6F0FC", bubble_border="#E3E9F1", bubble_out_border="#D2E3F7",
    selection="#EAF2FC", pill="#FFFFFF", pill_text="#5F6C82",
    quote_bg="rgba(57,134,216,0.08)", highlight="#FFE69C", highlight_border="#F2C94C",
    input_bg="#FFFFFF", tooltip_bg="#202B3C", tooltip_text="#F5F7FB",
    scrollbar="#CBD4E1", scrollbar_hover="#A9B5C6", viewer_bg="#0E141F",
)

DARK = Theme(
    name="sombre", dark=True,
    window="#0E1420", surface="#151D2B", panel="#1A2333", hover="#1E2839", nav="#111926",
    chat_bg="#0F1622", border="#232E40", border_strong="#2F3C52",
    text="#E4EAF3", muted="#93A1B6", faint="#66748A",
    accent="#5B9DE6", accent_hover="#71ACEC", accent_pressed="#4A8AD2", accent_soft="#1B2E48",
    accent_text="#8CBDF2", primary_bg="#3A78C4", primary_hover="#4686D0", secondary="#79B0EE", violet="#9C8FF0", turquoise="#4CC9BF",
    success="#4CC38A", success_soft="#15302A", warning="#E7A64E", warning_soft="#352914",
    danger="#EF706B", danger_soft="#3A1E22",
    bubble_in="#182131", bubble_out="#1D3553", bubble_border="#222D3F", bubble_out_border="#27446A",
    selection="#1B2E48", pill="#182131", pill_text="#A3B0C4",
    quote_bg="rgba(91,157,230,0.12)", highlight="#5E4F18", highlight_border="#8D7525",
    input_bg="#111926", tooltip_bg="#E4EAF3", tooltip_text="#151D2B",
    scrollbar="#2E3A4F", scrollbar_hover="#43526B", viewer_bg="#080C13",
)

# Couleurs d'avatar : correspondance avec les classes userpic1..8 des exports,
# accordées à la palette (saturation modérée, texte blanc lisible).
USERPIC_COLORS = {
    "userpic1": "#E0706A", "userpic2": "#E39A4B", "userpic3": "#8170D8", "userpic4": "#4FAE78",
    "userpic5": "#36B0A8", "userpic6": "#3986D8", "userpic7": "#D86C9E", "userpic8": "#E8875A",
}
FALLBACK_COLORS = list(USERPIC_COLORS.values())

_current: Theme = LIGHT


def theme_for(dark: bool) -> Theme:
    return DARK if dark else LIGHT


def current() -> Theme:
    """Thème actif (utilisé par les composants dessinés à la main)."""
    return _current


def set_current(theme: Theme) -> None:
    global _current
    _current = theme


def sender_color(userpic_class: str | None, name: str | None) -> str:
    if userpic_class in USERPIC_COLORS:
        return USERPIC_COLORS[userpic_class]
    if not name:
        return FALLBACK_COLORS[0]
    return FALLBACK_COLORS[sum(map(ord, name)) % len(FALLBACK_COLORS)]


def name_color(userpic_class: str | None, name: str | None, theme: Theme | None = None) -> str:
    """Couleur du nom d'un expéditeur, éclaircie en thème sombre pour rester lisible."""
    c = QColor(sender_color(userpic_class, name))
    if (theme or _current).dark:
        c = c.lighter(135)
    return c.name()


def mix(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t))
