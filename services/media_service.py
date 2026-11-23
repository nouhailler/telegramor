"""Services liés aux médias : miniatures asynchrones avec cache, ouverture système."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QImage, QImageReader, QPixmap, QPixmapCache

try:  # Qt Multimedia est optionnel (paquet python3-pyside6.qtmultimedia)
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
    from PySide6.QtMultimediaWidgets import QVideoWidget  # noqa: F401
    MULTIMEDIA_AVAILABLE = True
except ImportError:  # pragma: no cover - dépend de l'installation
    MULTIMEDIA_AVAILABLE = False

QPixmapCache.setCacheLimit(256 * 1024)  # Ko : 256 Mo de miniatures en mémoire


def cache_key(path: Path, size: QSize) -> str:
    return f"{path}|{size.width()}x{size.height()}"


class _Signals(QObject):
    done = Signal(str, QImage)


class _LoadTask(QRunnable):
    def __init__(self, key: str, path: Path, size: QSize, signals: _Signals) -> None:
        super().__init__()
        self.key, self.path, self.size, self.signals = key, path, size, signals

    def run(self) -> None:
        reader = QImageReader(str(self.path))
        reader.setAutoTransform(True)       # respecte l'orientation EXIF
        src = reader.size()
        if src.isValid() and (src.width() > self.size.width() or src.height() > self.size.height()):
            reader.setScaledSize(src.scaled(self.size, Qt.KeepAspectRatio))
        img = reader.read()
        self.signals.done.emit(self.key, img)


class ThumbnailLoader(QObject):
    """Charge les images hors du thread d'interface ; met en cache les QPixmap."""

    loaded = Signal(str, QPixmap)   # clé, pixmap (nulle si échec)

    _instance: "ThumbnailLoader | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(4)
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self._pending: set[str] = set()

    @classmethod
    def instance(cls) -> "ThumbnailLoader":
        if cls._instance is None:
            cls._instance = ThumbnailLoader()
        return cls._instance

    def request(self, path: Path, size: QSize) -> tuple[str, QPixmap | None]:
        """Retourne (clé, pixmap si déjà en cache). Sinon le signal `loaded` suivra."""
        key = cache_key(path, size)
        pm = QPixmap()
        if QPixmapCache.find(key, pm):
            return key, pm
        if key not in self._pending:
            self._pending.add(key)
            self._pool.start(_LoadTask(key, path, size, self._signals))
        return key, None

    def load_sync(self, path: Path, size: QSize) -> QPixmap:
        key = cache_key(path, size)
        pm = QPixmap()
        if QPixmapCache.find(key, pm):
            return pm
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        src = reader.size()
        if src.isValid() and (src.width() > size.width() or src.height() > size.height()):
            reader.setScaledSize(src.scaled(size, Qt.KeepAspectRatio))
        pm = QPixmap.fromImage(reader.read())
        if not pm.isNull():
            QPixmapCache.insert(key, pm)
        return pm

    def wait(self) -> None:
        self._pool.waitForDone()

    def _on_done(self, key: str, img: QImage) -> None:
        self._pending.discard(key)
        pm = QPixmap.fromImage(img) if not img.isNull() else QPixmap()
        if not pm.isNull():
            QPixmapCache.insert(key, pm)
        self.loaded.emit(key, pm)


def open_with_system(path: Path) -> bool:
    """Ouvre un fichier local avec l'application associée (xdg-open)."""
    if not path.exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def show_in_folder(path: Path) -> bool:
    folder = path if path.is_dir() else path.parent
    if not folder.exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def open_url(url: str) -> bool:
    """Ouvre un lien web dans le navigateur. Seuls http(s) et mailto sont acceptés."""
    if not url.lower().startswith(("http://", "https://", "mailto:")):
        return False
    return QDesktopServices.openUrl(QUrl(url))


def human_size(n: int | None) -> str:
    if n is None:
        return ""
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return ""
