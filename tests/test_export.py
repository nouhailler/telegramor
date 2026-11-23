"""Tests de la copie de médias vers un dossier."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from database.models import MediaRow
from services.media_export import (
    NAMING_DATE, ExportOptions, export_medias, plan_copies, safe_name, summary_text,
)


def media(path: Path | None, date="2025-12-16T18:33:18+01:00", conv="Famille", mid=1) -> MediaRow:
    return MediaRow(mid, "photo", str(path) if path else None, None, path, None, None, None, None, None,
                    None, None, False, message_seq=1, message_date=date, message_sender="Zoé",
                    conversation_id="c", conversation_name=conv)


def make(tmp: Path, rel: str, content: bytes = b"img") -> Path:
    p = tmp / "export" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def test_copy_keeps_sources_and_sets_date(tmp_path):
    a = make(tmp_path, "photos/photo_1.jpg", b"AAA")
    b = make(tmp_path, "photos/photo_2.jpg", b"BBBB")
    before = {p: (p.read_bytes(), p.stat().st_mtime) for p in (a, b)}
    dest = tmp_path / "dest"
    r = export_medias([media(a), media(b, date="2024-01-02T03:04:05+00:00")], dest)
    assert sorted(p.name for p in r.copied) == ["photo_1.jpg", "photo_2.jpg"]
    assert (dest / "photo_2.jpg").read_bytes() == b"BBBB" and r.bytes_copied == 7
    assert {p: (p.read_bytes(), p.stat().st_mtime) for p in (a, b)} == before      # originaux intacts
    assert os.path.getmtime(dest / "photo_2.jpg") == datetime.fromisoformat("2024-01-02T03:04:05+00:00").timestamp()


def test_never_overwrites_and_renames(tmp_path):
    a = make(tmp_path, "photos/photo_1.jpg", b"new")
    other = make(tmp_path, "autre/photo_1.jpg", b"other")      # même nom, autre dossier
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "photo_1.jpg").write_bytes(b"existing")
    r = export_medias([media(a), media(other)], dest)
    assert (dest / "photo_1.jpg").read_bytes() == b"existing"
    assert (dest / "photo_1 (2).jpg").read_bytes() == b"new"
    assert (dest / "photo_1 (3).jpg").read_bytes() == b"other"
    assert r.renamed == 2


def test_missing_and_duplicates_are_skipped(tmp_path):
    a = make(tmp_path, "photos/photo_1.jpg")
    r = export_medias([media(a), media(a, mid=2), media(tmp_path / "absent.jpg"), media(None)],
                      tmp_path / "dest")
    assert len(r.copied) == 1 and r.duplicates == 1 and r.missing == 2
    text = summary_text(r)
    assert "1 fichier(s) copié(s)" in text and "absent de l'export" in text


def test_naming_by_date_and_conversation_folders(tmp_path):
    a = make(tmp_path, "photos/photo_1.jpg")
    b = make(tmp_path, "photos/photo_2.jpg")
    opts = ExportOptions(naming=NAMING_DATE, by_conversation=True)
    plans, _ = plan_copies([media(a), media(b, conv="Voyages / 2024")], tmp_path / "d", opts)
    assert [p.target.relative_to(tmp_path / "d").as_posix() for p in plans] == [
        "Famille/2025-12-16_18-33-18_photo_1.jpg", "Voyages _ 2024/2025-12-16_18-33-18_photo_2.jpg"]
    assert not (tmp_path / "d").exists()          # le plan n'écrit rien


def test_cancel_keeps_copied_files(tmp_path):
    files = [make(tmp_path, f"photos/p{i}.jpg") for i in range(5)]
    r = export_medias([media(f, mid=i) for i, f in enumerate(files)], tmp_path / "dest",
                      progress=lambda done, total, name: done < 2)
    assert r.cancelled and len(r.copied) == 2


def test_error_leaves_no_partial_file(tmp_path, monkeypatch):
    a = make(tmp_path, "photos/photo_1.jpg")
    import shutil

    def boom(*_a, **_k):
        raise OSError(28, "Plus d'espace disponible")
    monkeypatch.setattr(shutil, "copyfileobj", boom)
    r = export_medias([media(a)], tmp_path / "dest")
    assert r.errors and not any((tmp_path / "dest").iterdir())


def test_safe_name():
    assert safe_name('a/b:c*?"<>|.jpg') == "a_b_c_.jpg"
    assert safe_name("...") == "media"
