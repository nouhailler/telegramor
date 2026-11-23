"""Statistiques d'une conversation ou de toute la bibliothèque (calculs SQL + Python)."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from database.db_manager import Database

# Mots vides français (et quelques mots de messagerie) exclus du palmarès des mots
STOPWORDS = set("""
a à ai aie aient aies ait alors as au aucun aussi autre aux avec avoir bon c ça car ce ceci cela celle celles
celui ces cet cette ceux chez ci comme comment d dans de des deja déjà du donc dont du elle elles en encore
est et étaient était été être eu eux fait faire fais il ils j je jusqu l la le les leur leurs lui m ma mais
me même mes moi mon n ne ni non nos notre nous o on ont ou où par pas peu peut plus pour pourquoi qu quand
que quel quelle quelles quels qui quoi s sa sans se ses si sien son sont sous sur t ta te tes toi ton tous
tout toute toutes très tu un une vers vos votre vous y oui ok bien va vais suis es sera c'est j'ai the and
to of is in it you that for http https www com fr youtu be si rien tout aussi alors ah oh eh hein bah
""".split())
WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


@dataclass
class Statistics:
    messages: int = 0
    conversations: int = 0
    participants: int = 0
    first_day: str | None = None
    last_day: str | None = None
    active_days: int = 0
    span_days: int = 0
    per_active_day: float = 0.0
    busiest_day: tuple[str, int] | None = None
    longest_streak: tuple[int, str | None, str | None] = (0, None, None)   # jours, début, fin
    longest_silence: tuple[int, str | None, str | None] = (0, None, None)
    media: dict[str, int] = field(default_factory=dict)
    links: int = 0
    per_month: list[tuple[str, int]] = field(default_factory=list)       # mois continus, zéros inclus
    per_year: list[tuple[str, int]] = field(default_factory=list)
    per_sender: list[tuple[str, int]] = field(default_factory=list)
    per_hour: list[int] = field(default_factory=lambda: [0] * 24)
    per_weekday: list[int] = field(default_factory=lambda: [0] * 7)       # lundi = 0
    heatmap: list[list[int]] = field(default_factory=lambda: [[0] * 24 for _ in range(7)])
    top_words: list[tuple[str, int]] = field(default_factory=list)


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.casefold()) if not unicodedata.combining(c))


_STOP_FOLDED = {_fold(w) for w in STOPWORDS}


def _months_between(first: str, last: str) -> list[str]:
    y, m = int(first[:4]), int(first[5:7])
    ly, lm = int(last[:4]), int(last[5:7])
    out = []
    while (y, m) <= (ly, lm):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def compute(db: Database, conversation_id: str | None = None, sender: str | None = None,
            words_limit: int = 40, words_sample: int = 300_000) -> Statistics:
    """Calcule les statistiques (messages ordinaires uniquement, sans doublons)."""
    c = db.conn
    where = ["m.kind = 'default'", "m.is_duplicate = 0"]
    params: list = []
    if conversation_id:
        where.append("m.conversation_id = ?")
        params.append(conversation_id)
    if sender:
        where.append("m.sender = ?")
        params.append(sender)
    w = " AND ".join(where)
    st = Statistics()
    st.messages, st.conversations, st.participants, st.first_day, st.last_day = c.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT m.conversation_id), COUNT(DISTINCT m.sender), MIN(m.day), MAX(m.day) "
        f"FROM messages m WHERE {w}", params).fetchone()
    if not st.messages:
        return st

    days = {d: n for d, n in c.execute(
        f"SELECT m.day, COUNT(*) FROM messages m WHERE {w} AND m.day IS NOT NULL GROUP BY m.day", params)}
    st.active_days = len(days)
    if days:
        d0, d1 = date.fromisoformat(min(days)), date.fromisoformat(max(days))
        st.span_days = (d1 - d0).days + 1
        st.per_active_day = round(st.messages / st.active_days, 1)
        st.busiest_day = max(days.items(), key=lambda kv: (kv[1], kv[0]))
        ordered = sorted(date.fromisoformat(d) for d in days)
        best = (1, ordered[0], ordered[0])
        start = ordered[0]
        gap = (0, None, None)
        for prev, cur in zip(ordered, ordered[1:]):
            delta = (cur - prev).days
            if delta == 1:
                if (cur - start).days + 1 > best[0]:
                    best = ((cur - start).days + 1, start, cur)
            else:
                start = cur
                if delta - 1 > gap[0]:
                    gap = (delta - 1, prev + timedelta(days=1), cur - timedelta(days=1))
        st.longest_streak = (best[0], best[1].isoformat(), best[2].isoformat())
        st.longest_silence = (gap[0], gap[1].isoformat() if gap[1] else None, gap[2].isoformat() if gap[2] else None)
        month_counts: Counter[str] = Counter()
        for d, n in days.items():
            month_counts[d[:7]] += n
        st.per_month = [(ym, month_counts.get(ym, 0)) for ym in _months_between(min(days), max(days))]
        years: Counter[str] = Counter()
        for d, n in days.items():
            years[d[:4]] += n
        st.per_year = sorted(years.items())
        for d, n in days.items():
            st.per_weekday[date.fromisoformat(d).weekday()] += n

    st.per_sender = [(s or "—", n) for s, n in c.execute(
        f"SELECT m.sender, COUNT(*) FROM messages m WHERE {w} GROUP BY m.sender ORDER BY 2 DESC", params)]

    # heure locale = caractères 12-13 de date_local (ISO avec décalage, tel qu'exporté)
    for day, hour, n in c.execute(
            f"SELECT m.day, CAST(substr(m.date_local, 12, 2) AS INTEGER), COUNT(*) FROM messages m "
            f"WHERE {w} AND m.date_local IS NOT NULL GROUP BY m.day, 2", params):
        if day and hour is not None and 0 <= hour < 24:
            st.per_hour[hour] += n
            st.heatmap[date.fromisoformat(day).weekday()][hour] += n

    st.media = {t: n for t, n in c.execute(
        f"SELECT md.media_type, COUNT(*) FROM medias md JOIN messages m ON m.id = md.message_pk "
        f"WHERE {w} GROUP BY md.media_type ORDER BY 2 DESC", params)}
    st.links = c.execute(f"SELECT COUNT(*) FROM links l JOIN messages m ON m.id = l.message_pk WHERE {w}",
                         params).fetchone()[0]

    words: Counter[str] = Counter()
    display: dict[str, Counter[str]] = {}
    for (text,) in c.execute(f"SELECT m.text FROM messages m WHERE {w} AND m.text != '' "
                             f"ORDER BY m.date_utc DESC LIMIT ?", (*params, words_sample)):
        for raw in WORD_RE.findall(text):
            key = _fold(raw)
            if key in _STOP_FOLDED:
                continue
            words[key] += 1
            display.setdefault(key, Counter())[raw.lower()] += 1
    st.top_words = [(display[k].most_common(1)[0][0], n) for k, n in words.most_common(words_limit)]
    return st


def weekday_label(i: int) -> str:
    return WEEKDAYS[i]
