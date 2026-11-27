"""Outils de maintenance : diagnostic, fichiers identiques, sauvegarde et
restauration, composants installés, mises à jour.

Les traitements longs (diagnostic, empreintes) tournent dans un thread avec
leur propre connexion SQLite et peuvent être annulés.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from html import escape

from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem,
    QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app import design, icons
from database.db_manager import Database
from database.repositories import LibraryRepository
from services import backup, dependencies, diagnostics, media_dedup, update_check
from services.media_service import human_size, show_in_folder
from ui.components import dialog_header
from ui.formatting import parse_iso, plural


# --------------------------------------------------------------------------- #
# Exécution en arrière-plan
# --------------------------------------------------------------------------- #

class _Worker(QObject):
    progress = Signal(str, int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path: Path, job) -> None:
        super().__init__()
        self.db_path, self.job, self.cancelled = db_path, job, False

    def run(self) -> None:
        try:
            with Database(self.db_path) as db:          # connexion propre au thread
                result = self.job(db, LibraryRepository(db), self._tick)
            self.done.emit(result)
        except Exception as exc:  # signalé à l'utilisateur, jamais silencieux
            self.failed.emit(str(exc))

    def _tick(self, label: str, i: int, n: int) -> bool:
        self.progress.emit(label, i, n)
        return not self.cancelled


def run_in_thread(owner: QObject, db_path: Path, job, on_progress, on_done, on_failed) -> tuple[QThread, _Worker]:
    thread = QThread(owner)
    worker = _Worker(db_path, job)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.progress.connect(on_progress)
    worker.done.connect(on_done)
    worker.failed.connect(on_failed)
    for sig in (worker.done, worker.failed):
        sig.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    return thread, worker


def _header_layout(dialog: QDialog, title: str, subtitle: str, icon: str) -> QVBoxLayout:
    lay = QVBoxLayout(dialog)
    lay.setContentsMargins(22, 20, 22, 16)
    lay.setSpacing(12)
    lay.addWidget(dialog_header(title, subtitle, icon))
    return lay


# --------------------------------------------------------------------------- #
# Diagnostic
# --------------------------------------------------------------------------- #

class DiagnosticsDialog(QDialog):
    rebuild_index = Signal()

    def __init__(self, db_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnostic de la bibliothèque")
        self.db_path = db_path
        self.report: diagnostics.DiagnosticReport | None = None
        self._thread = self._worker = None
        self.orphans = QCheckBox("Rechercher aussi les fichiers non référencés dans les dossiers d'export")
        self.orphans.setChecked(True)
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.hide()
        self.summary = QLabel("Le diagnostic contrôle la base SQLite, l'index de recherche, les archives, les "
                              "médias, les fils de discussion et vos données personnelles. Il ne corrige rien et "
                              "ne touche jamais aux exports ; il actualise seulement l'état de présence des médias.")
        self.summary.setWordWrap(True)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.run_btn = QPushButton("Lancer le diagnostic")
        self.run_btn.setProperty("variant", "primary")
        icons.bind(self.run_btn, "activity", "surface", 16, "surface", "surface")
        self.run_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Interrompre")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.hide()
        self.export_btn = QPushButton("Exporter le rapport…")
        icons.bind(self.export_btn, "export", "muted", 16)
        self.export_btn.clicked.connect(self._export)
        self.export_btn.setEnabled(False)
        self.fix_btn = QPushButton("Reconstruire l'index de recherche")
        icons.bind(self.fix_btn, "refresh", "muted", 16)
        self.fix_btn.setToolTip("Action explicite : reconstruit l'index plein texte à partir des messages")
        self.fix_btn.clicked.connect(self._rebuild)
        self.fix_btn.hide()
        close = QPushButton("Fermer")
        close.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(self.export_btn)
        btns.addWidget(self.fix_btn)
        btns.addStretch(1)
        btns.addWidget(close)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.run_btn)
        lay = _header_layout(self, "Diagnostic de la bibliothèque", "Aucune correction automatique, exports "
                             "jamais modifiés", "activity")
        lay.addWidget(self.orphans)
        lay.addWidget(self.bar)
        lay.addWidget(self.summary)
        lay.addWidget(self.view, 1)
        lay.addLayout(btns)
        self.resize(860, 620)

    def start(self) -> None:
        self.view.clear()
        self.bar.show()
        self.bar.setRange(0, 0)
        self.run_btn.setEnabled(False)
        self.cancel_btn.show()
        self.export_btn.setEnabled(False)
        scan = self.orphans.isChecked()
        job = lambda db, repo, tick: diagnostics.run_diagnostics(db, repo, scan, tick)  # noqa: E731
        self._thread, self._worker = run_in_thread(self, self.db_path, job, self._progress, self._done, self._failed)

    def _progress(self, label: str, i: int, n: int) -> None:
        self.bar.setRange(0, n)
        self.bar.setValue(i)
        self.bar.setFormat(f"{label} ({i}/{n})")

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancelled = True

    def _failed(self, msg: str) -> None:
        self._finish()
        QMessageBox.critical(self, "Diagnostic", f"Le diagnostic a échoué :\n{msg}")

    def _finish(self) -> None:
        self.bar.hide()
        self.run_btn.setEnabled(True)
        self.cancel_btn.hide()

    def _done(self, rep: diagnostics.DiagnosticReport) -> None:
        self._finish()
        self.report = rep
        self.export_btn.setEnabled(True)
        t = design.current()
        checked = ", ".join(f"{k.lower()} : {v:,}".replace(",", " ") for k, v in rep.checked.items())
        self.summary.setText(f"<b>{rep.summary()}</b> ({rep.duration_s:.1f} s)<br>"
                             f"<span style='color:{t.muted}'>Contrôlé — {checked}</span>")
        colors = {diagnostics.ERROR: t.danger, diagnostics.WARNING: t.warning, diagnostics.INFO: t.accent}
        parts = []
        for f in sorted(rep.findings, key=lambda f: diagnostics.SEVERITY_ORDER[f.severity]):
            col = colors[f.severity]
            count = f" <span style='color:{t.muted}'>({f.count:,})</span>".replace(",", "\u202f") if f.count else ""
            block = [f"<p style='margin:10px 0 2px'><span style='color:{col}; font-weight:600'>"
                     f"● {escape(diagnostics.SEVERITY_LABELS[f.severity])}</span> — <b>{escape(f.title)}</b>{count}</p>"]
            if f.details:
                block.append("<ul style='margin:0'>" + "".join(f"<li>{escape(d)}</li>" for d in f.details) + "</ul>")
            if f.recommendation:
                block.append(f"<p style='margin:2px 0 0 0; color:{t.accent_text}'>Recommandation : "
                             f"{escape(f.recommendation)}</p>")
            parts.append("".join(block))
        if not rep.findings:
            parts.append(f"<p style='color:{t.success}'>● Aucun constat : la bibliothèque est cohérente.</p>")
        self.view.setHtml("".join(parts))
        self.fix_btn.setVisible(any(f.category == "Recherche" for f in rep.errors))

    def _export(self) -> None:
        if not self.report:
            return
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getSaveFileName(self, "Exporter le rapport", str(Path(base) / "diagnostic-telegramor.md"),
                                              "Markdown (*.md);;Texte (*.txt)")
        if path:
            Path(path).write_text(self.report.to_markdown(), encoding="utf-8")
            show_in_folder(Path(path))

    def _rebuild(self) -> None:
        if QMessageBox.question(self, "Reconstruire l'index", "Reconstruire l'index de recherche à partir des "
                                "messages de la bibliothèque ? Les archives d'origine ne sont pas touchées.") \
                == QMessageBox.Yes:
            self.rebuild_index.emit()
            self.start()

    def closeEvent(self, e) -> None:  # noqa: N802
        if self._thread is not None and self._thread.isRunning():
            self._cancel()
            self._thread.quit()
            self._thread.wait(10000)
        super().closeEvent(e)


# --------------------------------------------------------------------------- #
# Fichiers identiques
# --------------------------------------------------------------------------- #

class DuplicatesDialog(QDialog):
    go_to = Signal(str, int)

    def __init__(self, db: Database, repo: LibraryRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fichiers identiques")
        self.db, self.repo = db, repo
        self._thread = self._worker = None
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.hide()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Fichier / occurrence", "Conversation", "Expéditeur", "Date"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.itemDoubleClicked.connect(self._go)
        self.hash_btn = QPushButton("Calculer les empreintes")
        self.hash_btn.setProperty("variant", "primary")
        icons.bind(self.hash_btn, "refresh", "surface", 16, "surface", "surface")
        self.hash_btn.clicked.connect(self.compute)
        self.cancel_btn = QPushButton("Interrompre")
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(lambda: self._worker and setattr(self._worker, "cancelled", True))
        go = QPushButton("Aller au message")
        go.clicked.connect(lambda: self.tree.currentItem() and self._go(self.tree.currentItem()))
        close = QPushButton("Fermer")
        close.clicked.connect(self.close)
        note = QLabel("Empreinte SHA-256 : seuls les fichiers strictement identiques sont regroupés. Rien n'est "
                      "supprimé ni déplacé ; chaque occurrence garde sa provenance. Dans la galerie, l'option "
                      "« Masquer les fichiers identiques » n'affiche qu'une occurrence.")
        note.setWordWrap(True)
        note.setProperty("role", "caption")
        btns = QHBoxLayout()
        btns.addWidget(go)
        btns.addStretch(1)
        btns.addWidget(close)
        btns.addWidget(self.cancel_btn)
        btns.addWidget(self.hash_btn)
        lay = _header_layout(self, "Fichiers identiques", "Médias présents plusieurs fois dans vos exports", "copy")
        lay.addWidget(self.info)
        lay.addWidget(self.bar)
        lay.addWidget(self.tree, 1)
        lay.addWidget(note)
        lay.addLayout(btns)
        self.resize(900, 600)
        self.refresh()

    def refresh(self) -> None:
        st = media_dedup.stats(self.db)
        text = (f"<b>{plural(st['groups'], 'fichier')} présent(s) plusieurs fois</b> — "
                f"{plural(st['extra_copies'], 'copie')} supplémentaire(s), {human_size(st['extra_bytes'])}.")
        if st["pending"]:
            text += f"<br>{plural(st['pending'], 'média')} sans empreinte : lancez le calcul pour les inclure."
        self.info.setText(text)
        self.hash_btn.setEnabled(bool(st["pending"]))
        self.tree.clear()
        t = design.current()
        for g in media_dedup.duplicate_groups(self.db, self.repo, limit=500):
            first = g.occurrences[0]
            name = first.path.name if first.path else "fichier"
            top = QTreeWidgetItem(self.tree, [f"{name} — {len(g.occurrences)} occurrences, {human_size(g.size)}",
                                              "", "", ""])
            top.setIcon(0, icons.icon(icons.MEDIA_ICONS.get(first.media_type, "file"), t.muted, 16))
            top.setToolTip(0, f"SHA-256 {g.sha256}")
            for o in g.occurrences:
                dt = parse_iso(o.date_local)
                it = QTreeWidgetItem(top, [str(o.path or ""), o.conversation_name, o.sender or "",
                                           dt.strftime("%d/%m/%Y %H:%M") if dt else ""])
                it.setData(0, Qt.UserRole, (o.conversation_id, o.seq))
        self.tree.expandToDepth(0)

    def compute(self) -> None:
        self.bar.show()
        self.bar.setRange(0, 0)
        self.hash_btn.setEnabled(False)
        self.cancel_btn.show()

        def job(db, repo, tick):
            return media_dedup.compute_hashes(db, repo, lambda i, n: tick("Empreintes", i, n))

        self._thread, self._worker = run_in_thread(self, self.db.path, job, self._progress, self._done, self._failed)

    def _progress(self, _label: str, i: int, n: int) -> None:
        self.bar.setRange(0, max(n, 1))
        self.bar.setValue(i)
        self.bar.setFormat(f"Empreintes : {i} / {n}")

    def _done(self, s: media_dedup.HashSummary) -> None:
        self.bar.hide()
        self.cancel_btn.hide()
        self.refresh()
        if s.errors:
            QMessageBox.warning(self, "Empreintes", f"{len(s.errors)} fichier(s) illisible(s) :\n"
                                + "\n".join(f"{p} : {e}" for p, e in s.errors[:8]))

    def _failed(self, msg: str) -> None:
        self.bar.hide()
        self.cancel_btn.hide()
        QMessageBox.critical(self, "Empreintes", msg)

    def _go(self, item: QTreeWidgetItem, _c: int = 0) -> None:
        data = item.data(0, Qt.UserRole)
        if data:
            self.go_to.emit(*data)

    def closeEvent(self, e) -> None:  # noqa: N802
        if self._thread is not None and self._thread.isRunning():
            self._worker.cancelled = True
            self._thread.quit()
            self._thread.wait(10000)
        super().closeEvent(e)


# --------------------------------------------------------------------------- #
# Sauvegarde et restauration
# --------------------------------------------------------------------------- #

class BackupDialog(QDialog):
    personal_restored = Signal()
    library_restore_requested = Signal(str)      # chemin de la sauvegarde (redémarrage nécessaire)

    def __init__(self, db: Database, settings_file: Path | None, app_version: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sauvegarde et restauration")
        self.db, self.settings_file, self.app_version = db, settings_file, app_version
        what = QLabel(
            "<b>Contenu d'une sauvegarde</b> (archive ZIP privée) :<ul>"
            "<li>vos données personnelles : favoris, notes, collections, marqueurs de lecture, recherches "
            "enregistrées ;</li><li>la bibliothèque complète (base SQLite et index), copiée de façon cohérente "
            "même pendant l'utilisation ;</li><li>les paramètres de l'application.</li></ul>"
            "<b>Non sauvegardés :</b> les exports Telegram eux-mêmes (HTML et médias). Ils restent là où vous "
            "les avez placés ; conservez-les de votre côté. Après une restauration sur un autre ordinateur, "
            "relocalisez les archives depuis la bibliothèque.")
        what.setWordWrap(True)
        what.setTextFormat(Qt.RichText)
        self.with_library = QCheckBox("Inclure la bibliothèque complète (recommandé)")
        self.with_library.setChecked(True)
        save = QPushButton("Créer une sauvegarde…")
        save.setProperty("variant", "primary")
        icons.bind(save, "save", "surface", 16, "surface", "surface")
        save.clicked.connect(self.create)
        restore = QPushButton("Restaurer une sauvegarde…")
        icons.bind(restore, "refresh", "muted", 16)
        restore.clicked.connect(self.restore)
        close = QPushButton("Fermer")
        close.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(restore)
        btns.addStretch(1)
        btns.addWidget(close)
        btns.addWidget(save)
        lay = _header_layout(self, "Sauvegarde et restauration", "Tout reste local : le fichier est créé où vous "
                             "le choisissez", "save")
        lay.addWidget(what)
        lay.addWidget(self.with_library)
        lay.addStretch(1)
        lay.addLayout(btns)
        self.resize(640, 420)

    def create(self) -> None:
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer la sauvegarde",
                                              str(Path(base) / backup.default_backup_name()), "Sauvegarde (*.zip)")
        if not path:
            return
        path = Path(path) if path.endswith(".zip") else Path(path + ".zip")
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            man = backup.create_backup(self.db, path, self.app_version, self.settings_file,
                                       self.with_library.isChecked())
        except (OSError, Exception) as exc:
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Sauvegarde", f"La sauvegarde a échoué :\n{exc}")
            return
        QGuiApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Sauvegarde terminée",
                                f"{man.describe()}\n\nFichier : {path} ({human_size(path.stat().st_size)})\n"
                                "Droits : lecture et écriture pour vous seul.")

    def restore(self) -> None:
        base = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
        path, _ = QFileDialog.getOpenFileName(self, "Choisir une sauvegarde", base, "Sauvegarde (*.zip)")
        if not path:
            return
        try:
            man = backup.read_manifest(Path(path))
        except backup.BackupError as exc:
            QMessageBox.warning(self, "Restauration", str(exc))
            return
        dlg = RestoreChoiceDialog(man, self)
        if dlg.exec() != QDialog.Accepted:
            return
        choice = dlg.choice()
        try:
            if choice == "library":
                self.library_restore_requested.emit(path)
                return
            added = backup.restore_personal_data(self.db, Path(path), replace=(choice == "replace"))
        except backup.BackupError as exc:
            QMessageBox.warning(self, "Restauration", str(exc))
            return
        self.personal_restored.emit()
        QMessageBox.information(self, "Restauration terminée", "Données personnelles restaurées :\n"
                                + "\n".join(f"· {v} {k}" for k, v in added.items()))


class RestoreChoiceDialog(QDialog):
    def __init__(self, man: backup.BackupManifest, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Restaurer")
        desc = QLabel(man.describe())
        desc.setWordWrap(True)
        self.merge = QRadioButton("Fusionner mes données personnelles (l'existant est conservé)")
        self.replace = QRadioButton("Remplacer mes données personnelles par celles de la sauvegarde")
        self.library = QRadioButton("Restaurer toute la bibliothèque (redémarrage de l'application)")
        self.merge.setChecked(True)
        self.library.setEnabled(backup.LIBRARY in man.contents)
        if not self.library.isEnabled():
            self.library.setToolTip("Cette sauvegarde ne contient que les données personnelles.")
        group = QButtonGroup(self)
        for b in (self.merge, self.replace, self.library):
            group.addButton(b)
        warn = QLabel("La restauration complète vérifie l'intégrité de la base sauvegardée, puis remplace la "
                      "bibliothèque actuelle ; celle-ci est conservée à côté (fichier « avant-restauration »).")
        warn.setWordWrap(True)
        warn.setProperty("role", "caption")
        bb = QDialogButtonBox()
        bb.addButton("Annuler", QDialogButtonBox.RejectRole)
        ok = bb.addButton("Restaurer", QDialogButtonBox.AcceptRole)
        ok.setProperty("variant", "primary")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = _header_layout(self, "Restaurer une sauvegarde", "", "refresh")
        lay.addWidget(desc)
        for b in (self.merge, self.replace, self.library):
            lay.addWidget(b)
        lay.addWidget(warn)
        lay.addWidget(bb)

    def choice(self) -> str:
        return "library" if self.library.isChecked() else ("replace" if self.replace.isChecked() else "merge")


# --------------------------------------------------------------------------- #
# Composants installés
# --------------------------------------------------------------------------- #

class DependenciesDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Composants de Telegramor")
        statuses = dependencies.check_all()
        t = design.current()
        table = QTableWidget(len(statuses), 4)
        table.setHorizontalHeaderLabels(["Composant", "État", "Utilité", "Si absent"])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.setWordWrap(True)
        for r, s in enumerate(statuses):
            kind = "obligatoire" if s.dep.required else "facultatif"
            name = QTableWidgetItem(f"{s.dep.label}\n{s.dep.debian} ({kind})")
            state = QTableWidgetItem("Installé" if s.available else "Absent")
            state.setIcon(icons.icon("check" if s.available else "alert",
                                     t.success if s.available else (t.danger if s.dep.required else t.warning), 16))
            state.setToolTip(s.detail)
            table.setItem(r, 0, name)
            table.setItem(r, 1, state)
            table.setItem(r, 2, QTableWidgetItem(s.dep.purpose))
            table.setItem(r, 3, QTableWidgetItem("—" if s.available else s.dep.without))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        table.resizeRowsToContents()
        cmd = dependencies.install_command(statuses)
        self.cmd = QLineEdit(cmd or "Tous les composants sont installés.")
        self.cmd.setReadOnly(True)
        copy = QPushButton("Copier la commande")
        icons.bind(copy, "copy", "muted", 16)
        copy.setEnabled(bool(cmd))
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(cmd))
        row = QHBoxLayout()
        row.addWidget(self.cmd, 1)
        row.addWidget(copy)
        note = QLabel("Telegramor n'installe jamais rien lui-même : copiez la commande et exécutez-la dans un "
                      "terminal. Redémarrez ensuite l'application.")
        note.setWordWrap(True)
        note.setProperty("role", "caption")
        close = QPushButton("Fermer")
        close.setProperty("variant", "primary")
        close.clicked.connect(self.accept)
        lay = _header_layout(self, "Composants de Telegramor",
                             f"Distribution détectée : {dependencies.detect_distribution()}", "shield")
        lay.addWidget(table, 1)
        cap = QLabel("COMMANDE D'INSTALLATION DES COMPOSANTS ABSENTS")
        cap.setProperty("role", "overline")
        lay.addWidget(cap)
        lay.addLayout(row)
        lay.addWidget(note)
        lay.addWidget(close, 0, Qt.AlignRight)
        self.resize(900, 560)


# --------------------------------------------------------------------------- #
# Mises à jour
# --------------------------------------------------------------------------- #

class _UpdateWorker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, current: str) -> None:
        super().__init__()
        self.current = current

    def run(self) -> None:
        try:
            self.done.emit(update_check.check_latest(self.current))
        except Exception as exc:  # hors ligne, délai dépassé, réponse inattendue
            self.failed.emit(str(exc))


def check_updates_async(owner: QObject, current: str, on_done, on_failed) -> QThread:
    thread = QThread(owner)
    worker = _UpdateWorker(current)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(on_done)
    worker.failed.connect(on_failed)
    for sig in (worker.done, worker.failed):
        sig.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread._worker = worker          # garde une référence
    thread.start()
    return thread


def show_update_result(parent: QWidget, info: update_check.UpdateInfo) -> None:
    if not info.newer:
        QMessageBox.information(parent, "Mises à jour", f"Telegramor est à jour (version {info.current}).\n"
                                f"Dernière version publiée : {info.latest}"
                                + (f" ({info.published})" if info.published else ""))
        return
    box = QMessageBox(QMessageBox.Information, "Nouvelle version disponible",
                      f"Version installée : {info.current}\nVersion disponible : {info.latest}"
                      + (f"\nPubliée le : {info.published}" if info.published else "")
                      + "\n\nRien n'est téléchargé automatiquement : la page officielle de la version "
                        "s'ouvre dans votre navigateur.", parent=parent)
    if info.notes:
        box.setDetailedText(info.notes)
    open_btn = box.addButton("Voir la version et ses notes", QMessageBox.AcceptRole)
    box.addButton("Plus tard", QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is open_btn:
        QDesktopServices.openUrl(QUrl(info.url))
