"""Mise en forme française des dates et des textes (indépendante de la locale système)."""

from __future__ import annotations

import re
from datetime import date, datetime

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
               "sept.", "oct.", "nov.", "déc."]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def day_long(day: str | date | None) -> str:
    """« mardi 16 décembre 2025 »"""
    if day is None:
        return ""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]} {d.year}"


def day_medium(day: str | date | None) -> str:
    """« 16 décembre 2025 »"""
    if day is None:
        return ""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def month_label(ym: str) -> str:
    """« 2026-03 » → « mars 2026 »"""
    y, m = ym.split("-")
    return f"{MOIS[int(m) - 1]} {y}"


def time_hm(iso: str | None) -> str:
    dt = parse_iso(iso)
    return dt.strftime("%H:%M") if dt else ""


def full_datetime(iso: str | None) -> str:
    dt = parse_iso(iso)
    if not dt:
        return ""
    tz = dt.strftime("%z")
    tz = f" (UTC{tz[:3]}:{tz[3:]})" if tz else ""
    return f"{day_long(dt.date())} à {dt.strftime('%H:%M:%S')}{tz}"


def short_date(iso: str | None) -> str:
    """Date compacte pour la liste des conversations : « 12/11/2026 »."""
    dt = parse_iso(iso)
    return dt.strftime("%d/%m/%Y") if dt else ""


def period(first: str | None, last: str | None) -> str:
    a, b = parse_iso(first), parse_iso(last)
    if not a or not b:
        return "—"
    return f"du {day_medium(a.date())} au {day_medium(b.date())}"


_LONG_WORD = re.compile(r"(\S{30,})")


def soft_wrap_html(html: str) -> str:
    """Insère des points de coupure invisibles dans les mots très longs (URL)
    des nœuds texte, afin que QLabel puisse les replier. Les balises sont intactes."""
    parts = re.split(r"(<[^>]+>)", html)
    for i, p in enumerate(parts):
        if p and not p.startswith("<"):
            parts[i] = _LONG_WORD.sub(lambda m: "​".join(m.group(1)[j:j + 12]
                                                              for j in range(0, len(m.group(1)), 12)), p)
    return "".join(parts)


def html_paragraphs(html: str) -> str:
    """Les sauts de ligne bruts du texte assaini deviennent des <br> pour QLabel."""
    return html.replace("\n", "<br>")


def plural(n: int, singular: str, plural_form: str | None = None) -> str:
    word = singular if n <= 1 else (plural_form or singular + "s")
    return f"{n:,} {word}".replace(",", " ")
