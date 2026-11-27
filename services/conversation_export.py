"""Export de messages (conversation, période, sélection, résultats de recherche,
collection) en HTML autonome imprimable, Markdown, JSON ou PDF.

Confidentialité : seules les données provenant de Telegram sont exportées.
Les données personnelles Telegramor (favoris, notes, collections) n'y figurent
jamais ; leur export est une action distincte (« Mon espace » › Exporter).

Sécurité : tout le contenu est échappé (aucun HTML de l'export n'est recopié
tel quel, aucun script) ; les médias éventuellement inclus sont COPIÉS sans
jamais écraser un fichier existant (logique de services/media_export.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Callable, Iterable

from database.models import MessageRow
from database.repositories import LibraryRepository, media_label
from services import media_export
from ui.formatting import day_long, full_datetime, time_hm

FMT_HTML, FMT_MARKDOWN, FMT_JSON, FMT_PDF = "html", "md", "json", "pdf"
FORMATS = {FMT_HTML: "Page HTML imprimable (.html)", FMT_PDF: "Document PDF (.pdf)",
           FMT_MARKDOWN: "Markdown (.md)", FMT_JSON: "JSON (.json)"}
EXTENSIONS = {FMT_HTML: ".html", FMT_PDF: ".pdf", FMT_MARKDOWN: ".md", FMT_JSON: ".json"}
CHUNK = 2000


@dataclass
class ExportOutcome:
    path: Path
    messages: int = 0
    media_copied: int = 0
    media_missing: int = 0
    media_dir: Path | None = None
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Collecte des messages
# --------------------------------------------------------------------------- #

def gather_conversation(repo: LibraryRepository, conversation_id: str, day_from: str | None = None,
                        day_to: str | None = None) -> list[MessageRow]:
    """Messages (hors doublons) d'une conversation, éventuellement limités à une période (jours inclus)."""
    bounds = repo.seq_bounds(conversation_id)
    if not bounds:
        return []
    out: list[MessageRow] = []
    seq = bounds[0] - 1
    while True:
        chunk = repo.messages_after(conversation_id, seq, CHUNK)
        if not chunk:
            break
        for m in chunk:
            if m.kind == "date_separator":
                continue
            if day_from and (m.day or "") < day_from:
                continue
            if day_to and (m.day or "9999") > day_to:
                return out
            out.append(m)
        seq = chunk[-1].seq
    return out


def gather_keys(repo: LibraryRepository, keys: Iterable[tuple[str, int]]) -> list[MessageRow]:
    """Messages désignés par (conversation, identifiant Telegram), dans l'ordre chronologique.
    Les messages absents de la bibliothèque sont ignorés."""
    out: list[MessageRow] = []
    seen: set[tuple[str, int]] = set()
    for conv_id, mid in keys:
        if (conv_id, mid) in seen:
            continue
        seen.add((conv_id, mid))
        seq = repo.seq_of_message(conv_id, mid)
        if seq is not None:
            m = repo.message_by_seq(conv_id, seq)
            if m is not None:
                out.append(m)
    out.sort(key=lambda m: (m.date_local or "", m.conversation_id, m.seq))
    return out


# --------------------------------------------------------------------------- #
# Médias inclus
# --------------------------------------------------------------------------- #

def _copy_media(messages: list[MessageRow], media_dir: Path,
                progress: Callable[[int, int, str], bool] | None) -> tuple[dict[int, Path], int, int, list[str]]:
    medias = [md for m in messages for md in m.media]
    plans, result = media_export.plan_copies(medias, media_dir, media_export.ExportOptions())
    by_source = {p.source: p.target for p in plans}
    media_export.execute(plans, result, media_export.ExportOptions(), progress)
    copied = set(result.copied)
    mapping: dict[int, Path] = {}
    for md in medias:
        if md.file_available:
            target = by_source.get(md.abs_file.resolve())
            if target in copied:
                mapping[md.id] = target
    return mapping, len(result.copied), result.missing, [f"{n} : {e}" for n, e in result.errors]


# --------------------------------------------------------------------------- #
# Rendus
# --------------------------------------------------------------------------- #

def _media_name(md) -> str:
    return md.title or (Path(md.file_path).name if md.file_path else "") or (media_label(md.media_type) or "Média")


def _rel(target: Path, base: Path) -> str:
    try:
        return target.relative_to(base).as_posix()
    except ValueError:
        return target.as_posix()


