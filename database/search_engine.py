"""Moteur de recherche : plein texte (SQLite FTS5) combiné à des filtres SQL.

Une seule requête interroge toutes les archives et toutes les conversations ;
chaque filtre est facultatif. Sans texte, la recherche porte uniquement sur
les filtres (ex. « toutes les vidéos de Paul en 2024 »).

Syntaxe du texte recherché :
- mots séparés par des espaces : tous doivent être présents (ET) ;
- "entre guillemets" : expression exacte ;
- -mot : exclut les messages contenant ce mot.
La casse et les accents sont ignorés (tokenizer unicode61, remove_diacritics 2).
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from html import escape, unescape

from .db_manager import Database

# Types de contenu proposés dans les filtres → types de médias correspondants
CONTENT_TYPES: dict[str, tuple[str, ...]] = {
    "photo": ("photo",),
    "video": ("video", "video_message"),
    "audio": ("voice", "audio"),
    "voice": ("voice",),
    "file": ("file",),
    "sticker": ("sticker",),
    "animation": ("animation",),
    "location": ("location",),
    "contact": ("contact",),
    "call": ("call",),
    "poll": ("poll",),
}
CONTENT_LABELS = {
    "text": "Texte seul", "photo": "Photos", "video": "Vidéos", "audio": "Audio et vocaux",
    "voice": "Messages vocaux", "file": "Fichiers", "link": "Liens", "sticker": "Autocollants",
    "animation": "GIF", "location": "Positions", "contact": "Contacts", "call": "Appels",
    "poll": "Sondages", "service": "Événements système",
}

MODE_PREFIX = "prefix"     # début de mot : « vac » trouve « vacances »
MODE_WORDS = "words"       # mots entiers
MODE_EXACT = "exact"       # expression exacte
MODE_SEMANTIC = "semantic" # par le sens (nécessite un fournisseur, voir semantic.py)
SEMANTIC_CANDIDATES = 2000

SORT_RELEVANCE = "relevance"
SORT_NEWEST = "newest"
SORT_OLDEST = "oldest"
SORT_CHRONO = "chrono"     # ordre de la conversation (seq), pour la recherche locale

_MARK_OPEN, _MARK_CLOSE = "\x01", "\x02"
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_TOKEN_RE = re.compile(r'(-?)"([^"]*)"|(-?)(\S+)')


@dataclass
class SearchQuery:
    text: str = ""
    mode: str = MODE_PREFIX
    conversation_ids: list[str] | None = None
    archive_ids: list[int] | None = None
    sender: str | None = None
    date_from: str | None = None          # AAAA-MM-JJ inclus (jour local)
    date_to: str | None = None            # AAAA-MM-JJ inclus
    content_type: str | None = None       # clé de CONTENT_LABELS
    has_media: bool | None = None
    has_link: bool | None = None
    filename: str | None = None
    is_reply: bool | None = None          # réponse à un autre message (citation)
    sort: str = SORT_RELEVANCE

    def is_empty(self) -> bool:
        return not (self.text.strip() or self.sender or self.date_from or self.date_to
                    or self.content_type or self.has_media is not None or self.has_link is not None
                    or self.filename or self.is_reply is not None)


@dataclass
class SearchHit:
    pk: int
    conversation_id: str
    conversation_name: str
    archive_name: str
    seq: int
    message_id: int
    kind: str
    sender: str | None
    date_local: str | None
    snippet_html: str                      # extrait assaini, termes entre <mark>
    media_types: list[str] = field(default_factory=list)
    has_link: bool = False


@dataclass
class SearchPage:
    hits: list[SearchHit]
    total: int
    offset: int
    limit: int
    elapsed_ms: float
    terms: list[str]                       # termes positifs, pour le surlignage

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.hits) < self.total


class SearchError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Construction de l'expression FTS5
# --------------------------------------------------------------------------- #

def _quote(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def parse_terms(text: str) -> tuple[list[tuple[str, bool]], list[str]]:
    """Découpe le texte en [(élément, est_une_expression)] positifs et en mots exclus."""
    positive: list[tuple[str, bool]] = []
    negative: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        if m.group(2) is not None:                      # "expression"
            neg, chunk, phrase = m.group(1), m.group(2), True
        else:
            neg, chunk, phrase = m.group(3), m.group(4), False
        words = _WORD_RE.findall(chunk)
        if not words:
            continue
        if neg:
            negative.extend(words)
        elif phrase or len(words) > 1:
            positive.append((" ".join(words), True))    # « l'Italie » → expression « l Italie »
        else:
            positive.append((words[0], False))
    return positive, negative


def build_match(text: str, mode: str) -> tuple[str | None, list[str]]:
    """Retourne (expression MATCH limitée à la colonne text, termes à surligner)."""
    if mode == MODE_EXACT:
        words = _WORD_RE.findall(text)
        if not words:
            return None, []
        phrase = " ".join(words)
        return f"text : ({_quote(phrase)})", [phrase]
    positive, negative = parse_terms(text)
    if not positive:
        return None, []
    parts = []
    for term, is_phrase in positive:
        q = _quote(term)
        if mode == MODE_PREFIX and not is_phrase:
            q += "*"
        parts.append(q)
    expr = " AND ".join(parts)
    for w in negative:
        expr += f" NOT {_quote(w)}"
    return f"text : ({expr})", [t for t, _ in positive]


def _mark_substring(text: str, needle: str) -> str:
    """Surligne une sous-chaîne (insensible à la casse) : utilisé pour les noms de fichiers."""
    i = text.casefold().find(needle.casefold())
    if i < 0 or not needle:
        return escape(text)
    j = i + len(needle)
    return escape(text[:i]) + "<mark>" + escape(text[i:j]) + "</mark>" + escape(text[j:])


def _snippet_to_html(raw: str) -> str:
    return escape(raw).replace(_MARK_OPEN, "<mark>").replace(_MARK_CLOSE, "</mark>")


# --------------------------------------------------------------------------- #
# Surlignage côté interface (insensible à la casse et aux accents)
# --------------------------------------------------------------------------- #

def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.casefold()) if not unicodedata.combining(c))


def highlight_spans(text: str, terms: list[str], prefix: bool = True) -> list[tuple[int, int]]:
    """Positions [début, fin) des occurrences des termes dans `text`."""
    if not terms or not text:
        return []
    # Correspondance caractère replié → caractère d'origine (le repliage peut
    # changer la longueur, ex. « ß » → « ss »)
    folded_chars: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        f = _fold(ch)
        folded_chars.append(f)
        origin.extend([i] * len(f))
    folded = "".join(folded_chars)
    spans: list[tuple[int, int]] = []
    for term in terms:
        words = [_fold(w) for w in _WORD_RE.findall(term)]
        if not words:
            continue
        pat = r"\b" + r"\W+".join(re.escape(w) for w in words) + (r"\w*" if prefix else r"\b")
        for m in re.finditer(pat, folded):
            if m.end() > m.start():
                spans.append((origin[m.start()], origin[m.end() - 1] + 1))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    return merged


def highlight_html(html: str, terms: list[str], open_tag: str, close_tag: str = "</span>",
                   prefix: bool = True) -> str:
    """Surligne les termes dans les nœuds texte d'un HTML assaini (balises intactes)."""
    if not terms:
        return html
    parts = re.split(r"(<[^>]+>)", html)
    out = []
    for p in parts:
        if not p or p.startswith("<"):
            out.append(p)
            continue
        # Les entités (&amp;…) ne doivent pas être coupées : on travaille sur le texte décodé
        plain = unescape(p)
        spans = highlight_spans(plain, terms, prefix)
        if not spans:
            out.append(p)
            continue
        buf, last = [], 0
        for s, e in spans:
            buf.append(escape(plain[last:s], quote=False))
            buf.append(open_tag + escape(plain[s:e], quote=False) + close_tag)
            last = e
        buf.append(escape(plain[last:], quote=False))
        out.append("".join(buf))
    return "".join(out)


