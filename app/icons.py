"""Jeu d'icônes SVG de Telegramor (trait 1,8 px, coins arrondis, grille 24 × 24).

Les icônes sont dessinées pour l'application et colorées à la volée avec les
jetons du thème. `bind()` mémorise une icône posée sur un bouton pour la
recolorer automatiquement lors d'un changement de thème.
"""

from __future__ import annotations

import weakref
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, QStandardPaths, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap

from . import design

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:          # module absent : boutons sans pictogramme, texte conservé
    QSvgRenderer = None

_P = {
    "chat": '<path d="M5 4.5h14a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2h-7.2L7 20.5V17H5a2 2 0 0 1-2-2V6.5a2 2 0 0 1 2-2z"/>'
            '<path d="M7.5 9h9M7.5 12.5h6"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1.6"/><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9"/>'
               '<path d="M10 13h4"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2.6"/><circle cx="8.8" cy="9.6" r="1.7"/>'
             '<path d="M20.5 15.5l-4.8-4.6L7 19.6"/>',
    "chart": '<path d="M3.5 20.5h17"/><path d="M6.5 16.5v-5"/><path d="M12 16.5V5.5"/><path d="M17.5 16.5v-8"/>',
    "timeline": '<rect x="3" y="5" width="18" height="16" rx="2.6"/><path d="M3 10h18M8 3v4M16 3v4"/>'
                '<path d="M7.5 14h3M7.5 17.2h6"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2.6"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "search": '<circle cx="10.8" cy="10.8" r="6.3"/><path d="M20 20l-4.6-4.6"/>',
    "filters": '<path d="M4 7h9.5M18.5 7H20M4 17h3.5M12.5 17H20"/><circle cx="16" cy="7" r="2.3"/>'
               '<circle cx="10" cy="17" r="2.3"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.2"/><path d="M12 7.8h.01"/>',
    "back": '<path d="M19 12H5.5"/><path d="M11 6l-6 6 6 6"/>',
    "first": '<path d="M5 4.5h14"/><path d="M12 20V9.5"/><path d="M7 13.5l5-5 5 5"/>',
    "last": '<path d="M5 19.5h14"/><path d="M12 4v10.5"/><path d="M7 10.5l5 5 5-5"/>',
    "list": '<path d="M9 6.5h11M9 12h11M9 17.5h11"/><path d="M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01"/>',
    "moon": '<path d="M20 14.6A8.2 8.2 0 1 1 9.4 4a6.6 6.6 0 0 0 10.6 10.6z"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
           'M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "import": '<path d="M12 3.5v11"/><path d="M7.5 10l4.5 4.5 4.5-4.5"/>'
              '<path d="M4 15.5v2.5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2.5"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.4v.6"/>'
            '<path d="M12 16.8h.01"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "copy": '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2.2"/>'
            '<path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>',
    "folder": '<path d="M3 7.2a2 2 0 0 1 2-2h4.2l2 2.4H19a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "file-text": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
                 '<path d="M9 13h6M9 16.5h4"/>',
    "alert": '<path d="M10.3 4.6L2.8 17.8A2 2 0 0 0 4.5 20.8h15a2 2 0 0 0 1.7-3L13.7 4.6a2 2 0 0 0-3.4 0z"/>'
             '<path d="M12 9.5v4.2"/><path d="M12 17h.01"/>',
    "play": '<path d="M8 5.6v12.8c0 .8.9 1.3 1.6.9l10-6.4a1 1 0 0 0 0-1.8l-10-6.4C8.9 4.3 8 4.8 8 5.6z" '
            'fill="currentColor" stroke="none"/>',
    "pause": '<path d="M8.5 5.5v13M15.5 5.5v13" stroke-width="2.6"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/>'
            '<path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    "music": '<path d="M9 17.5V6l11-2v11.5"/><circle cx="6.5" cy="17.5" r="2.5"/><circle cx="17.5" cy="15.5" r="2.5"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
    "video": '<rect x="3" y="6" width="13" height="12" rx="2.6"/><path d="M16 10.2l5-3v9.6l-5-3"/>',
    "smile": '<circle cx="12" cy="12" r="9"/><path d="M8.5 14.3a4.6 4.6 0 0 0 7 0"/>'
             '<path d="M9.2 9.6h.01M14.8 9.6h.01"/>',
    "film": '<rect x="3" y="4.5" width="18" height="15" rx="2.6"/><path d="M7.5 4.5v15M16.5 4.5v15'
            'M3 9.5h4.5M3 14.5h4.5M16.5 9.5H21M16.5 14.5H21"/>',
    "chevron-down": '<path d="M6.5 9.5l5.5 5.5 5.5-5.5"/>',
    "chevron-up": '<path d="M6.5 14.5L12 9l5.5 5.5"/>',
    "chevron-left": '<path d="M14.5 6.5L9 12l5.5 5.5"/>',
    "chevron-right": '<path d="M9.5 6.5L15 12l-5.5 5.5"/>',
    "refresh": '<path d="M19.5 11A7.6 7.6 0 0 0 6 6.6L4.5 8.2"/><path d="M4.5 4.5v3.7h3.7"/>'
               '<path d="M4.5 13A7.6 7.6 0 0 0 18 17.4l1.5-1.6"/><path d="M19.5 19.5v-3.7h-3.7"/>',
    "shield": '<path d="M12 3l7 3v5.2c0 4.4-3 7.9-7 9.8-4-1.9-7-5.4-7-9.8V6z"/><path d="M9 12l2.2 2.2L15.2 10"/>',
    "pin": '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.4"/>',
    "pencil": '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/>'
             '<path d="M9 7V4.5h6V7"/>',
    "database": '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/>'
                '<path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3"/>',
    "zoom-in": '<circle cx="10.8" cy="10.8" r="6.3"/><path d="M20 20l-4.6-4.6M8.3 10.8h5M10.8 8.3v5"/>',
    "zoom-out": '<circle cx="10.8" cy="10.8" r="6.3"/><path d="M20 20l-4.6-4.6M8.3 10.8h5"/>',
    "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "external": '<path d="M14 4h6v6"/><path d="M20 4l-8.5 8.5"/>'
                '<path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
             '<path d="M16 4.6a3.5 3.5 0 0 1 0 6.8"/><path d="M18 14.2a6 6 0 0 1 3.5 5.8"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.2l3.2 2"/>',
    "reply": '<path d="M9 14.5L4 9.5l5-5"/><path d="M4 9.5h10a6 6 0 0 1 6 6v4"/>',
    "forward": '<path d="M15 14.5l5-5-5-5"/><path d="M20 9.5H10a6 6 0 0 0-6 6v4"/>',
    "grid": '<rect x="3.5" y="3.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.6"/>'
            '<rect x="3.5" y="13.5" width="7" height="7" rx="1.6"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.6"/>',
    "sort": '<path d="M7 4.5v15M3.5 8L7 4.5 10.5 8M17 19.5v-15M13.5 16l3.5 3.5 3.5-3.5"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2.4"/>'
                '<path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M7.5 14h9"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "dot": '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/>',
}

