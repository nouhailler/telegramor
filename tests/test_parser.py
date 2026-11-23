"""Tests du parseur : fichier de référence réel + cas synthétiques."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from importer.models import MediaType, MessageKind
from importer.telegram_html_parser import (
    ParserState, TelegramHtmlParser, parse_date_title, parse_duration, parse_separator_date,
)
from tests.conftest import msg, page, service


@pytest.fixture
def parser() -> TelegramHtmlParser:
    return TelegramHtmlParser()


# --------------------------------------------------------------------------- #
# Fichier de référence réel
# --------------------------------------------------------------------------- #

class TestReferenceFile:
    @pytest.fixture
    def res(self, parser, reference_html):
        return parser.parse_html(reference_html)

    def by_id(self, res):
        return {m.html_id: m for m in res.messages}

    def test_conversation_name(self, res):
        assert res.conversation_name == "fabien"

    def test_all_blocks_extracted(self, res):
        assert res.raw_block_count == 40
        assert res.dom_block_count == 40
        assert len(res.messages) == 40

    def test_counts_by_kind(self, res):
        kinds = [m.kind for m in res.messages]
        assert kinds.count(MessageKind.DATE_SEPARATOR) == 8
        assert kinds.count(MessageKind.DEFAULT) == 32
        assert kinds.count(MessageKind.SERVICE) == 0
        assert sum(m.is_joined for m in res.messages) == 8

    def test_ids_unique_and_ordered(self, res):
        ids = [m.message_id for m in res.messages]
        assert len(set(ids)) == 40
        assert [m.position for m in res.messages] == list(range(40))
        assert res.messages[0].message_id == -1

    def test_no_error_anomalies(self, res):
        assert [a for a in res.anomalies if a.severity == "erreur"] == []

    def test_every_default_message_has_sender_and_date(self, res):
        for m in res.messages:
            if m.kind is MessageKind.DEFAULT:
                assert m.sender, m.html_id
                assert m.date is not None and m.date.tzinfo is not None, m.html_id
                assert m.timezone == "UTC+01:00"

    def test_joined_inherit_sender(self, res):
        expected = {
            "message185996": "fabien",
            "message189180": "remi",
            "message189182": "pierre",
            "message189187": "pierre",
            "message189188": "pierre",
            "message191564": "remi",
            "message191565": "remi",
            "message191566": "remi",
        }
        joined = {m.html_id: m.sender for m in res.messages if m.is_joined}
        assert joined == expected
        assert all(m.sender_inherited for m in res.messages if m.is_joined)
        assert not any(m.sender_inherited for m in res.messages if not m.is_joined)

    def test_sender_name_trimmed(self, res):
        assert {m.sender for m in res.messages if m.sender} == {"fabien", "pierre", "remi"}

    def test_date_parsing(self, res):
        m = self.by_id(res)["message185995"]
        assert m.date == datetime(2025, 12, 16, 18, 33, 18, tzinfo=timezone(timedelta(hours=1)))
        assert m.date_raw == "16.12.2025 18:33:18 UTC+01:00"
        assert m.utc_offset_minutes == 60

    def test_date_separators(self, res):
        seps = [m.separator_date for m in res.messages if m.kind is MessageKind.DATE_SEPARATOR]
        assert seps[0] == date(2025, 12, 16)
        assert seps[-1] == date(2026, 11, 12)
        assert not [a for a in res.anomalies if a.code == "SEPARATOR_MISMATCH"]

    def test_link_keeps_real_href(self, res):
        m = self.by_id(res)["message185995"]
        # Le texte visible est anonymisé, mais le href garde le vrai lien
        assert len(m.links) == 1 and m.links[0].startswith("https://youtu.be/")
        assert m.links[0] != m.text
        assert m.text == "https://youtu.be/anonymisé"
        assert f'href="{m.links[0]}"' in m.html

    def test_reply(self, res):
        m = self.by_id(res)["message189181"]
        assert m.reply_to_message_id == 189180
        assert m.reply_to_file is None
        assert m.text == "Top"
        assert "message189180" in self.by_id(res)  # cible présente

    def test_reactions(self, res):
        reacted = [m for m in res.messages if m.reactions]
        assert [m.html_id for m in reacted] == ["message189180", "message191569"]
        r = reacted[0].reactions[0]
        assert (r.emoji, r.count, r.users, r.active) == ("👍", 1, ["pierre"], True)

    def test_photos(self, res):
        d = self.by_id(res)
        p1 = d["message186728"].media
        assert len(p1) == 1 and p1[0].media_type is MediaType.PHOTO
        assert p1[0].file_path == "photos/photo_1@10-01-2026_20-28-43.jpg"
        assert p1[0].thumbnail_path == "photos/photo_1@10-01-2026_20-28-43_thumb.jpg"
        assert (p1[0].thumb_width, p1[0].thumb_height) == (173, 260)
        assert d["message186728"].text == ""
        # photo + légende
        assert d["message188184"].media[0].media_type is MediaType.PHOTO
        assert d["message188184"].text == "tu vas bien ?"

    def test_video_paths_not_reconstructed(self, res):
        m = self.by_id(res)["message196573"]
        v = m.media[0]
        assert v.media_type is MediaType.VIDEO
        assert v.file_path == "video_files/jenseng.mp4"
        # chemin lu tel quel, même s'il ne correspond pas au nom de la vidéo
        assert v.thumbnail_path == "video_files/jean.mp4_thumb.jpg"
        assert v.duration_raw == "00:42" and v.duration_seconds == 42
        assert m.text == "bonne matinées 🤔"

    def test_userpic_metadata(self, res):
        m = self.by_id(res)["message185997"]
        assert (m.sender_initials, m.sender_userpic_class) == ("p", "userpic5")

    def test_no_javascript_retained(self, res):
        for m in res.messages:
            assert "onclick" not in m.html and "GoToMessage" not in m.html


# --------------------------------------------------------------------------- #
# Cas synthétiques (types non présents dans le fichier de référence)
# --------------------------------------------------------------------------- #

def parse(parser, history, **kw):
    return parser.parse_html(page(history, **kw))


def test_service_event_and_pinned_link(parser):
    res = parse(parser, service(-1, "5 May 2024") + service(
        -2, 'Alice pinned <a href="#go_to_message42" onclick="return GoToMessage(42)">this message</a>'))
    sep, ev = res.messages
    assert sep.kind is MessageKind.DATE_SEPARATOR and sep.separator_date == date(2024, 5, 5)
    assert ev.kind is MessageKind.SERVICE
    assert ev.service_text == "Alice pinned this message"
    assert ev.reply_to_message_id == 42


def test_forwarded_message(parser):
    inner = ('<div class="forwarded body"><div class="from_name">Bob '
             '<span class="date details" title="01.01.2024 09:00:00 UTC+01:00"> 01.01.2024</span></div>'
             '<div class="text">Texte transféré</div></div>')
    m = parse(parser, msg(1, inner)).messages[0]
    assert m.forwarded_from == "Bob"
    assert m.forwarded_date_raw == "01.01.2024 09:00:00 UTC+01:00"
    assert m.text == "Texte transféré"
    assert m.sender == "Alice"


def test_via_bot(parser):
    h = ('<div class="message default clearfix" id="message1"><div class="body">'
         '<div class="pull_right date details" title="01.02.2024 10:00:00 UTC+01:00">10:00</div>'
         '<div class="from_name">Alice <span class="details"> via @gif</span></div>'
         '<div class="text">x</div></div></div>')
    m = parse(parser, h).messages[0]
    assert (m.sender, m.via_bot) == ("Alice", "@gif")


def test_generic_media_types(parser):
    media = (
        '<div class="media_wrap clearfix">'
        '<a class="media clearfix pull_left block_link media_voice_message" href="voice_messages/audio_1.ogg">'
        '<div class="fill pull_left"></div><div class="body"><div class="title bold">Voice message</div>'
        '<div class="status details">00:07, 25.1 KB</div></div></a></div>')
    v = parse(parser, msg(1, media)).messages[0].media[0]
    assert v.media_type is MediaType.VOICE
    assert v.file_path == "voice_messages/audio_1.ogg"
    assert v.duration_seconds == 7 and v.duration_raw == "00:07"
    assert not v.not_included

    not_inc = ('<div class="media_wrap clearfix"><div class="media clearfix pull_left media_file">'
               '<div class="fill pull_left"></div><div class="body"><div class="title bold">rapport.pdf</div>'
               '<div class="status details">Not included, change data exporting settings to download.</div>'
               '</div></div></div>')
    f = parse(parser, msg(2, not_inc)).messages[0].media[0]
    assert f.media_type is MediaType.FILE and f.not_included and f.file_path is None
    assert f.title == "rapport.pdf"


@pytest.mark.parametrize("cls,title,expected", [
    ("media_audio_file", "Chanson", MediaType.AUDIO),
    ("media_video", "Video message", MediaType.VIDEO_MESSAGE),
    ("media_location", "Location", MediaType.LOCATION),
    ("media_contact", "Jean", MediaType.CONTACT),
    ("media_call", "Outgoing call", MediaType.CALL),
    ("media_game", "Jeu", MediaType.GAME),
])
def test_generic_media_mapping(parser, cls, title, expected):
    h = (f'<div class="media_wrap clearfix"><a class="media clearfix pull_left block_link {cls}" href="f/x">'
         f'<div class="body"><div class="title bold">{title}</div></div></a></div>')
    assert parse(parser, msg(1, h)).messages[0].media[0].media_type is expected


def test_sticker_and_animation(parser):
    h = ('<div class="media_wrap clearfix"><a class="sticker_wrap clearfix pull_left" href="stickers/s.webp">'
         '<img class="sticker" src="stickers/s.webp_thumb.jpg" style="width: 256px; height: 256px"/></a></div>')
    s = parse(parser, msg(1, h)).messages[0].media[0]
    assert s.media_type is MediaType.STICKER and s.thumbnail_path == "stickers/s.webp_thumb.jpg"
    h = ('<div class="media_wrap clearfix"><a class="animated_wrap clearfix pull_left" href="video_files/g.mp4">'
         '<div class="video_play_bg"><div class="gif_play">GIF</div></div>'
         '<img class="animated" src="video_files/g.mp4_thumb.jpg"/></a></div>')
    g = parse(parser, msg(2, h)).messages[0].media[0]
    assert g.media_type is MediaType.ANIMATION and g.file_path == "video_files/g.mp4"


def test_poll(parser):
    h = ('<div class="media_wrap clearfix"><div class="media_poll"><div class="question bold">Pizza ?</div>'
         '<div class="details">Anonymous poll</div><div class="answer">- Oui</div><div class="answer">- Non</div>'
         '<div class="total details">3 votes</div></div></div>')
    p = parse(parser, msg(1, h)).messages[0].media[0]
    assert p.media_type is MediaType.POLL and p.title == "Pizza ?"
    assert p.description == "- Oui\n- Non" and p.status == "3 votes"


def test_reply_to_other_file(parser):
    h = ('<div class="reply_to details">In reply to <a href="messages2.html#go_to_message77" '
         'onclick="return GoToMessage(77)">this message</a></div><div class="text">ok</div>')
    m = parse(parser, msg(1, h)).messages[0]
    assert m.reply_to_message_id == 77 and m.reply_to_file == "messages2.html"


def test_reply_without_link(parser):
    res = parse(parser, msg(1, '<div class="reply_to details">In reply to a message in another chat</div>'
                               '<div class="text">ok</div>'))
    assert res.messages[0].reply_to_message_id is None
    assert res.messages[0].reply_raw == "In reply to a message in another chat"
    assert any(a.code == "REPLY_UNRESOLVED" for a in res.anomalies)


def test_reactions_with_count_and_custom_emoji(parser):
    h = ('<div class="text">x</div><span class="reactions">'
         '<span class="reaction"><span class="emoji">❤</span><span class="count">12</span></span>'
         '<span class="reaction"><span class="emoji"><img src="images/custom.webp"/></span>'
         '<span class="userpics"><div class="userpic"><div class="initials" title="Bob">B</div></div>'
         '<div class="userpic"><div class="initials" title="Eve">E</div></div></span></span></span>')
    r = parse(parser, msg(1, h)).messages[0].reactions
    assert (r[0].emoji, r[0].count, r[0].users, r[0].active) == ("❤", 12, [], False)
    assert r[1].is_custom_emoji and r[1].emoji == "images/custom.webp"
    assert r[1].count == 2 and r[1].users == ["Bob", "Eve"]


def test_edited_and_multiline_formatting(parser):
    h = '<div class="text">Ligne <strong>1</strong><br>Ligne 2<br><br>Ligne 4</div>'
    m = parse(parser, msg(1, h, title="01.02.2024 10:00:00 UTC+01:00\nEdited: 01.02.2024 10:05:00 UTC+01:00")
              ).messages[0]
    assert m.text == "Ligne 1\nLigne 2\n\nLigne 4"
    assert "<strong>1</strong>" in m.html and m.html.count("<br>") == 3
    assert m.edited_raw and "Edited" in m.edited_raw
    assert m.date == datetime(2024, 2, 1, 10, 0, tzinfo=timezone(timedelta(hours=1)))


def test_html_is_sanitized(parser):
    h = ('<div class="text">Salut <script>alert(1)</script><a href="javascript:alert(2)">clic</a> '
         '<img src=x onerror="alert(3)"><a href="https://ex.org" onclick="evil()">ok</a>'
         '<span class="spoiler">secret</span></div>')
    m = parse(parser, msg(1, h)).messages[0]
    assert "script" not in m.html and "alert" not in m.html
    assert "javascript" not in m.html and "onerror" not in m.html and "onclick" not in m.html
    assert '<a href="https://ex.org">ok</a>' in m.html
    assert '<span class="spoiler">secret</span>' in m.html
    assert m.links == ["https://ex.org"]
    assert "alert" not in m.text


def test_unknown_element_is_reported_not_lost(parser):
    res = parse(parser, msg(1, '<div class="text">a</div><div class="nouveau_bloc">info inédite</div>'))
    m = res.messages[0]
    assert "info inédite" in m.text and m.warnings
    assert any(a.code == "UNKNOWN_ELEMENT" for a in res.anomalies)


def test_joined_without_previous_sender(parser):
    res = parse(parser, msg(1, '<div class="text">orphelin</div>', joined=True))
    assert res.messages[0].sender is None
    assert any(a.code == "JOINED_WITHOUT_SENDER" for a in res.anomalies)


def test_state_carries_sender_across_files(parser):
    state = ParserState()
    parser.parse_html(page(msg(1, '<div class="text">a</div>', sender="Zoé")), state=state)
    res = parser.parse_html(page(msg(2, '<div class="text">b</div>', joined=True)), state=state,
                            source_name="messages2.html")
    m = res.messages[0]
    assert m.sender == "Zoé" and m.sender_inherited and m.position == 1


def test_separator_mismatch_detected(parser):
    res = parse(parser, service(-1, "2 February 2024") + msg(1, '<div class="text">a</div>'))
    assert any(a.code == "SEPARATOR_MISMATCH" for a in res.anomalies)


def test_date_without_timezone_and_bad_date(parser):
    res = parse(parser, msg(1, '<div class="text">a</div>', title="01.02.2024 10:00:00")
                + msg(2, '<div class="text">b</div>', title="pas une date"))
    a, b = res.messages
    assert a.date == datetime(2024, 2, 1, 10, 0) and a.timezone is None
    assert b.date is None and b.date_raw == "pas une date"
    codes = {x.code for x in res.anomalies}
    assert {"NO_TIMEZONE", "UNPARSED_DATE"} <= codes


def test_not_a_chat_page(parser):
    res = parser.parse_html("<html><body><p>rien</p></body></html>")
    assert res.messages == [] and res.anomalies[0].code == "NO_HISTORY"


@pytest.mark.parametrize("raw,expected", [("00:42", 42), ("1:02:03", 3723), ("00:07, 25 KB", 7), (None, None),
                                          ("abc", None)])
def test_parse_duration(raw, expected):
    assert parse_duration(raw) == expected


def test_parse_helpers():
    assert parse_separator_date("1 March 2026") == date(2026, 3, 1)
    assert parse_separator_date("Alice joined") is None
    dt, tz, off, rest = parse_date_title("31.12.2023 23:59:59 UTC-05:30")
    assert off == -330 and tz == "UTC-05:30" and rest is None
    assert dt.utcoffset() == timedelta(hours=-5, minutes=-30)