# --------------------------------------------------------------------------- #
# Moteur
# --------------------------------------------------------------------------- #

class SearchEngine:
    def __init__(self, db: Database) -> None:
        self.conn = db.conn
        self.semantic = None          # fournisseur SemanticProvider optionnel

    @property
    def semantic_available(self) -> bool:
        return self.semantic is not None and self.semantic.is_ready()

    def senders(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT name FROM participants GROUP BY name ORDER BY SUM(message_count) DESC")]

    def search(self, q: SearchQuery, offset: int = 0, limit: int = 50) -> SearchPage:
        t0 = time.perf_counter()
        semantic_scores: dict[int, float] | None = None
        if q.mode == MODE_SEMANTIC:
            if not self.semantic_available:
                raise SearchError("La recherche sémantique n'est pas installée.")
            semantic_scores = dict(self.semantic.search(q.text, SEMANTIC_CANDIDATES)) if q.text.strip() else {}
            match, terms = None, []
        else:
            match, terms = build_match(q.text, q.mode) if q.text.strip() else (None, [])
        if semantic_scores is not None and not semantic_scores and q.text.strip():
            return SearchPage([], 0, offset, limit, 0.0, [])
        if q.text.strip() and match is None and semantic_scores is None and not q.filename:
            # texte sans aucun mot exploitable (ex. ponctuation seule)
            return SearchPage([], 0, offset, limit, 0.0, [])

        where: list[str] = ["m.kind != 'date_separator'", "m.is_duplicate = 0"]
        params: list = []
        if match:
            # CROSS JOIN impose l'index plein texte comme table directrice : sans cela,
            # SQLite peut parcourir un index de filtre (ex. expéditeur) et réévaluer
            # la recherche FTS pour chaque ligne (des minutes sur 200 000 messages).
            src = "messages_fts f CROSS JOIN messages m ON m.id = f.rowid"
            where.insert(0, "messages_fts MATCH ?")
            params.append(match)
            snippet = (f"snippet(messages_fts, 0, '{_MARK_OPEN}', '{_MARK_CLOSE}', '…', 24)")
            rank = "bm25(messages_fts)"
        else:
            src = "messages m"
            snippet = "substr(m.text, 1, 220)"
            rank = "0"

        if semantic_scores:
            where.append(f"m.id IN ({','.join(str(int(pk)) for pk in semantic_scores)})")
        if q.conversation_ids:
            where.append(f"m.conversation_id IN ({','.join('?' * len(q.conversation_ids))})")
            params.extend(q.conversation_ids)
        if q.archive_ids:
            where.append(f"m.archive_id IN ({','.join('?' * len(q.archive_ids))})")
            params.extend(q.archive_ids)
        if q.sender:
            where.append("m.sender = ?")
            params.append(q.sender)
        if q.date_from:
            where.append("m.day >= ?")
            params.append(q.date_from)
        if q.date_to:
            where.append("m.day <= ?")
            params.append(q.date_to)
        if q.has_media is not None:
            where.append("m.has_media = ?")
            params.append(int(q.has_media))
        if q.has_link is not None:
            where.append("m.has_link = ?")
            params.append(int(q.has_link))
        if q.is_reply is not None:
            where.append("m.reply_to_message_id IS NOT NULL" if q.is_reply else "m.reply_to_message_id IS NULL")
        ct = q.content_type
        if ct == "text":
            where.append("m.kind = 'default' AND m.has_media = 0 AND m.text != ''")
        elif ct == "link":
            where.append("m.has_link = 1")
        elif ct == "service":
            where.append("m.kind = 'service'")
        elif ct in CONTENT_TYPES:
            types = CONTENT_TYPES[ct]
            where.append(f"EXISTS (SELECT 1 FROM medias x WHERE x.message_pk = m.id "
                         f"AND x.media_type IN ({','.join('?' * len(types))}))")
            params.extend(types)
        elif ct:
            raise SearchError(f"Type de contenu inconnu : {ct}")
        if q.filename:
            where.append("EXISTS (SELECT 1 FROM medias x WHERE x.message_pk = m.id AND "
                         "(x.file_path LIKE ? ESCAPE '\\' OR x.title LIKE ? ESCAPE '\\'))")
            like = "%" + q.filename.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params.extend([like, like])

        sql_where = " AND ".join(where)
        if semantic_scores and q.sort == SORT_RELEVANCE:
            # classement du fournisseur conservé : CASE … WHEN id THEN rang
            ranked = sorted(semantic_scores, key=lambda pk: -semantic_scores[pk])
            rank = "CASE m.id " + " ".join(f"WHEN {int(pk)} THEN {i}" for i, pk in enumerate(ranked)) + " END"
        order = {
            SORT_NEWEST: "m.date_utc DESC, m.seq DESC",
            SORT_OLDEST: "m.date_utc ASC, m.seq ASC",
            SORT_CHRONO: "m.conversation_id, m.seq",
        }.get(q.sort, f"{rank}, m.date_utc DESC" if (match or semantic_scores) else "m.date_utc DESC, m.seq DESC")

        try:
            total = self.conn.execute(f"SELECT COUNT(*) FROM {src} WHERE {sql_where}", params).fetchone()[0]
            rows = self.conn.execute(
                f"""SELECT m.id, m.conversation_id, c.name, a.name, m.seq, m.message_id, m.kind, m.sender,
                           m.date_local, {snippet}, m.has_link, m.text, m.service_text,
                           (SELECT GROUP_CONCAT(media_type) FROM medias x WHERE x.message_pk = m.id),
                           (SELECT GROUP_CONCAT(COALESCE(x.title, x.file_path), ' · ')
                              FROM medias x WHERE x.message_pk = m.id)
                    FROM {src}
                    JOIN conversations c ON c.id = m.conversation_id
                    JOIN archives a ON a.id = m.archive_id
                    WHERE {sql_where} ORDER BY {order} LIMIT ? OFFSET ?""",
                (*params, limit, offset)).fetchall()
        except Exception as exc:  # erreur de syntaxe FTS improbable mais possible
            raise SearchError(str(exc)) from exc

        hits = []
        for r in rows:
            media = r[13].split(",") if r[13] else []
            if match:
                snip = _snippet_to_html(r[9] or "")
            else:
                base = r[11] or r[12] or ""
                snip = escape(base[:220] + ("…" if len(base) > 220 else ""))
                if q.filename and r[14]:
                    snip = _mark_substring(r[14], q.filename) + (("<br>" + snip) if snip else "")
            if not snip and r[14]:
                snip = escape(r[14])
            hits.append(SearchHit(
                pk=r[0], conversation_id=r[1], conversation_name=r[2], archive_name=r[3], seq=r[4],
                message_id=r[5], kind=r[6], sender=r[7], date_local=r[8], snippet_html=snip,
                media_types=media, has_link=bool(r[10])))
        return SearchPage(hits, total, offset, limit, (time.perf_counter() - t0) * 1000, terms)

    def matching_seqs(self, q: SearchQuery, limit: int = 20000) -> tuple[list[int], list[str]]:
        """Positions (seq) des résultats d'une recherche dans UNE conversation, dans l'ordre."""
        if not q.conversation_ids or len(q.conversation_ids) != 1:
            raise SearchError("matching_seqs exige exactement une conversation")
        match, terms = build_match(q.text, q.mode) if q.text.strip() else (None, [])
        if match is None:
            return [], []
        rows = self.conn.execute(
            "SELECT m.seq FROM messages_fts f CROSS JOIN messages m ON m.id = f.rowid "
            "WHERE messages_fts MATCH ? AND m.conversation_id = ? AND m.kind != 'date_separator' "
            "AND m.is_duplicate = 0 "
            "ORDER BY m.seq LIMIT ?", (match, q.conversation_ids[0], limit)).fetchall()
        return [r[0] for r in rows], terms
