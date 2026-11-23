"""Assainissement du HTML des messages.

Le HTML des exports est traité comme une donnée non fiable : on ne conserve
qu'une liste blanche de balises de mise en forme, on supprime tout attribut
hors `href` (et `class="spoiler"`), on neutralise les schémas d'URL dangereux
et on retire intégralement les balises actives (script, style, iframe…).
"""

from __future__ import annotations

from html import escape

from bs4 import NavigableString, Tag, Comment

ALLOWED_TAGS = {
    "a", "strong", "b", "em", "i", "u", "s", "strike", "del", "code", "pre",
    "blockquote", "br", "span",
}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math"}
SAFE_SCHEMES = ("http://", "https://", "mailto:", "tg://", "tel:")


def is_safe_href(href: str) -> bool:
    h = href.strip().lower()
    return h.startswith(SAFE_SCHEMES) or h.startswith("#go_to_message")


def sanitize_children(node: Tag) -> str:
    """Retourne le HTML assaini du contenu de `node` (sans `node` lui-même)."""
    return "".join(_render(child) for child in node.children).strip()


def _render(node) -> str:
    if isinstance(node, Comment):
        return ""
    if isinstance(node, NavigableString):
        return escape(str(node), quote=False)
    if not isinstance(node, Tag):
        return ""
    name = node.name.lower()
    if name in DROP_WITH_CONTENT:
        return ""
    inner = "".join(_render(c) for c in node.children)
    if name not in ALLOWED_TAGS:
        return inner  # balise inconnue : on garde le texte, pas la balise
    if name == "br":
        return "<br>"
    if name == "a":
        href = node.get("href", "")
        if href and is_safe_href(href):
            return f'<a href="{escape(href, quote=True)}">{inner}</a>'
        return inner
    if name == "span":
        if "spoiler" in (node.get("class") or []):
            return f'<span class="spoiler">{inner}</span>'
        return inner
    return f"<{name}>{inner}</{name}>"


def html_to_text(node: Tag) -> str:
    """Texte brut d'un nœud : <br> devient un saut de ligne, scripts ignorés."""
    parts: list[str] = []

    def walk(n) -> None:
        if isinstance(n, Comment):
            return
        if isinstance(n, NavigableString):
            parts.append(str(n))
            return
        if not isinstance(n, Tag):
            return
        if n.name.lower() in DROP_WITH_CONTENT:
            return
        if n.name.lower() == "br":
            parts.append("\n")
            return
        for c in n.children:
            walk(c)

    for child in node.children:
        walk(child)
    return _normalize_text("".join(parts))


def _normalize_text(text: str) -> str:
    # Les exports (souvent indentés) entourent le contenu de sauts de ligne :
    # on retire les blancs de début/fin de chaque ligne et les lignes vides
    # en bordure, sans toucher aux sauts de ligne internes voulus.
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
