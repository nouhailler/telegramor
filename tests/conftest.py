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
