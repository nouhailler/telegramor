"""Fenêtre principale : liste des conversations | messages | informations."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLoggingCategory, Qt, QThread, Slot
from PySide6.QtGui import QAction, QFontDatabase, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QInputDialog, QLabel, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget, QLineEdit, QToolButton, QSizePolicy,
)

from database.db_manager import Database
from database.repositories import LibraryRepository
from database.search_engine import SearchEngine
from services.indexing_service import ImportWorker, start_import
from services.media_service import MULTIMEDIA_AVAILABLE
from ui.archive_library import ArchiveLibraryDialog
from ui.conversation_list import ConversationList
from ui.gallery_window import GalleryWindow
from ui.statistics_window import StatisticsWindow
from ui.formatting import day_long, plural
from ui.global_search import GlobalSearchPanel
from ui.information_panel import InformationPanel
from ui.media_viewer import ImageViewer, play_video
from ui.message_view import MessageView

from .settings import ZOOM_STEPS, AppSettings
from .styles import apply_theme, theme_for

APP_NAME = "Telegram Archive Explorer"
APP_VERSION = "1.1"
ICON_PATH = Path(__file__).parent / "resources" / "icon.svg"


class ReportDialog(QDialog):
    def __init__(self, text: str, parent=None, title: str = "Rapport d'importation") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        view = QPlainTextEdit(text, readOnly=True)
        view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        view.setLineWrapMode(QPlainTextEdit.NoWrap)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Fermer")
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(view)
        lay.addWidget(bb)
        self.resize(820, 620)


class Welcome(QWidget):
    def __init__(self, on_import_dir, on_import_files, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Welcome")
        title = QLabel("<h2>Votre bibliothèque est vide</h2>", alignment=Qt.AlignCenter)
        text = QLabel("Importez un export Telegram Desktop au format HTML\n"
                      "(dossier « ChatExport_… » contenant messages.html).\n"
                      "Les fichiers d'origine ne sont jamais modifiés ; tout reste sur cet ordinateur.",
                      alignment=Qt.AlignCenter)
        b1 = QPushButton("Importer un dossier d'export…", objectName="Primary")
        b1.clicked.connect(on_import_dir)
        b2 = QPushButton("Importer des fichiers HTML…")
        b2.clicked.connect(on_import_files)
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        lay.addWidget(title)
        lay.addWidget(text)
        lay.addSpacing(16)
        lay.addWidget(b1, 0, Qt.AlignHCenter)
        lay.addWidget(b2, 0, Qt.AlignHCenter)
        lay.addStretch(2)


class MainWindow(QMainWindow):
    def __init__(self, db_path: Path | None = None, settings: AppSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.settings = settings or AppSettings()
        self.db = Database(db_path)
        self.repo = LibraryRepository(self.db)
        self.theme = theme_for(self.settings.dark_mode)
        apply_theme(QApplication.instance(), self.theme)
        self._import_thread: QThread | None = None
        self._import_worker: ImportWorker | None = None
        self._import_dialog: QProgressDialog | None = None
        self.last_import_reports: list = []

        # --- Zones ---------------------------------------------------------
        self.engine = SearchEngine(self.db)
        self.conv_list = ConversationList()
        self.search_panel = GlobalSearchPanel(self.engine, self.theme)
        self.left = QStackedWidget()
        self.left.addWidget(self.conv_list)
        self.left.addWidget(self.search_panel)
        self.message_view = MessageView(self.repo, self.theme, self.engine)
        self.message_view.zoom = self.settings.zoom
        self.message_view.internal_video = self.settings.internal_video_player
        self.info_panel = InformationPanel(self.repo)
        self.info_panel.settings = self.settings

        self.center = QStackedWidget()
        self.welcome = Welcome(self.import_directory, self.import_files)
        self.center.addWidget(self.message_view)
        self.center.addWidget(self.welcome)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.center)
        self.splitter.addWidget(self.info_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        self.splitter.setSizes([320, 760, 300])
        self.splitter.setChildrenCollapsible(False)
        self.setCentralWidget(self.splitter)

        # --- Signaux -------------------------------------------------------
        self.conv_list.conversation_selected.connect(self.open_conversation)
        self.conv_list.sort_changed.connect(lambda m: setattr(self.settings, "conversation_sort", m))
        self.conv_list.archive_filter_changed.connect(self._on_archive_filter)
        self.archive_filter: int | None = None
        self.library_dialog: ArchiveLibraryDialog | None = None
        self.message_view.position_changed.connect(self._save_position)
        self.message_view.toggle_info_panel.connect(self.toggle_info_panel)
        self.info_panel.jump_requested.connect(lambda seq: self.message_view.jump_to_seq(seq))
        self.info_panel.open_media.connect(self._open_media)
        self.info_panel.day_requested.connect(self.message_view.go_to_day)
        self.message_view.day_changed.connect(self.info_panel.timeline.select_day)
        self.info_panel.timeline.set_accent(self.theme.accent)

        self.search_panel.hit_selected.connect(self.open_search_hit)
        self.search_panel.closed.connect(self.close_search)
        self.message_view.advanced_search_requested.connect(self.advanced_search_in)
        self._build_search_bar()
        self._build_menus()
        self.statusBar()

        geom, split = self.settings.window_state()
        if geom is not None:
            self.restoreGeometry(geom)
        else:
            self.resize(1380, 860)
        if split is not None:
            self.splitter.restoreState(split)
        self.conv_list.set_sort_mode(self.settings.conversation_sort)
        self._set_info_visible(self.settings.info_panel_visible)

        self.repo.backfill_file_hashes()       # archives importées avant la v2 du schéma
        self.refresh_library(restore=True)
        self._warn_missing_archives()

    # ================================================================== #
    # Menus
    # ================================================================== #

    def _build_search_bar(self) -> None:
        """Barre de recherche globale, en haut de la fenêtre."""
        bar = self.addToolBar("Recherche")
        bar.setObjectName("SearchBar")
        bar.setMovable(False)
        self.search_field = QLineEdit(placeholderText="🔍  Rechercher dans toutes les conversations…  (Ctrl+Maj+F)")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.setMinimumWidth(420)
        self.search_field.setMaximumWidth(760)
        self.search_field.textEdited.connect(self._on_search_text)
        self.search_field.returnPressed.connect(self._on_search_return)
        adv = QToolButton(text="Recherche avancée", toolTip="Filtres : conversation, expéditeur, dates, type…")
        adv.clicked.connect(self.open_advanced_search)
        bar.addWidget(self.search_field)
        bar.addWidget(adv)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        for text, tip, slot in (("🖼 Galerie", "Galerie multimédia (Ctrl+M)", self.open_gallery),
                                ("📊 Statistiques", "Statistiques (Ctrl+Maj+S)", self.open_statistics),
                                ("🗄 Bibliothèque", "Bibliothèque des archives (Ctrl+L)", self.open_library)):
            b = QToolButton(text=text, toolTip=tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        for w in (self.search_field, self.search_panel):
            QShortcut(QKeySequence(Qt.Key_Escape), w, activated=self.close_search,
                      context=Qt.WidgetWithChildrenShortcut)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu("&Fichier")
        self._add(m, "Importer un &dossier d'export…", self.import_directory, "Ctrl+O")
        self._add(m, "Importer des fichiers &HTML…", self.import_files, "Ctrl+Shift+O")
        self._add(m, "&Bibliothèque des archives…", self.open_library, "Ctrl+L")
        self._add(m, "&Galerie multimédia…", self.open_gallery, "Ctrl+M")
        self._add(m, "&Statistiques…", self.open_statistics, "Ctrl+Shift+S")
        m.addSeparator()
        self._add(m, "&Quitter", self.close, QKeySequence.Quit)

        v = mb.addMenu("&Affichage")
        self.act_dark = self._add(v, "Mode &sombre", self.toggle_dark, "Ctrl+Shift+D", checkable=True)
        self.act_dark.setChecked(self.settings.dark_mode)
        self.act_info = self._add(v, "Panneau d'&informations", self.toggle_info_panel, "Ctrl+I", checkable=True)
        v.addSeparator()
        self._add(v, "Zoom a&vant", lambda: self.change_zoom(1), QKeySequence.ZoomIn)
        self._add(v, "Zoom a&rrière", lambda: self.change_zoom(-1), QKeySequence.ZoomOut)
        self._add(v, "Taille &normale", lambda: self.change_zoom(0), "Ctrl+0")
        v.addSeparator()
        self._add(v, "Mon &nom dans les conversations…", self.choose_owner)
        self.act_video = self._add(v, "Lire les vidéos dans l'application", self.toggle_video_player, checkable=True)
        self.act_video.setChecked(self.settings.internal_video_player and MULTIMEDIA_AVAILABLE)
        self.act_video.setEnabled(MULTIMEDIA_AVAILABLE)
        if not MULTIMEDIA_AVAILABLE:
            self.act_video.setToolTip("Installer python3-pyside6.qtmultimedia et python3-pyside6.qtmultimediawidgets")
            self.act_video.setText("Lire les vidéos dans l'application (Qt Multimedia absent)")

        g = mb.addMenu("&Aller")
        mv = self.message_view
        self._add(g, "Aller à une &date…", mv.choose_date, "Ctrl+G")
        self._add(g, "&Premier message", mv.go_first, "Ctrl+Home")
        self._add(g, "&Dernier message", mv.go_last, "Ctrl+End")
        self._add(g, "&Retour", mv.go_back, "Alt+Left")
        g.addSeparator()
        self._add(g, "Jour &précédent", lambda: mv.step_day(-1), "Ctrl+PgUp")
        self._add(g, "Jour &suivant", lambda: mv.step_day(1), "Ctrl+PgDown")
        self._add(g, "&Mois précédent", lambda: mv.step_day(-1, "month"), "Ctrl+Shift+PgUp")
        self._add(g, "M&ois suivant", lambda: mv.step_day(1, "month"), "Ctrl+Shift+PgDown")
        self._add(g, "Afficher la &chronologie", self.show_timeline, "Ctrl+T")
        g.addSeparator()
        self._add(g, "Rechercher une &conversation", lambda: self.conv_list.search.setFocus(), "Ctrl+K")

        r = mb.addMenu("&Recherche")
        self._add(r, "Rechercher dans &toutes les conversations", self.focus_global_search, "Ctrl+Shift+F")
        self._add(r, "Rechercher dans cette &conversation", mv.open_find_bar, "Ctrl+F")
        self._add(r, "Recherche &avancée…", self.open_advanced_search, "Ctrl+Shift+A")
        self._add(r, "&Fermer la recherche", self.close_search)

        h = mb.addMenu("Aid&e")
        self._add(h, "&Raccourcis clavier", self.show_shortcuts, "F1")
        self._add(h, "À &propos", self.about)

    def _add(self, menu, text, slot, shortcut=None, checkable=False) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setCheckable(checkable)
        a.triggered.connect(lambda *_: slot())
        menu.addAction(a)
        return a

    # ================================================================== #
    # Bibliothèque
    # ================================================================== #

    def refresh_library(self, restore: bool = False) -> None:
        archives = self.repo.list_archives()
        self.conv_list.set_archives([(a.id, a.name) for a in archives])
        if self.archive_filter is not None and all(a.id != self.archive_filter for a in archives):
            self.archive_filter = None
        convs = self.repo.list_conversations(self.archive_filter)
        self.conv_list.set_conversations(convs)
        if self.left.currentWidget() is self.search_panel:
            self._refresh_search_filters()
        stats = self.repo.library_stats()
        self.statusBar().showMessage(
            f"{plural(stats['archives'], 'archive')} · {plural(stats['conversations'], 'conversation')} · "
            f"{plural(stats['messages'], 'message')} · {plural(stats['medias'], 'média')}")
        self.message_view.owner = self.settings.owner_name or self.repo.detect_owner()
        if not convs and not archives:
            self.center.setCurrentWidget(self.welcome)
            self.info_panel.set_conversation(None)
            self.message_view.open_conversation(None)
            return
        self.center.setCurrentWidget(self.message_view)
        target = self.conv_list.current_id()
        if restore or target is None:
            target = self.settings.last_conversation if any(c.id == self.settings.last_conversation for c in convs) \
                else None
        if target is None:
            target = convs[0].id
        self.conv_list.select(target, emit=False)
        self.open_conversation(target)

    def _on_archive_filter(self, archive_id) -> None:
        self.archive_filter = archive_id
        self.refresh_library()

    def _warn_missing_archives(self) -> None:
        missing = [a.name for a in self.repo.list_archives() if not a.root_exists]
        if missing:
            self.statusBar().showMessage(
                f"⚠ {plural(len(missing), 'archive')} introuvable(s) ({', '.join(missing[:3])}) : "
                "les messages restent consultables, mais pas les médias. "
                "Fichier → Bibliothèque des archives → Localiser…", 20000)

    def show_timeline(self) -> None:
        self._set_info_visible(True)
        self.info_panel.tabs.setCurrentWidget(self.info_panel.timeline)

    def open_gallery(self) -> None:
        win = GalleryWindow(self.repo, self, self.settings)
        if self.message_view.conv:
            win.set_conversation(self.message_view.conv.id)
        win.go_to_message.connect(self._go_to_message)
        win.show()
        self._gallery = win

    def open_statistics(self) -> None:
        win = StatisticsWindow(self.db, self.repo, self.theme, self)
        if self.message_view.conv:
            win.set_conversation(self.message_view.conv.id)
        win.go_to_day.connect(self._go_to_day)
        win.show()
        self._statistics = win

    def _go_to_message(self, conv_id: str, seq: int) -> None:
        if self.message_view.conv and self.message_view.conv.id == conv_id:
            self.message_view.jump_to_seq(seq, highlight=True)
        else:
            self.conv_list.select(conv_id, emit=False)
            self.open_conversation(conv_id, seq=seq, highlight=True)
        self.raise_()
        self.activateWindow()

    def _go_to_day(self, conv_id: str, day: str) -> None:
        if not self.message_view.conv or self.message_view.conv.id != conv_id:
            self.conv_list.select(conv_id, emit=False)
            self.open_conversation(conv_id)
        self.message_view.go_to_day(day)
        self.raise_()
        self.activateWindow()

    def open_library(self) -> None:
        if self.library_dialog is None:
            dlg = self.library_dialog = ArchiveLibraryDialog(self.repo, self)
            dlg.import_requested.connect(self.import_directory)
            dlg.reindex_requested.connect(lambda src: self.run_import([src], ask=False))
            dlg.library_changed.connect(self.refresh_library)
            dlg.show_report.connect(lambda title, text: ReportDialog(text, dlg, title).exec())
        self.library_dialog.refresh()
        self.library_dialog.show()
        self.library_dialog.raise_()

    def open_conversation(self, conv_id: str, seq: int | None = None, highlight: bool = False) -> None:
        conv = self.repo.get_conversation(conv_id)
        if conv is None:
            return
        self.settings.last_conversation = conv_id
        if seq is None:
            seq = self.settings.last_seq(conv_id)
            align = "top"
        else:
            align = "center"
        self.message_view.open_conversation(conv, seq, highlight=highlight, align=align)
        self.info_panel.set_conversation(conv)
        self.setWindowTitle(f"{conv.name} — {APP_NAME}")

    def _save_position(self, conv_id: str, seq: int) -> None:
        bounds = self.message_view.bounds
        # En bas de conversation : ne rien mémoriser (réouverture sur les derniers messages)
        sb = self.message_view.area.verticalScrollBar()
        at_bottom = sb.maximum() - sb.value() < 40 and bounds and self.message_view.rows \
            and self.message_view.rows[-1].seq >= bounds[1]
        self.settings.set_last_seq(conv_id, None if at_bottom else seq)

    # ================================================================== #
    # Importation
    # ================================================================== #

    def import_directory(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choisir un dossier d'export Telegram",
                                             self.settings.last_import_dir or str(Path.home()))
        if d:
            self.settings.last_import_dir = str(Path(d).parent)
            self.run_import([d])

    def import_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Choisir des fichiers HTML d'export",
                                                self.settings.last_import_dir or str(Path.home()),
                                                "Pages HTML (*.html *.htm)")
        if files:
            self.settings.last_import_dir = str(Path(files[0]).parent)
            self.run_import(files)

    def run_import(self, sources: list[str], ask: bool = True) -> None:
        if self._import_thread is not None:
            QMessageBox.information(self, APP_NAME, "Une importation est déjà en cours.")
            return
        known = {a.source_path for a in self.repo.list_archives()}
        again = [s for s in sources if str(Path(s).resolve()) in known]
        if ask and again and QMessageBox.question(
                self, "Réimporter ?",
                "Cette archive est déjà dans la bibliothèque :\n" + "\n".join(again)
                + "\n\nLa réimporter remplacera ses messages (sans créer de doublons). Continuer ?") \
                != QMessageBox.Yes:
            return
        self._import_dialog = dlg = QProgressDialog("Analyse de l'export…", "Annuler", 0, 0, self)
        dlg.setWindowTitle("Importation")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setMinimumWidth(480)
        self._import_thread, self._import_worker = start_import(sources, self.db.path, self)
        w = self._import_worker
        # Les signaux du thread d'importation doivent être reçus par des méthodes
        # de la fenêtre (objet du thread principal) : Qt les met alors en file
        # d'attente et les exécute dans le thread de l'interface.
        w.progress.connect(self._on_import_progress)
        w.finished.connect(self._on_import_finished)
        w.failed.connect(self._on_import_failed)
        # Annulation : simple drapeau, positionné directement (le thread est occupé)
        dlg.canceled.connect(w.cancel, Qt.DirectConnection)

    @Slot(int, int, str)
    def _on_import_progress(self, done: int, total: int, label: str) -> None:
        dlg = self._import_dialog
        if dlg is not None:
            dlg.setMaximum(total)
            dlg.setValue(done)
            dlg.setLabelText(label)

    def _end_import(self) -> None:
        if self._import_dialog is not None:
            self._import_dialog.close()
            self._import_dialog.deleteLater()
            self._import_dialog = None
        if self._import_thread is not None:
            self._import_thread.wait(5000)
        self._import_thread = None
        self._import_worker = None

    @Slot(list)
    def _on_import_finished(self, reports: list) -> None:
        self._end_import()
        self.refresh_library()
        if self.library_dialog is not None and self.library_dialog.isVisible():
            self.library_dialog.refresh()
        self.last_import_reports = reports
        if reports:
            self.show_import_report("\n\n".join(r[1] for r in reports))

    @Slot(str)
    def _on_import_failed(self, err: str) -> None:
        self._end_import()
        QMessageBox.critical(self, "Échec de l'importation", err[:3000])
        self.refresh_library()

    def show_import_report(self, text: str) -> None:
        ReportDialog(text, self).exec()

    # ================================================================== #
    # Affichage
    # ================================================================== #

    # ================================================================== #
    # Recherche
    # ================================================================== #

    def _refresh_search_filters(self) -> None:
        convs = self.repo.list_conversations()
        first = min((c.first_date for c in convs if c.first_date), default=None)
        last = max((c.last_date for c in convs if c.last_date), default=None)
        self.search_panel.filters.populate(
            [(c.id, c.name) for c in sorted(convs, key=lambda c: c.name.casefold())],
            [(a.id, a.name) for a in self.repo.list_archives()],
            self.engine.senders(), first, last)

    def show_search_panel(self) -> None:
        if self.left.currentWidget() is not self.search_panel:
            self._refresh_search_filters()
            self.left.setCurrentWidget(self.search_panel)

    def focus_global_search(self) -> None:
        self.search_field.setFocus()
        self.search_field.selectAll()

    def _on_search_text(self, text: str) -> None:
        if text.strip():
            self.show_search_panel()
        self.search_panel.set_text(text)

    def _on_search_return(self) -> None:
        self.show_search_panel()
        self.search_panel.set_text(self.search_field.text(), immediate=True)
        self.search_panel.focus_results()

    def open_advanced_search(self) -> None:
        self.show_search_panel()
        self.search_panel.filters_btn.setChecked(True)
        self.search_panel.set_text(self.search_field.text(), immediate=True)

    def advanced_search_in(self, text: str, conv_id: str) -> None:
        """Depuis la barre de recherche d'une conversation : recherche avancée filtrée sur elle."""
        self.search_field.setText(text)
        self.show_search_panel()
        self.search_panel.filters.set_conversation(conv_id)
        self.search_panel.filters_btn.setChecked(True)
        self.search_panel.set_text(text, immediate=True)

    def search(self, text: str) -> None:
        """Lance une recherche globale (utilisé aussi par les tests)."""
        self.search_field.setText(text)
        self.show_search_panel()
        self.search_panel.set_text(text, immediate=True)

    def open_search_hit(self, hit, terms: list[str]) -> None:
        """Ouvre la conversation du résultat, positionnée sur le message, surligné."""
        self.message_view.terms = list(terms)
        if self.message_view.conv is None or self.message_view.conv.id != hit.conversation_id:
            self.conv_list.select(hit.conversation_id, emit=False)
            self.open_conversation(hit.conversation_id, seq=hit.seq, highlight=True)
        else:
            self.message_view.reload()
            self.message_view.jump_to_seq(hit.seq, highlight=True)
        self.statusBar().showMessage(
            f"{hit.conversation_name} · {hit.sender or ''} · {day_long((hit.date_local or '')[:10] or None)}", 4000)

    def close_search(self) -> None:
        if self.left.currentWidget() is self.search_panel:
            self.left.setCurrentWidget(self.conv_list)
            current = self.message_view.conv
            if current:
                self.conv_list.select(current.id, emit=False)
        self.message_view.set_highlight_terms([])

    def toggle_dark(self) -> None:
        self.settings.dark_mode = self.act_dark.isChecked()
        self.theme = theme_for(self.settings.dark_mode)
        apply_theme(QApplication.instance(), self.theme)
        self.message_view.set_theme(self.theme)
        self.search_panel.set_theme(self.theme)
        self.info_panel.timeline.set_accent(self.theme.accent)

    def toggle_info_panel(self) -> None:
        self._set_info_visible(not self.info_panel.isVisible())

    def _set_info_visible(self, visible: bool) -> None:
        self.info_panel.setVisible(visible)
        self.settings.info_panel_visible = visible
        self.act_info.setChecked(visible)
        self.message_view.info_btn.setChecked(visible)

    def change_zoom(self, direction: int) -> None:
        z = self.settings.zoom
        if direction == 0:
            z = 100
        else:
            steps = list(ZOOM_STEPS)
            i = min(range(len(steps)), key=lambda k: abs(steps[k] - z))
            z = steps[max(0, min(len(steps) - 1, i + direction))]
        self.settings.zoom = z
        self.message_view.set_zoom(z)
        self.statusBar().showMessage(f"Zoom : {z} %", 2000)

    def toggle_video_player(self) -> None:
        self.settings.internal_video_player = self.act_video.isChecked()
        self.message_view.internal_video = self.act_video.isChecked()

    def choose_owner(self) -> None:
        names = sorted({r[0] for r in self.db.conn.execute(
            "SELECT DISTINCT name FROM participants")}, key=str.casefold)
        detected = self.repo.detect_owner()
        options = ["(aucun — tous les messages à gauche)"] + names
        current = self.settings.owner_name or detected
        idx = options.index(current) if current in options else 0
        name, ok = QInputDialog.getItem(
            self, "Mon nom", "Vos messages s'affichent à droite, en vert.\n"
            + (f"Détecté automatiquement : {detected}\n" if detected else "") + "Qui êtes-vous ?",
            options, idx, False)
        if ok:
            owner = None if name == options[0] else name
            self.settings.owner_name = owner or ""
            self.message_view.set_owner(owner)

    def _open_media(self, media) -> None:
        if media.media_type == "photo":
            items = self.repo.medias(self.message_view.conv.id, ("photo",))
            idx = next((i for i, m in enumerate(items) if m.id == media.id), 0)
            ImageViewer(items, idx, self).exec()
        elif media.file_available:
            play_video(media.abs_file, self, self.settings.internal_video_player)
        else:
            QMessageBox.information(self, APP_NAME, f"Fichier introuvable :\n{media.file_path}")

    def show_shortcuts(self) -> None:
        rows = [("Importer un dossier d'export", "Ctrl+O"), ("Bibliothèque des archives", "Ctrl+L"),
                ("Galerie multimédia", "Ctrl+M"),
                ("Galerie : copier la sélection vers un dossier", "Ctrl+Maj+C  (Ctrl/Maj + clic pour sélectionner)"),
                ("Statistiques", "Ctrl+Maj+S"),
                ("Rechercher dans toutes les conversations", "Ctrl+Maj+F"),
                ("Rechercher dans la conversation", "Ctrl+F  (Entrée / Maj+Entrée)"),
                ("Recherche avancée", "Ctrl+Maj+A"), ("Rechercher une conversation par nom", "Ctrl+K"),
                ("Aller à une date", "Ctrl+G"), ("Jour précédent / suivant", "Ctrl+PgPréc / Ctrl+PgSuiv"),
                ("Mois précédent / suivant", "Ctrl+Maj+PgPréc / PgSuiv"), ("Chronologie", "Ctrl+T"),
                ("Premier / dernier message", "Ctrl+Début / Ctrl+Fin"), ("Revenir après un saut", "Alt+←"),
                ("Panneau d'informations", "Ctrl+I"), ("Zoom avant / arrière / normal", "Ctrl++ / Ctrl+− / Ctrl+0"),
                ("Mode sombre", "Ctrl+Maj+D"), ("Fermer la recherche, une visionneuse", "Échap")]
        html = "<table cellspacing='6'>" + "".join(
            f"<tr><td>{a}</td><td><b>{k}</b></td></tr>" for a, k in rows) + "</table>"
        box = QMessageBox(self)
        box.setWindowTitle("Raccourcis clavier")
        box.setTextFormat(Qt.RichText)
        box.setText(html)
        box.exec()

    def about(self) -> None:
        QMessageBox.about(self, APP_NAME,
                          f"<b>{APP_NAME}</b> {APP_VERSION}<br>Bibliothèque personnelle de conversations Telegram."
                          "<br><br>"
                          "Fonctionnement 100 % local : aucune donnée n'est transmise.<br>"
                          f"Bibliothèque : <code>{self.db.path}</code>")

    # ================================================================== #

    def closeEvent(self, e) -> None:  # noqa: N802
        self.message_view._emit_position()
        self.settings.save_window_state(self.saveGeometry(), self.splitter.saveState())
        self.settings.sync()
        if self._import_worker is not None:
            self._import_worker.cancel()
        if self._import_thread is not None:
            self._import_thread.quit()
            self._import_thread.wait(5000)
        self.db.close()
        super().closeEvent(e)


def run_gui(argv: list[str], db_path: Path | None = None) -> int:
    # Messages techniques de FFmpeg (décodage matériel…) inutiles pour l'utilisateur
    QLoggingCategory.setFilterRules("qt.multimedia.ffmpeg.info=false\nqt.multimedia.ffmpeg.debug=false")
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName("telegram-archive-explorer")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    # Boutons standard de Qt (Oui, Non, Annuler, Fermer…) en français si les
    # traductions sont installées (paquet Debian qt6-translations-l10n)
    from PySide6.QtCore import QLibraryInfo, QTranslator
    tr = QTranslator(app)
    if tr.load("qtbase_fr", QLibraryInfo.path(QLibraryInfo.TranslationsPath)) or \
            tr.load("qtbase_fr", "/usr/share/qt6/translations"):
        app.installTranslator(tr)
    f = app.font()
    if f.pointSizeF() < 10:
        f.setPointSizeF(10)
        app.setFont(f)
    win = MainWindow(db_path)
    win.show()
    return app.exec()

