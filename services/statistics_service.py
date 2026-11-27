"""Statistiques d'une conversation ou de toute la bibliothèque (calculs SQL + Python)."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

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
    top_bigrams: list[tuple[str, int]] = field(default_factory=list)    # groupes de deux mots
    top_trigrams: list[tuple[str, int]] = field(default_factory=list)   # groupes de trois mots
    avg_length: float = 0.0                                             # caractères par message texte
    words_sampled: int = 0                                              # messages analysés pour les mots
    date_from: str | None = None
    date_to: str | None = None


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
            words_limit: int = 40, words_sample: int = 300_000, date_from: str | None = None,
            date_to: str | None = None, excluded_words: Iterable[str] = (), ngrams_limit: int = 20) -> Statistics:
    """Calcule les statistiques (messages ordinaires uniquement, sans doublons).

    date_from / date_to : jours locaux inclus (AAAA-MM-JJ). words_limit = 0 : sans analyse lexicale.
    """
    c = db.conn
    where = ["m.kind = 'default'", "m.is_duplicate = 0"]
    params: list = []
    if conversation_id:
        where.append("m.conversation_id = ?")
        params.append(conversation_id)
    if sender:
        where.append("m.sender = ?")
        params.append(sender)
    if date_from:
        where.append("m.day >= ?")
        params.append(date_from)
    if date_to:
        where.append("m.day <= ?")
        params.append(date_to)
    w = " AND ".join(where)
    st = Statistics(date_from=date_from, date_to=date_to)
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

    st.avg_length = round(c.execute(f"SELECT AVG(LENGTH(m.text)) FROM messages m WHERE {w} AND m.text != ''",
                                    params).fetchone()[0] or 0.0, 1)
    if words_limit <= 0:
        return st

    stop = _STOP_FOLDED | {_fold(x.strip()) for x in excluded_words if x.strip()}
    words: Counter[str] = Counter()
    bigrams: Counter[tuple[str, str]] = Counter()
    trigrams: Counter[tuple[str, str, str]] = Counter()
    display: dict[str, Counter[str]] = {}
    for (text,) in c.execute(f"SELECT m.text FROM messages m WHERE {w} AND m.text != '' "
                             f"ORDER BY m.date_utc DESC LIMIT ?", (*params, words_sample)):
        st.words_sampled += 1
        kept: list[str] = []          # mots significatifs consécutifs (une coupure à chaque mot courant)
        for raw in WORD_RE.findall(text):
            key = _fold(raw)
            if key in stop:
                kept.append("")
                continue
            words[key] += 1
            display.setdefault(key, Counter())[raw.lower()] += 1
            kept.append(key)
        for i in range(len(kept) - 1):
            a, b = kept[i], kept[i + 1]
            if a and b and a != b:
                bigrams[(a, b)] += 1
                if i + 2 < len(kept) and kept[i + 2] and kept[i + 2] not in (a, b):
                    trigrams[(a, b, kept[i + 2])] += 1

    def show(key: str) -> str:
        return display[key].most_common(1)[0][0]

    st.top_words = [(show(k), n) for k, n in words.most_common(words_limit)]
    st.top_bigrams = [(" ".join(map(show, k)), n) for k, n in bigrams.most_common(ngrams_limit) if n > 1]
    st.top_trigrams = [(" ".join(map(show, k)), n) for k, n in trigrams.most_common(ngrams_limit) if n > 1]
    return st


# --------------------------------------------------------------------------- #
# Comparaison de deux portées (conversations, années, périodes)
# --------------------------------------------------------------------------- #

@dataclass
class Scope:
    label: str
    conversation_id: str | None = None
    sender: str | None = None
    date_from: str | None = None
    date_to: str | None = None


@dataclass
class Comparison:
    a: Scope
    b: Scope
    stats_a: Statistics
    stats_b: Statistics
    rows: list[tuple[str, str, str, str]]         # indicateur, A, B, écart (normalisé)
    hours_pct: tuple[list[float], list[float]]
    weekdays_pct: tuple[list[float], list[float]]


def _span(st: Statistics) -> int:
    """Durée de la période en jours (période demandée si fournie, sinon période d'activité)."""
    if st.date_from and st.date_to:
        return (date.fromisoformat(st.date_to) - date.fromisoformat(st.date_from)).days + 1
    return st.span_days


def _pct(values: list[int]) -> list[float]:
    total = sum(values) or 1
    return [round(100 * v / total, 1) for v in values]


def _fmt_num(x: float) -> str:
    """Nombre à la française : espace fine insécable pour les milliers, virgule décimale."""
    nb = "\u202f"
    if isinstance(x, float) and not x.is_integer():
        digits = 2 if abs(x) < 1 else 1
        return f"{x:,.{digits}f}".replace(",", nb).replace(".", ",")
    return f"{int(x):,}".replace(",", nb)


def _delta(a: float, b: float) -> str:
    if not a and not b:
        return "="
    if not a:
        return "nouveau"
    d = 100 * (b - a) / a
    return "=" if abs(d) < 0.5 else f"{d:+.0f} %"


def compare(db: Database, a: Scope, b: Scope) -> Comparison:
    """Compare deux portées. Les volumes sont ramenés à la durée de chaque période
    (messages par jour) pour que des périodes de longueurs différentes restent comparables."""
    sa = compute(db, a.conversation_id, a.sender, words_limit=0, date_from=a.date_from, date_to=a.date_to)
    sb = compute(db, b.conversation_id, b.sender, words_limit=0, date_from=b.date_from, date_to=b.date_to)
    rows: list[tuple[str, str, str, str]] = []

    def add(label: str, va: float, vb: float, normalized: bool = True) -> None:
        rows.append((label, _fmt_num(va), _fmt_num(vb), _delta(va, vb) if normalized else ""))

    span_a, span_b = _span(sa), _span(sb)
    media_a, media_b = sum(sa.media.values()), sum(sb.media.values())
    add("Durée de la période (jours)", span_a, span_b, normalized=False)
    add("Messages", sa.messages, sb.messages, normalized=False)
    add("Messages par jour (sur la période)", sa.messages / span_a if span_a else 0.0,
        sb.messages / span_b if span_b else 0.0)
    add("Jours actifs", sa.active_days, sb.active_days, normalized=False)
    add("Part de jours actifs (%)", 100 * sa.active_days / span_a if span_a else 0.0,
        100 * sb.active_days / span_b if span_b else 0.0)
    add("Messages par jour actif", sa.per_active_day, sb.per_active_day)
    add("Participants actifs", sa.participants, sb.participants)
    add("Médias", media_a, media_b, normalized=False)
    add("Médias pour 100 messages", 100 * media_a / sa.messages if sa.messages else 0.0,
        100 * media_b / sb.messages if sb.messages else 0.0)
    add("Liens pour 100 messages", 100 * sa.links / sa.messages if sa.messages else 0.0,
        100 * sb.links / sb.messages if sb.messages else 0.0)
    add("Longueur moyenne d'un message (caractères)", sa.avg_length, sb.avg_length)
    peak = lambda v: f"{max(range(24), key=lambda h: v[h])} h" if any(v) else "—"  # noqa: E731
    rows.append(("Heure la plus active", peak(sa.per_hour), peak(sb.per_hour), ""))
    wd = lambda v: WEEKDAYS[max(range(7), key=lambda d: v[d])] if any(v) else "—"  # noqa: E731
    rows.append(("Jour de la semaine le plus actif", wd(sa.per_weekday), wd(sb.per_weekday), ""))
    return Comparison(a, b, sa, sb, rows, (_pct(sa.per_hour), _pct(sb.per_hour)),
                      (_pct(sa.per_weekday), _pct(sb.per_weekday)))


# --------------------------------------------------------------------------- #
# Export CSV
# --------------------------------------------------------------------------- #

def to_csv(st: Statistics, scope_label: str) -> str:
    """Toutes les séries d'une analyse, avec leur unité, dans un CSV (séparateur « ; », UTF-8)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Portée", scope_label])
    w.writerow(["Période", st.date_from or st.first_day or "", st.date_to or st.last_day or ""])
    w.writerow([])
    w.writerow(["Indicateur", "Valeur", "Unité"])
    for label, value, unit in (("Messages", st.messages, "messages"), ("Conversations", st.conversations, ""),
                               ("Participants", st.participants, "personnes"),
                               ("Jours actifs", st.active_days, "jours"), ("Durée", st.span_days, "jours"),
                               ("Messages par jour actif", st.per_active_day, "messages/jour"),
                               ("Longueur moyenne", st.avg_length, "caractères"), ("Liens", st.links, "liens")):
        w.writerow([label, value, unit])

    def section(title: str, header: list[str], rows) -> None:
        w.writerow([])
        w.writerow([title])
        w.writerow(header)
        w.writerows(rows)

    section("Messages par mois", ["Mois", "Messages"], st.per_month)
    section("Messages par année", ["Année", "Messages"], st.per_year)
    section("Messages par heure", ["Heure", "Messages"], [(f"{h:02d}h", n) for h, n in enumerate(st.per_hour)])
    section("Messages par jour de la semaine", ["Jour", "Messages"],
            [(WEEKDAYS[i], n) for i, n in enumerate(st.per_weekday)])
    section("Expéditeurs", ["Expéditeur", "Messages"], st.per_sender)
    section("Médias", ["Type", "Nombre"], st.media.items())
    section("Carte jour × heure", ["Jour"] + [f"{h:02d}h" for h in range(24)],
            [[WEEKDAYS[d]] + st.heatmap[d] for d in range(7)])
    section(f"Mots les plus fréquents ({st.words_sampled} messages analysés)", ["Mot", "Occurrences"], st.top_words)
    section("Groupes de deux mots", ["Expression", "Occurrences"], st.top_bigrams)
    section("Groupes de trois mots", ["Expression", "Occurrences"], st.top_trigrams)
    return buf.getvalue()


def weekday_label(i: int) -> str:
    return WEEKDAYS[i]
