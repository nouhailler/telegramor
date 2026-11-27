"""Vérification facultative des nouvelles versions publiées sur GitHub Releases.

- Désactivée par défaut ; à la demande (menu Aide) ou automatique au plus une
  fois tous les 7 jours si l'utilisateur l'active.
- Une seule requête HTTPS GET, sans cookie ni identifiant : l'en-tête
  User-Agent est générique (« Telegramor-update-check ») et aucune donnée
  d'utilisation ou d'archive n'est transmise. GitHub voit, comme pour toute
  requête web, l'adresse IP de l'ordinateur.
- Rien n'est téléchargé ni installé : l'application affiche seulement le lien
  vers la page officielle de la version.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta

RELEASES_API = "https://api.github.com/repos/nouhailler/telegramor/releases/latest"
RELEASES_PAGE = "https://github.com/nouhailler/telegramor/releases"
USER_AGENT = "Telegramor-update-check"
AUTO_INTERVAL = timedelta(days=7)


@dataclass
class UpdateInfo:
    current: str
    latest: str
    published: str | None
    url: str
    notes: str = ""

    @property
    def newer(self) -> bool:
        return version_tuple(self.latest) > version_tuple(self.current)


def version_tuple(v: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", v or "")[:3]]
    return tuple(nums + [0] * (3 - len(nums)))


def parse_release(data: dict, current: str) -> UpdateInfo:
    tag = str(data.get("tag_name") or data.get("name") or "")
    if not tag:
        raise ValueError("Réponse inattendue de GitHub.")
    url = str(data.get("html_url") or RELEASES_PAGE)
    if not url.startswith("https://github.com/"):
        url = RELEASES_PAGE                      # ne jamais proposer un lien hors de GitHub
    return UpdateInfo(current=current, latest=tag.lstrip("vV"), published=(data.get("published_at") or "")[:10] or None,
                      url=url, notes=str(data.get("body") or "")[:2000])


def check_latest(current: str, timeout: float = 8.0, opener=urllib.request.urlopen) -> UpdateInfo:
    """Interroge GitHub (une requête GET). Lève OSError / ValueError en cas d'échec."""
    req = urllib.request.Request(RELEASES_API, headers={"Accept": "application/vnd.github+json",
                                                        "User-Agent": USER_AGENT})
    with opener(req, timeout=timeout) as resp:
        data = json.loads(resp.read(512 * 1024).decode("utf-8"))
    return parse_release(data, current)


def auto_check_due(last_check_iso: str | None, now: datetime | None = None) -> bool:
    if not last_check_iso:
        return True
    try:
        last = datetime.fromisoformat(last_check_iso)
    except ValueError:
        return True
    return (now or datetime.now()) - last >= AUTO_INTERVAL
