"""Vérification des dépendances (obligatoires et facultatives) et commandes
d'installation adaptées à la distribution.

Aucun paquet n'est jamais installé automatiquement : l'application affiche la
commande, que l'utilisateur copie et exécute lui-même.
Les noms de paquets Debian ont été vérifiés sur Debian 13 (trixie).
"""

from __future__ import annotations

import importlib
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Dependency:
    key: str
    label: str
    required: bool
    module: str | None              # module Python importé par Telegramor
    debian: str                     # paquet Debian / Ubuntu
    fedora: str                     # paquet Fedora
    pip: str | None                 # paquet PyPI (environnement virtuel)
    purpose: str                    # à quoi il sert
    without: str                    # conséquence de son absence
    command: str | None = None      # exécutable (au lieu d'un module)


DEPENDENCIES: list[Dependency] = [
    Dependency("qtcore", "Qt 6 pour Python (PySide6) — cœur", True, "PySide6.QtCore",
               "python3-pyside6.qtcore", "python3-pyside6", "PySide6", "Interface graphique",
               "L'application ne peut pas démarrer."),
    Dependency("qtgui", "PySide6 — affichage", True, "PySide6.QtGui", "python3-pyside6.qtgui",
               "python3-pyside6", "PySide6", "Dessin, images, export PDF", "L'application ne peut pas démarrer."),
    Dependency("qtwidgets", "PySide6 — fenêtres", True, "PySide6.QtWidgets", "python3-pyside6.qtwidgets",
               "python3-pyside6", "PySide6", "Fenêtres et contrôles", "L'application ne peut pas démarrer."),
    Dependency("qtsvg", "PySide6 — icônes SVG", True, "PySide6.QtSvg", "python3-pyside6.qtsvg",
               "python3-pyside6", "PySide6", "Icônes de l'interface", "Les icônes ne s'affichent pas."),
    Dependency("bs4", "Beautiful Soup", True, "bs4", "python3-bs4", "python3-beautifulsoup4", "beautifulsoup4",
               "Lecture des exports HTML", "Impossible d'importer une archive."),
    Dependency("lxml", "lxml", True, "lxml", "python3-lxml", "python3-lxml", "lxml",
               "Analyse HTML rapide", "Impossible d'importer une archive."),
    Dependency("multimedia", "PySide6 — multimédia", False, "PySide6.QtMultimedia", "python3-pyside6.qtmultimedia",
               "python3-pyside6", "PySide6", "Lecture des vidéos et sons dans l'application",
               "Les vidéos s'ouvrent avec le lecteur du système."),
    Dependency("multimediawidgets", "PySide6 — lecteur vidéo", False, "PySide6.QtMultimediaWidgets",
               "python3-pyside6.qtmultimediawidgets", "python3-pyside6", "PySide6",
               "Fenêtre du lecteur vidéo intégré", "Les vidéos s'ouvrent avec le lecteur du système."),
    Dependency("printsupport", "PySide6 — impression", False, "PySide6.QtPrintSupport",
               "python3-pyside6.qtprintsupport", "python3-pyside6", "PySide6",
               "Impression directe d'une conversation (boîte de dialogue d'impression)",
               "L'impression passe par le navigateur (page HTML prête à imprimer)."),
    Dependency("svgplugin", "Greffon d'images SVG de Qt", False, None, "qt6-svg-plugins", "qt6-qtsvg", None,
               "Affichage des autocollants et images SVG des exports", "Ces images ne s'affichent pas."),
]


@dataclass
class DependencyStatus:
    dep: Dependency
    available: bool
    detail: str = ""


def _check(dep: Dependency) -> DependencyStatus:
    if dep.command:
        path = shutil.which(dep.command)
        return DependencyStatus(dep, path is not None, path or "")
    if dep.module is None:          # greffon Qt : recherche dans les dossiers de greffons
        try:
            from PySide6.QtCore import QLibraryInfo
            plugins = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)) / "imageformats"
            found = any(plugins.glob("libqsvg*"))
            return DependencyStatus(dep, found, str(plugins))
        except Exception:
            return DependencyStatus(dep, False)
    try:
        mod = importlib.import_module(dep.module)
        return DependencyStatus(dep, True, getattr(mod, "__version__", "") or "")
    except Exception as exc:          # ImportError, ou bibliothèque système manquante
        return DependencyStatus(dep, False, str(exc).splitlines()[0][:160])


def check_all() -> list[DependencyStatus]:
    return [_check(d) for d in DEPENDENCIES]


def missing(required_only: bool = False) -> list[DependencyStatus]:
    return [s for s in check_all() if not s.available and (s.dep.required or not required_only)]


def detect_distribution(os_release: Path = Path("/etc/os-release")) -> str:
    """'debian' (Debian, Ubuntu, Mint…), 'fedora', 'arch' ou 'autre'."""
    try:
        data = dict(line.split("=", 1) for line in os_release.read_text().splitlines() if "=" in line)
    except OSError:
        return "autre"
    ids = (data.get("ID", "") + " " + data.get("ID_LIKE", "")).replace('"', "").lower().split()
    if any(i in ("debian", "ubuntu") for i in ids):
        return "debian"
    if any(i in ("fedora", "rhel") for i in ids):
        return "fedora"
    if "arch" in ids:
        return "arch"
    return "autre"


def install_command(statuses: list[DependencyStatus], distro: str | None = None) -> str:
    """Commande à copier pour installer les composants manquants ('' si rien ne manque)."""
    todo = [s.dep for s in statuses if not s.available]
    if not todo:
        return ""
    distro = distro or detect_distribution()
    if distro == "debian":
        return "sudo apt install " + " ".join(dict.fromkeys(d.debian for d in todo))
    if distro == "fedora":
        return "sudo dnf install " + " ".join(dict.fromkeys(d.fedora for d in todo))
    pips = [d.pip for d in todo if d.pip]
    return ("python3 -m pip install " + " ".join(dict.fromkeys(pips))) if pips else ""


def terminal_report(statuses: list[DependencyStatus]) -> str:
    """Texte affiché dans le terminal si l'interface ne peut pas démarrer."""
    lines = ["Telegramor ne peut pas démarrer : composants obligatoires manquants."]
    for s in statuses:
        if not s.available and s.dep.required:
            lines.append(f"  - {s.dep.label} ({s.dep.purpose}) : {s.detail or 'absent'}")
    cmd = install_command([s for s in statuses if s.dep.required])
    if cmd:
        lines += ["", "Commande d'installation :", f"  {cmd}"]
    return "\n".join(lines)
