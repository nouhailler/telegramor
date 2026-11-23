"""Visionneuse de photos (zoom, navigation) et lecteur vidéo intégré optionnel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSlider, QToolButton,
    QVBoxLayout, QWidget,
)

from database.models import MediaRow
from services.media_service import MULTIMEDIA_AVAILABLE, ThumbnailLoader, open_with_system, show_in_folder

from .formatting import full_datetime


class ImageViewer(QDialog):
    """Affiche une photo en grand. ←/→ : photo précédente/suivante, molette+Ctrl ou +/− : zoom."""

    def __init__(self, items: list[MediaRow], index: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Photo")
        self.items = items
        self.index = index
        self.scale = 0.0           # 0 = ajusté à la fenêtre
        self.pixmap = QPixmap()

        self.label = QLabel(alignment=Qt.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.area = QScrollArea()
        self.area.setAlignment(Qt.AlignCenter)
        self.area.setWidget(self.label)
        self.area.setWidgetResizable(False)
        self.area.setStyleSheet("background: #111;")

        self.caption = QLabel(objectName="Muted")
        prev_b = QToolButton(text="◀", toolTip="Précédente (←)")
        next_b = QToolButton(text="▶", toolTip="Suivante (→)")
        fit_b = QToolButton(text="Ajuster", toolTip="Ajuster à la fenêtre (0)")
        one_b = QToolButton(text="100 %", toolTip="Taille réelle (1)")
        open_b = QPushButton("Ouvrir avec…")
        folder_b = QPushButton("Dossier")
        prev_b.clicked.connect(lambda: self.step(-1))
        next_b.clicked.connect(lambda: self.step(1))
        fit_b.clicked.connect(lambda: self.set_scale(0))
        one_b.clicked.connect(lambda: self.set_scale(1))
        open_b.clicked.connect(lambda: self.current_path() and open_with_system(self.current_path()))
        folder_b.clicked.connect(lambda: self.current_path() and show_in_folder(self.current_path()))

        bar = QHBoxLayout()
        for w in (prev_b, next_b, fit_b, one_b):
            bar.addWidget(w)
        bar.addWidget(self.caption, 1)
        bar.addWidget(open_b)
        bar.addWidget(folder_b)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.addWidget(self.area, 1)
        lay.addLayout(bar)

        for key, fn in ((Qt.Key_Left, lambda: self.step(-1)), (Qt.Key_Right, lambda: self.step(1)),
                        (Qt.Key_Plus, lambda: self.zoom(1.25)), (Qt.Key_Minus, lambda: self.zoom(0.8)),
                        (Qt.Key_0, lambda: self.set_scale(0)), (Qt.Key_1, lambda: self.set_scale(1))):
            QShortcut(QKeySequence(key), self, activated=fn)
        self.resize(1000, 750)
        self.load()

    def current(self) -> MediaRow:
        return self.items[self.index]

    def current_path(self) -> Path | None:
        m = self.current()
        if m.file_available:
            return m.abs_file
        return m.abs_thumbnail if m.thumbnail_available else None

    def load(self) -> None:
        m = self.current()
        path = self.current_path()
        self.pixmap = QPixmap(str(path)) if path else QPixmap()
        note = "" if m.file_available else "  —  original introuvable, miniature affichée" if path else ""
        info = f"{self.index + 1}/{len(self.items)}  ·  {m.message_sender or ''}  ·  {full_datetime(m.message_date)}"
        self.caption.setText(info + note)
        if self.pixmap.isNull():
            self.label.setText(f"Fichier introuvable :\n{m.file_path or m.thumbnail_path}")
            self.label.setStyleSheet("color: #ff8a80;")
            self.label.resize(self.area.viewport().size())
        else:
            self.label.setStyleSheet("")
        self.scale = 0
        self.render()

    def render(self) -> None:
        if self.pixmap.isNull():
            return
        if self.scale == 0:
            target = self.area.viewport().size() - QSize(4, 4)
            pm = self.pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation) \
                if (self.pixmap.width() > target.width() or self.pixmap.height() > target.height()) else self.pixmap
        else:
            pm = self.pixmap.scaled(self.pixmap.size() * self.scale, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label.setPixmap(pm)
        self.label.resize(pm.size())

    def set_scale(self, s: float) -> None:
        self.scale = s
        self.render()

    def zoom(self, factor: float) -> None:
        if self.pixmap.isNull():
            return
        if self.scale == 0:
            self.scale = self.label.pixmap().width() / max(self.pixmap.width(), 1)
        self.scale = min(max(self.scale * factor, 0.05), 8)
        self.render()

    def step(self, delta: int) -> None:
        if self.items:
            self.index = (self.index + delta) % len(self.items)
            self.load()

    def wheelEvent(self, e) -> None:  # noqa: N802
        if e.modifiers() & Qt.ControlModifier:
            self.zoom(1.15 if e.angleDelta().y() > 0 else 1 / 1.15)
        else:
            super().wheelEvent(e)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self.scale == 0:
            self.render()


class VideoPlayer(QDialog):
    """Lecteur intégré (nécessite python3-pyside6.qtmultimedia et qtmultimediawidgets)."""

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget

        self.setWindowTitle(path.name)
        self.path = path
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.player.setVideoOutput(self.video)
        self.player.setSource(QUrl.fromLocalFile(str(path)))

        self.play_b = QToolButton(text="⏸")
        self.play_b.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("00:00", objectName="Muted")
        ext = QPushButton("Lecteur système")
        ext.clicked.connect(lambda: (open_with_system(self.path), self.close()))
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.positionChanged.connect(self._pos)
        self.player.errorOccurred.connect(lambda *_: self.time.setText("Lecture impossible : " +
                                                                       self.player.errorString()))

        bar = QHBoxLayout()
        bar.addWidget(self.play_b)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.time)
        bar.addWidget(ext)
        lay = QVBoxLayout(self)
        lay.addWidget(self.video, 1)
        lay.addLayout(bar)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle)
        self.resize(900, 560)
        self.player.play()

    def toggle(self) -> None:
        from PySide6.QtMultimedia import QMediaPlayer
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.play_b.setText("▶")
        else:
            self.player.play()
            self.play_b.setText("⏸")

    def _pos(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        s = ms // 1000
        self.time.setText(f"{s // 60:02d}:{s % 60:02d}")

    def closeEvent(self, e) -> None:  # noqa: N802
        self.player.stop()
        super().closeEvent(e)


def play_video(path: Path, parent: QWidget | None, internal: bool) -> None:
    """Lit une vidéo : lecteur intégré si disponible et souhaité, sinon application système."""
    if internal and MULTIMEDIA_AVAILABLE:
        VideoPlayer(path, parent).exec()
    else:
        open_with_system(path)


def preload(path: Path, size: QSize) -> None:
    ThumbnailLoader.instance().request(path, size)
