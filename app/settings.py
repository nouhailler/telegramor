"""Paramètres persistants de l'application (QSettings, fichier INI utilisateur)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

DEFAULT_ZOOM = 100
ZOOM_STEPS = (70, 80, 90, 100, 110, 125, 140, 160, 180, 200)


class AppSettings:
    def __init__(self, settings: QSettings | None = None) -> None:
        self.s = settings or QSettings("TelegramArchiveExplorer", "TelegramArchiveExplorer")

    # -- Apparence ---------------------------------------------------------- #
    @property
    def dark_mode(self) -> bool:
        return self.s.value("ui/dark_mode", False, type=bool)

    @dark_mode.setter
    def dark_mode(self, v: bool) -> None:
        self.s.setValue("ui/dark_mode", v)

    @property
    def zoom(self) -> int:
        return int(self.s.value("ui/zoom", DEFAULT_ZOOM, type=int))

    @zoom.setter
    def zoom(self, v: int) -> None:
        self.s.setValue("ui/zoom", int(v))

    @property
    def info_panel_visible(self) -> bool:
        return self.s.value("ui/info_panel", True, type=bool)

    @info_panel_visible.setter
    def info_panel_visible(self, v: bool) -> None:
        self.s.setValue("ui/info_panel", v)

    @property
    def conversation_sort(self) -> str:
        return str(self.s.value("ui/conversation_sort", "date"))

    @conversation_sort.setter
    def conversation_sort(self, v: str) -> None:
        self.s.setValue("ui/conversation_sort", v)

    @property
    def internal_video_player(self) -> bool:
        return self.s.value("ui/internal_video_player", True, type=bool)

    @internal_video_player.setter
    def internal_video_player(self, v: bool) -> None:
        self.s.setValue("ui/internal_video_player", v)

    # -- Identité (côté droit des bulles) ------------------------------------ #
    @property
    def owner_name(self) -> str | None:
        v = self.s.value("identity/owner_name", "")
        return str(v) or None

    @owner_name.setter
    def owner_name(self, v: str | None) -> None:
        self.s.setValue("identity/owner_name", v or "")

    # -- Fenêtre ------------------------------------------------------------- #
    def window_state(self) -> tuple[QByteArray | None, QByteArray | None]:
        return self.s.value("window/geometry"), self.s.value("window/splitter")

    def save_window_state(self, geometry: QByteArray, splitter: QByteArray) -> None:
        self.s.setValue("window/geometry", geometry)
        self.s.setValue("window/splitter", splitter)

    # -- Dernière consultation ----------------------------------------------- #
    @property
    def last_conversation(self) -> str | None:
        v = self.s.value("last/conversation", "")
        return str(v) or None

    @last_conversation.setter
    def last_conversation(self, v: str | None) -> None:
        self.s.setValue("last/conversation", v or "")

    def last_seq(self, conv_id: str) -> int | None:
        v = self.s.value(f"last_seq/{conv_id}")
        return int(v) if v not in (None, "") else None

    def set_last_seq(self, conv_id: str, seq: int | None) -> None:
        self.s.setValue(f"last_seq/{conv_id}", "" if seq is None else int(seq))

    @property
    def last_import_dir(self) -> str:
        return str(self.s.value("last/import_dir", ""))

    @last_import_dir.setter
    def last_import_dir(self, v: str) -> None:
        self.s.setValue("last/import_dir", v)

    # -- Copie de médias ------------------------------------------------------ #
    @property
    def last_export_dir(self) -> str:
        return str(self.s.value("export/dir", ""))

    @last_export_dir.setter
    def last_export_dir(self, v: str) -> None:
        self.s.setValue("export/dir", v)

    def export_options(self) -> dict:
        return dict(naming=str(self.s.value("export/naming", "original")),
                    by_conversation=self.s.value("export/by_conversation", False, type=bool),
                    set_mtime=self.s.value("export/set_mtime", True, type=bool))

    def save_export_options(self, naming: str, by_conversation: bool, set_mtime: bool) -> None:
        self.s.setValue("export/naming", naming)
        self.s.setValue("export/by_conversation", by_conversation)
        self.s.setValue("export/set_mtime", set_mtime)

    # -- Mises à jour (facultatif, désactivé par défaut) ---------------------- #
    @property
    def auto_update_check(self) -> bool:
        return self.s.value("update/auto_check", False, type=bool)

    @auto_update_check.setter
    def auto_update_check(self, v: bool) -> None:
        self.s.setValue("update/auto_check", bool(v))

    @property
    def last_update_check(self) -> str | None:
        return str(self.s.value("update/last_check", "")) or None

    @last_update_check.setter
    def last_update_check(self, v: str) -> None:
        self.s.setValue("update/last_check", v)

    # -- Composants facultatifs : signalés une fois par version ------------- #
    @property
    def deps_notified(self) -> str:
        return str(self.s.value("deps/notified_version", ""))

    @deps_notified.setter
    def deps_notified(self, v: str) -> None:
        self.s.setValue("deps/notified_version", v)

    def file_path(self):
        from pathlib import Path
        return Path(self.s.fileName())

    def sync(self) -> None:
        self.s.sync()