# Pictogramme par type de média
MEDIA_ICONS = {
    "photo": "image", "video": "video", "video_message": "video", "animation": "film", "sticker": "smile",
    "file": "file", "audio": "music", "voice": "mic", "link": "link", "location": "pin", "contact": "user",
    "call": "clock", "poll": "chart", "game": "smile", "invoice": "file-text", "unknown": "file",
}


def svg(name: str, color: str) -> bytes:
    body = _P.get(name, _P["file"]).replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def _ratio() -> float:
    app = QGuiApplication.instance()
    return max(2.0, app.devicePixelRatio() if app else 1.0)


_cache: dict[tuple, QPixmap] = {}


def pixmap(name: str, color: str, size: int = 18) -> QPixmap:
    key = (name, color, size)
    if key in _cache:
        return _cache[key]
    ratio = _ratio()
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.transparent)
    if QSvgRenderer is not None:
        r = QSvgRenderer(QByteArray(svg(name, color)))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, pm.width(), pm.height()))
        p.end()
    pm.setDevicePixelRatio(ratio)
    _cache[key] = pm
    return pm


def icon(name: str, color: str | None = None, size: int = 18, active: str | None = None,
         checked: str | None = None, disabled: str | None = None) -> QIcon:
    """Icône avec variantes d'état (survol, coché, désactivé) tirées du thème."""
    t = design.current()
    ic = QIcon()
    normal = color or t.muted
    ic.addPixmap(pixmap(name, normal, size), QIcon.Normal, QIcon.Off)
    ic.addPixmap(pixmap(name, active or t.text, size), QIcon.Active, QIcon.Off)
    ic.addPixmap(pixmap(name, checked or t.accent, size), QIcon.Normal, QIcon.On)
    ic.addPixmap(pixmap(name, checked or t.accent, size), QIcon.Active, QIcon.On)
    ic.addPixmap(pixmap(name, checked or t.accent, size), QIcon.Selected, QIcon.Off)
    ic.addPixmap(pixmap(name, disabled or t.faint, size), QIcon.Disabled, QIcon.Off)
    return ic


# --------------------------------------------------------------------------- #
# Recoloration automatique au changement de thème
# --------------------------------------------------------------------------- #

_bound: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def bind(widget, name: str, role: str = "muted", size: int = 18, active: str = "text",
         checked: str = "accent") -> None:
    """Pose une icône sur un bouton (QAbstractButton / QAction) et la recolore au changement de thème."""
    _bound[widget] = (name, role, size, active, checked)
    _apply(widget, name, role, size, active, checked)
    if hasattr(widget, "setIconSize"):
        widget.setIconSize(QSize(size, size))
    _fit_text(widget, size)


def _fit_text(widget, size: int) -> None:
    from PySide6.QtGui import QFont, QFontMetrics
    from PySide6.QtWidgets import QPushButton
    if isinstance(widget, QPushButton) and widget.text():
        f = QFont(widget.font())
        f.setWeight(QFont.DemiBold)                 # largeur du texte en gras (boutons principaux)
        text = widget.text().replace("&", "")
        widget.setMinimumWidth(QFontMetrics(f).horizontalAdvance(text) + size + 38)


def _apply(widget, name, role, size, active, checked) -> None:
    t = design.current()
    widget.setIcon(icon(name, getattr(t, role), size, getattr(t, active), getattr(t, checked)))


def retheme() -> None:
    for w, args in list(_bound.items()):
        try:
            _apply(w, *args)
        except RuntimeError:       # objet Qt détruit
            pass


# --------------------------------------------------------------------------- #
# Fichiers PNG pour la feuille de style (flèches des listes, coches…)
# --------------------------------------------------------------------------- #

def qss_icon(name: str, color: str, size: int = 14) -> str:
    """Chemin d'une image PNG utilisable dans une feuille de style (`image: url(...)`)."""
    # Dossier au nom sans espace ni caractère spécial (utilisable tel quel dans url(...))
    base = Path(QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation) or Path.home() / ".cache")
    folder = base / "telegramor" / "icons"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-{color.lstrip('#')}-{size}.png"
    if not path.exists():
        pm = pixmap(name, color, size)
        pm.save(str(path), "PNG")
    return path.as_posix()