def _participants(messages: list[MessageRow]) -> list[str]:
    seen: dict[str, int] = {}
    for m in messages:
        if m.sender and m.kind == "default":
            seen[m.sender] = seen.get(m.sender, 0) + 1
    return [s for s, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


def _period(messages: list[MessageRow]) -> str:
    days = [m.day for m in messages if m.day]
    if not days:
        return ""
    a, b = min(days), max(days)
    return day_long(a) if a == b else f"du {day_long(a)} au {day_long(b)}"


def to_json(messages: list[MessageRow], title: str, media_map: dict[int, Path] | None = None,
            base: Path | None = None, conv_names: dict[str, str] | None = None) -> str:
    media_map = media_map or {}
    names = conv_names or {}
    data = {
        "format": "telegramor-export", "version": 1, "title": title,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "source": "Données Telegram importées dans Telegramor (sans données personnelles Telegramor)",
        "participants": _participants(messages),
        "messages": [{
            "conversation_id": m.conversation_id, "conversation": names.get(m.conversation_id),
            "id": m.message_id, "kind": m.kind, "date": m.date_local,
            "sender": m.sender, "text": m.text, "service_text": m.service_text,
            "reply_to": m.reply_to_message_id, "forwarded_from": m.forwarded_from, "edited": m.edited_raw,
            "media": [{"type": md.media_type, "name": _media_name(md), "original_path": md.file_path,
                       "exported_file": _rel(media_map[md.id], base) if md.id in media_map and base else None,
                       "available": md.file_available} for md in m.media],
            "links": m.links,
            "reactions": [{"emoji": r.emoji, "count": r.count} for r in m.reactions if not r.is_custom_emoji],
        } for m in messages],
    }
    return json.dumps(data, ensure_ascii=False, indent=1)


def to_markdown(messages: list[MessageRow], title: str, media_map: dict[int, Path] | None = None,
                base: Path | None = None, conv_names: dict[str, str] | None = None) -> str:
    media_map = media_map or {}
    names = conv_names or {}
    out = [f"# {title}", ""]
    if messages:
        out += [f"*{_period(messages)} · {len(messages)} messages · "
                f"participants : {', '.join(_participants(messages)) or '—'}*", ""]
    day = None
    multi = len({m.conversation_id for m in messages}) > 1
    for m in messages:
        if m.day != day:
            day = m.day
            out += ["", f"## {day_long(day) if day else 'Date inconnue'}", ""]
        if m.kind == "service":
            out += [f"_— {m.service_text or m.text} —_", ""]
            continue
        head = f"**{time_hm(m.date_local)} · {m.sender or '—'}**"
        if multi:
            head += f" _({names.get(m.conversation_id, m.conversation_id)})_"
        if m.forwarded_from:
            head += f" ↪ transféré de {m.forwarded_from}"
        out.append(head)
        if m.reply is not None:
            out.append(f"> En réponse à {m.reply.sender or 'un message'} : {(m.reply.text or '')[:120]}")
        if m.text:
            out += [line if line.strip() else "" for line in m.text.split("\n")]
        for md in m.media:
            name = _media_name(md)
            if md.id in media_map and base:
                rel = _rel(media_map[md.id], base)
                out.append(f"![{name}]({rel})" if md.media_type == "photo" else f"📎 [{name}]({rel})")
            else:
                out.append(f"📎 {media_label(md.media_type) or 'Pièce jointe'} : {name}"
                           + ("" if md.file_available else " (fichier absent de l'export)"))
        out.append("")
    return "\n".join(out).strip() + "\n"


_CSS = """
:root { --text:#202b3c; --muted:#738096; --line:#e3e9f1; --accent:#2a6db8; --bubble:#f5f7fb; }
* { box-sizing: border-box; }
body { font-family: Inter, "Noto Sans", "Segoe UI", sans-serif; color: var(--text); margin: 0 auto;
       max-width: 820px; padding: 32px 24px; line-height: 1.45; font-size: 11pt; background: #fff; }
header { border-bottom: 2px solid var(--line); margin-bottom: 18px; padding-bottom: 12px; }
header h1 { font-size: 20pt; margin: 0 0 4px; }
header p { margin: 2px 0; color: var(--muted); font-size: 9.5pt; }
.day { text-align: center; color: var(--muted); font-size: 9pt; font-weight: 600; margin: 22px 0 10px;
       text-transform: capitalize; break-after: avoid; page-break-after: avoid; }
.day span { background: #fff; padding: 0 10px; }
.day::before { content: ""; display: block; border-top: 1px solid var(--line); margin-bottom: -0.7em; }
.msg { background: var(--bubble); border: 1px solid var(--line); border-radius: 10px; padding: 8px 12px;
       margin: 6px 0; break-inside: avoid; page-break-inside: avoid; }
.meta { font-size: 9pt; color: var(--muted); margin-bottom: 2px; }
.meta b { color: var(--text); }
.conv { color: var(--accent); }
.quote { border-left: 3px solid var(--accent); padding: 2px 8px; margin: 4px 0; font-size: 9.5pt;
         color: var(--muted); }
.text { white-space: pre-wrap; overflow-wrap: anywhere; }
.att { font-size: 9.5pt; margin-top: 4px; }
.att img { max-width: 100%; max-height: 360px; border-radius: 6px; display: block; margin-top: 4px; }
.missing { color: #c9463f; }
.service { text-align: center; color: var(--muted); font-size: 9pt; font-style: italic; margin: 8px 0; }
a { color: var(--accent); overflow-wrap: anywhere; }
footer { margin-top: 28px; border-top: 1px solid var(--line); padding-top: 8px; color: var(--muted);
         font-size: 8.5pt; }
.hint { background: #eaf2fc; border-radius: 8px; padding: 8px 12px; font-size: 9.5pt; margin-bottom: 14px; }
@page { size: A4; margin: 16mm 14mm 18mm; @bottom-center { content: counter(page) " / " counter(pages);
        font-size: 8pt; color: #738096; } }
@media print { body { padding: 0; max-width: none; } .hint { display: none; } a { color: inherit; } }
"""


def to_html(messages: list[MessageRow], title: str, media_map: dict[int, Path] | None = None,
            base: Path | None = None, print_hint: bool = False, for_qt: bool = False,
            conv_names: dict[str, str] | None = None) -> str:
    """HTML autonome (CSS intégré, aucun script). for_qt : variante compatible QTextDocument (PDF)."""
    media_map = media_map or {}
    multi = len({m.conversation_id for m in messages}) > 1
    names = conv_names or {}
    parts = [f"<header><h1>{escape(title)}</h1>"]
    if messages:
        parts.append(f"<p>{escape(_period(messages))} · {len(messages)} messages</p>")
        parts.append(f"<p>Participants : {escape(', '.join(_participants(messages)) or '—')}</p>")
    parts.append(f"<p>Exporté le {escape(full_datetime(datetime.now().astimezone().isoformat()))} "
                 f"avec Telegramor — données issues de l'export Telegram, sans notes personnelles.</p></header>")
    if print_hint:
        parts.append("<div class='hint'>Pour imprimer ou enregistrer en PDF : Ctrl+P "
                     "(la mise en page A4 est prête).</div>")
    day = None
    for m in messages:
        if m.day != day:
            day = m.day
            label = escape(day_long(day) if day else "Date inconnue")
            parts.append(f"<h3 class='day' align='center'>{label}</h3>" if for_qt
                         else f"<div class='day'><span>{label}</span></div>")
        if m.kind == "service":
            parts.append(f"<p class='service' align='center'>{escape(m.service_text or m.text)}</p>")
            continue
        meta = f"<b>{escape(m.sender or '—')}</b> · {escape(time_hm(m.date_local))}"
        if multi:
            meta += f" · <span class='conv'>{escape(names.get(m.conversation_id, m.conversation_id))}</span>"
        if m.edited_raw:
            meta += " · modifié"
        if m.forwarded_from:
            meta += f" · ↪ transféré de {escape(m.forwarded_from)}"
        body = [f"<div class='meta'>{meta}</div>"]
        if m.reply is not None:
            body.append(f"<div class='quote'>{escape(m.reply.sender or 'Message cité')} : "
                        f"{escape((m.reply.text or '')[:160])}</div>")
        if m.text:
            txt = escape(m.text)
            if for_qt:
                txt = txt.replace("\n", "<br>")
            for url in m.links:
                e = escape(url)
                if url.startswith(("http://", "https://")) and e in txt:
                    txt = txt.replace(e, f"<a href=\"{e}\">{e}</a>", 1)
            body.append(f"<div class='text'>{txt}</div>")
        for md in m.media:
            name = escape(_media_name(md))
            label = escape(media_label(md.media_type) or "Pièce jointe")
            if md.id in media_map and base is not None:
                rel = escape(_rel(media_map[md.id], base))
                src = escape(media_map[md.id].as_uri()) if for_qt else rel
                if md.media_type == "photo":
                    img = (f"<img src=\"{src}\" width=\"420\">" if for_qt else f"<img src=\"{rel}\" alt=\"{name}\">")
                    body.append(f"<div class='att'>{img}</div>")
                else:
                    body.append(f"<div class='att'>{label} : <a href=\"{rel}\">{name}</a></div>")
            else:
                miss = "" if md.file_available else " <span class='missing'>(fichier absent de l'export)</span>"
                body.append(f"<div class='att'>{label} : {name}{miss}</div>")
        if m.reactions:
            body.append("<div class='att'>" + " ".join(
                f"{escape(r.emoji)} {r.count}" for r in m.reactions if not r.is_custom_emoji) + "</div>")
        if for_qt:
            parts.append("<table width='100%' cellpadding='6' style='margin:4px 0; background:#f5f7fb; "
                         "border:1px solid #e3e9f1'><tr><td>" + "".join(body) + "</td></tr></table>")
        else:
            parts.append("<div class='msg'>" + "".join(body) + "</div>")
    parts.append("<footer>Telegramor — explorateur local d'archives Telegram. Ce document reproduit des "
                 "messages tels qu'exportés par Telegram.</footer>")
    css = _CSS if not for_qt else (
        "body { font-family: sans-serif; font-size: 10pt; color: #202b3c; } .meta { color: #738096; "
        "font-size: 9pt; } .quote { color: #738096; } .day { color: #738096; } .missing { color: #c9463f; } "
        ".service { color: #738096; font-style: italic; } header p { color: #738096; }")
    return ("<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<meta name='generator' content='Telegramor'><title>{escape(title)}</title>"
            f"<style>{css}</style></head><body>" + "".join(parts) + "</body></html>")


def write_pdf(html: str, path: Path, title: str) -> None:
    """PDF A4 paginé via Qt (QTextDocument + QPdfWriter, sans dépendance supplémentaire)."""
    from PySide6.QtCore import QMarginsF, QSizeF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
    writer = QPdfWriter(str(path))
    writer.setTitle(title)
    writer.setCreator("Telegramor")
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                     QMarginsF(14, 16, 14, 18), QPageLayout.Millimeter))
    doc = QTextDocument()
    doc.setHtml(html)
    doc.setPageSize(QSizeF(writer.width(), writer.height()))
    doc.print_(writer)


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #

