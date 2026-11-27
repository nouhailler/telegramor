from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE_HTML = FIXTURES / "reference" / "messages.html"
# Export réel complet (avec médias) : tests ignorés s'il est absent.
REAL_EXPORT = Path.home() / "Téléchargements" / "Telegram Desktop" / "ChatExport_2026-11-23"


def page(history: str, name: str = "Test", extra_after_history: str = "") -> str:
    """Construit une page d'export Telegram minimale autour d'un historique."""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/>
<script src="js/script.js"></script></head>
<body onload="CheckLocation();"><div class="page_wrap">
<div class="page_header"><div class="content"><div class="text bold">{name}</div></div></div>
<div class="page_body chat_page"><div class="history">
{history}
</div>{extra_after_history}</div></div></body></html>"""


def msg(mid: int, inner: str, sender: str | None = "Alice", joined: bool = False,
        title: str = "01.02.2024 10:00:00 UTC+01:00", initials: str | None = None) -> str:
    """Construit un bloc .message.default."""
    cls = "message default clearfix" + (" joined" if joined else "")
    pic = "" if joined else (
        f'<div class="pull_left userpic_wrap"><div class="userpic userpic3">'
        f'<div class="initials">{initials or (sender or "?")[0]}</div></div></div>')
    from_name = f'<div class="from_name">{sender} </div>' if (sender and not joined) else ""
    return (f'<div class="{cls}" id="message{mid}">{pic}<div class="body">'
            f'<div class="pull_right date details" title="{title}">10:00</div>'
            f'{from_name}{inner}</div></div>')


def service(mid: int, text: str) -> str:
    return f'<div class="message service" id="message{mid}"><div class="body details">{text}</div></div>'


@pytest.fixture
def reference_html() -> str:
    return REFERENCE_HTML.read_text(encoding="utf-8")


# La fixture de référence est une copie d'un export réel : elle n'est pas publiée
# dans le dépôt. Sans elle, les tests qui en dépendent sont ignorés (pas en échec).
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if (call.excinfo is not None and not REFERENCE_HTML.exists()
            and call.excinfo.errisinstance(FileNotFoundError)
            and "reference" in str(call.excinfo.value)):
        rep.outcome = "skipped"
        rep.longrepr = (str(item.path), item.location[1] or 0,
                        "Skipped: tests/fixtures/reference/messages.html absent (export réel non publié)")


# --------------------------------------------------------------------------- #
# Bibliothèque synthétique (données entièrement fictives) pour les tests des
# fonctions personnelles, du diagnostic, des exports et de la sauvegarde.
# --------------------------------------------------------------------------- #

def photo_msg(mid: int, href: str, caption: str = "", **kw) -> str:
    cap = f'<div class="text">{caption}</div>' if caption else ""
    return msg(mid, f'<div class="media_wrap clearfix"><a class="photo_wrap clearfix pull_left" href="{href}">'
                    f'<img class="photo" src="{href}" style="width: 260px; height: 173px"/></a></div>{cap}', **kw)


def reply_msg(mid: int, target: int, text: str, **kw) -> str:
    return msg(mid, f'<div class="reply_to details">In reply to <a href="#go_to_message{target}" '
                    f'onclick="return GoToMessage({target})">this message</a></div><div class="text">{text}</div>', **kw)


def build_synthetic_exports(root: Path) -> tuple[Path, Path]:
    """Deux exports fictifs : « Voyage » (fil de réponses, photo) et « Famille »
    (la même photo, octet pour octet, sous un autre nom ; une photo manquante)."""
    a = root / "ExportVoyage"
    (a / "photos").mkdir(parents=True)
    pixels = b"\x89PNG fictive " + bytes(range(256)) * 8
    (a / "photos" / "florence.jpg").write_bytes(pixels)
    (a / "photos" / "sienne.jpg").write_bytes(pixels[::-1])
    (a / "messages.html").write_text(page(
        service(-1, "12 May 2025")
        + msg(1, '<div class="text">On part en Italie en juillet ?</div>', sender="Léa",
              title="12.05.2025 09:00:00 UTC+02:00")
        + reply_msg(2, 1, "Oui, je regarde les trains pour Florence", sender="Marc",
                    title="12.05.2025 09:05:00 UTC+02:00")
        + reply_msg(3, 2, "Le train de nuit est parfait", sender="Léa", title="12.05.2025 09:10:00 UTC+02:00")
        + reply_msg(4, 1, "Je réserve l'appartement", sender="Camille", title="12.05.2025 09:20:00 UTC+02:00")
        + reply_msg(5, 999, "Réponse à un message absent de l'export", sender="Marc",
                    title="13.05.2025 08:00:00 UTC+02:00")
        + service(-2, "7 July 2025")
        + photo_msg(6, "photos/florence.jpg", "Premier matin à Florence", sender="Camille",
                    title="07.07.2025 08:12:30 UTC+02:00")
        + photo_msg(7, "photos/sienne.jpg", "Pause à Sienne", sender="Léa", title="09.07.2025 13:22:10 UTC+02:00")
        + msg(8, '<div class="text">Le lien : <a href="https://exemple.org/carte">https://exemple.org/carte</a></div>',
              sender="Marc", title="09.07.2025 14:00:00 UTC+02:00"),
        name="Voyage en Italie"))
    b = root / "ExportFamille"
    (b / "photos").mkdir(parents=True)
    (b / "photos" / "copie_florence.jpg").write_bytes(pixels)          # doublon exact
    (b / "photos" / "orphelin.jpg").write_bytes(b"jamais reference")   # fichier non référencé
    (b / "messages.html").write_text(page(
        service(-1, "24 December 2025")
        + msg(1, '<div class="text">Joyeux Noël à tous !</div>', sender="Hugo", title="24.12.2025 19:00:00 UTC+01:00")
        + photo_msg(2, "photos/copie_florence.jpg", "Souvenir d'Italie", sender="Inès",
                    title="24.12.2025 19:30:00 UTC+01:00")
        + photo_msg(3, "photos/absente.jpg", "Photo perdue", sender="Hugo", title="25.12.2025 10:00:00 UTC+01:00"),
        name="Famille"))
    return a, b


@pytest.fixture
def synthetic_lib(tmp_path):
    """(db, repo, conversations par nom) d'une bibliothèque synthétique importée."""
    from database.db_manager import Database
    from database.repositories import LibraryRepository
    from importer.import_manager import import_path
    a, b = build_synthetic_exports(tmp_path / "exports")
    db = Database(tmp_path / "lib.sqlite")
    repo = LibraryRepository(db)
    repo.save_import(import_path(a), a)
    repo.save_import(import_path(b), b)
    convs = {c.name: c for c in repo.list_conversations()}
    yield db, repo, convs
    db.close()


@pytest.fixture(scope="session")
def qapp():
    """Application Qt hors écran (QApplication, compatible avec les tests d'interface)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
