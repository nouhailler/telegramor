"""Tests de la vérification des médias (existence, chemins suspects)."""

from __future__ import annotations

from pathlib import Path

import pytest

from importer.import_manager import import_path
from importer.media_scanner import resolve_media_path
from tests.conftest import REAL_EXPORT, msg, page


def write_export(tmp: Path, history: str) -> Path:
    d = tmp / "ChatExport"
    d.mkdir()
    (d / "messages.html").write_text(page(history), encoding="utf-8")
    return d


def photo(mid: int, href: str, thumb: str) -> str:
    return msg(mid, f'<div class="media_wrap clearfix"><a class="photo_wrap clearfix pull_left" href="{href}">'
                    f'<img class="photo" src="{thumb}"/></a></div>')


def test_existing_and_missing_files(tmp_path):
    d = write_export(tmp_path, photo(1, "photos/a.jpg", "photos/a_thumb.jpg")
                     + photo(2, "photos/b.jpg", "photos/b_thumb.jpg"))
    (d / "photos").mkdir()
    (d / "photos/a.jpg").write_bytes(b"x" * 10)
    (d / "photos/a_thumb.jpg").write_bytes(b"x")
    (d / "photos/b_thumb.jpg").write_bytes(b"x")
    res = import_path(d)
    a, b = (m.media[0] for m in res.conversations[0].messages)
    assert a.file_exists and a.thumbnail_exists and a.file_size == 10
    assert b.file_exists is False and b.thumbnail_exists is True
    assert res.report.missing_files == 1
    assert res.report.missing_file_list == ["photos/b.jpg"]
    assert [x.code for x in res.report.anomalies if x.code.startswith("MISSING")] == ["MISSING_FILE"]


def test_original_files_untouched(tmp_path):
    d = write_export(tmp_path, photo(1, "photos/a.jpg", "photos/a_thumb.jpg"))
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in d.rglob("*") if p.is_file()}
    import_path(d)
    after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in d.rglob("*") if p.is_file()}
    assert before == after


@pytest.mark.parametrize("href", ["../../etc/passwd", "/etc/passwd", "https://exemple.org/a.jpg",
                                  "javascript:alert(1)"])
def test_suspicious_paths_are_not_accessed(tmp_path, href):
    d = write_export(tmp_path, photo(1, href, "photos/t.jpg"))
    res = import_path(d)
    media = res.conversations[0].messages[0].media[0]
    assert media.file_exists is False
    assert any(a.code == "SUSPICIOUS_PATH" for a in res.report.anomalies)


def test_percent_encoded_path(tmp_path):
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "mon fichier.pdf").write_bytes(b"x")
    path, err = resolve_media_path(tmp_path, tmp_path, "files/mon%20fichier.pdf")
    assert err is None and path.name == "mon fichier.pdf"


@pytest.mark.skipif(not REAL_EXPORT.is_dir(), reason="export réel absent de cette machine")
def test_real_export_media():
    res = import_path(REAL_EXPORT)
    r = res.report
    assert (r.photos, r.videos) == (2, 1)
    assert r.missing_file_list == ["video_files/jean.mp4_thumb.jpg"]
    video = next(m for c in res.conversations for msg_ in c.messages for m in msg_.media
                 if m.media_type.value == "video")
    assert video.file_exists is True and video.thumbnail_exists is False