def export_messages(messages: list[MessageRow], path: Path, fmt: str, title: str, include_media: bool = False,
                    progress: Callable[[int, int, str], bool] | None = None,
                    conv_names: dict[str, str] | None = None) -> ExportOutcome:
    path = Path(path)
    if fmt not in FORMATS:
        raise ValueError(f"Format inconnu : {fmt}")
    path.parent.mkdir(parents=True, exist_ok=True)
    out = ExportOutcome(path, messages=len(messages))
    media_map: dict[int, Path] = {}
    base = path.parent
    if include_media:
        media_dir = path.with_name(path.stem + "_fichiers")
        media_map, out.media_copied, out.media_missing, out.errors = _copy_media(messages, media_dir, progress)
        out.media_dir = media_dir if out.media_copied else None
    if fmt == FMT_JSON:
        text = to_json(messages, title, media_map, base, conv_names)
    elif fmt == FMT_MARKDOWN:
        text = to_markdown(messages, title, media_map, base, conv_names)
    elif fmt == FMT_HTML:
        text = to_html(messages, title, media_map, base, conv_names=conv_names)
    else:
        write_pdf(to_html(messages, title, media_map, base, for_qt=True, conv_names=conv_names), path, title)
        return out
    path.write_text(text, encoding="utf-8")
    return out


def printable_html(messages: list[MessageRow], title: str, folder: Path,
                   conv_names: dict[str, str] | None = None) -> Path:
    """Fichier HTML prêt à imprimer (ouvert ensuite dans le navigateur du système)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (media_export.safe_name(title) + ".html")
    path.write_text(to_html(messages, title, print_hint=True, conv_names=conv_names), encoding="utf-8")
    return path
