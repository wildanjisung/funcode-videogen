from __future__ import annotations

from dataclasses import asdict
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QProcess, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QPlainTextEdit, QProgressBar, QMenu, QStackedWidget, QTabBar, QSlider, QSizePolicy, QVBoxLayout, QWidget,
)

from videogen.application.projects import load_project, record_evaluation, save_draft, normalize_draft, _append_event
from videogen.domain.hook import HookStyle
from videogen.domain.subtitle_style import SubtitleStyle
from videogen.presentation.hook_style_editor import HookStyleEditor
from videogen.presentation.hook_preview import HookPreview
from videogen.infrastructure.logging_config import default_log_path


PROMPT = """Saya ingin membuat judul hook untuk video pendek berdasarkan transkrip berikut.

Pahami topik utama, masalah atau ketegangan yang dibahas, dan manfaat yang akan didapat penonton. Buat SATU judul hook yang menarik perhatian dan membuat orang ingin melanjutkan menonton.

Ketentuan:
- Hook harus sesuai konteks dan isi transkrip.
- Gunakan rasa penasaran, masalah yang relevan, atau manfaat yang spesifik.
- Jangan mengarang fakta, angka, janji, atau detail visual.
- Gunakan bahasa yang sama dengan transkrip, kecuali arahan saya meminta bahasa lain.
- Usahakan singkat, sekitar 6–12 kata, agar nyaman ditampilkan dalam 1–3 baris.
- Tulis dalam HURUF KAPITAL.
- Berikan hanya judul final, tanpa penjelasan, alternatif, penomoran, tanda kutip, atau Markdown.

Arahan khusus saya:
{instruction}

TRANSKRIP VIDEO:
{transcript}"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Videogen — Hook Text")
        self.resize(1040, 720)
        self.setMinimumSize(800, 600)
        self._video_duration = 0.0
        self._video_width = 720
        self._video_height = 1280
        self.hook_style: dict | None = None
        self.subtitle_style = asdict(SubtitleStyle())
        self._style_editing = False
        self._style_editor = None
        self.last_video: Path | None = None
        self.source: Path | None = None
        self.project_dir: Path | None = None
        self.output_dir = Path.home() / "Videos" / "Videogen"
        self.log_path = default_log_path()
        self.last_result_dir: Path | None = None
        self._line_buffer = ""
        self._terminal: dict | None = None
        self._operation = ""
        self._stopping = False
        self._cancel_requested = False
        self._preview_request = 0
        self._preview_valid = False
        self._preview_image: QPixmap | None = None
        self._preview_words_hash = None
        self._preview_process: QProcess | None = None
        self._preview_temp: Path | None = None
        self._preview_request_path: Path | None = None
        self._active_request: Path | None = None
        self._draft_loading = False

        self.file_label = QLabel("Belum ada video dipilih")
        self.choose_button = QPushButton("Pilih video")
        self.project_button = QPushButton("Buka proyek")
        self.project_folder_button = QPushButton("Buka folder proyek / log")
        self.project_folder_button.setEnabled(False)
        self.output_label = QLabel(f"Folder hasil: {self.output_dir}")
        self.folder_button = QPushButton("Pilih folder hasil")
        self.transcribe_button = QPushButton("Transkripsikan video")
        self.cancel_button = QPushButton("Batalkan proses")
        self.cancel_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        self.preview_progress = QProgressBar()
        self.preview_progress.setTextVisible(False)
        self.preview_progress.setMaximumHeight(6)
        self.preview_progress.hide()
        self.status_label = QLabel("Pilih video baru atau buka proyek tersimpan.")
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("Transkrip proyek aktif akan tampil di sini.")
        self.transcript.setMaximumBlockCount(100000)
        self.copy_transcript_button = QPushButton("Copy transkrip")
        self.copy_prompt_button = QPushButton("Copy prompt + transkrip")
        self.instruction = QLineEdit()
        self.instruction.setPlaceholderText("Arahan khusus, misalnya: fokuskan pada biaya tersembunyi")
        self.hook_enabled = QCheckBox("Tampilkan hook")
        self.hook_enabled.setChecked(True)
        self.hook_text = QPlainTextEdit()
        self.hook_text.setPlaceholderText("Paste atau tulis judul hook. Gunakan newline untuk pemenggalan manual.")
        self.wrap_mode = QComboBox()
        self.wrap_mode.addItems(["Otomatis", "Manual"])
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.1, 86400)
        self.duration.setDecimals(1)
        self.duration.setValue(5.0)
        self.duration.setSuffix(" detik")
        self.full_video = QCheckBox("Sepanjang video")
        self.top_position = QDoubleSpinBox()
        self.top_position.setRange(-1000000, 1000000)
        self.top_position.setValue(15)
        self.top_position.setDecimals(3)
        self.top_position.setSuffix("% tinggi frame")
        self.paste_button = QPushButton("Paste hook")
        self.render_button = QPushButton("Render video")
        self.render_button.setEnabled(False)
        self.open_button = QPushButton("Buka folder hasil")
        self.open_button.setEnabled(False)
        self.preview_label = HookPreview("Preview hook + subtitle")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(270, 440)
        self.preview_label.setStyleSheet("background:#222;color:white")
        self.preview_status = QLabel("Preview menunggu proyek dan judul hook.")
        self.hook_lines_label = QLabel("Hook: belum di-layout")
        self.preview_slider = QSlider(Qt.Orientation.Horizontal)
        self.preview_slider.setRange(0, 1000)
        self.preview_slider.setEnabled(False)
        self.evaluation_button = QPushButton("Catat evaluasi / keluhan")
        self.evaluation_button.setEnabled(False)

        self.stage_label = QLabel("1. Video   →   2. Hook   →   3. Hasil")
        self.stage_label.setStyleSheet("font-size:18px;padding:8px")
        self.setStyleSheet('QPushButton[primary="true"] { background:#2463b6; color:white; padding:8px; border-radius:4px; } QPushButton { padding:5px; }')
        self.save_status = QLabel("")
        self.render_reason = QLabel("Isi judul hook atau matikan hook melalui Pengaturan hook.")
        self.render_reason.setWordWrap(True)
        self.time_label = QLabel("00:00 / 00:00")
        self.settings_summary = QPushButton("Pengaturan hook · Otomatis · 5 detik · Posisi 15%")
        self.transcript_button = QPushButton("Lihat transkrip")
        self.edit_button = QPushButton("Edit lagi")
        self.open_video_button = QPushButton("Buka video")
        self.more_button = QPushButton("Lainnya ▾")
        self.result_label = QLabel("Video selesai dirender.")
        self.result_label.setWordWrap(True)
        self.copy_prompt_button.setText("Salin prompt untuk ChatGPT")
        self.transcribe_button.setText("Buat transkrip")
        self.transcribe_button.setEnabled(False)
        self.preview_label.setMinimumSize(220, 280)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.preview_status.setWordWrap(True)
        self.file_label.setWordWrap(True)
        self.output_label.setWordWrap(True)
        self.status_label.setWordWrap(True)
        self.hook_text.setMinimumHeight(100)
        self.hook_text.setMaximumHeight(160)

        self.pages = QStackedWidget()
        video_page = QWidget()
        video_layout = QVBoxLayout(video_page)
        video_layout.addWidget(QLabel("Mulai dari satu video"))
        video_layout.addWidget(self.file_label)
        video_layout.addWidget(self.choose_button)
        video_layout.addWidget(self.transcribe_button)
        video_layout.addStretch()
        video_layout.addWidget(self.project_button)
        video_layout.addWidget(self.output_label)
        video_layout.addWidget(self.folder_button)
        self.pages.addWidget(video_page)

        hook_page = QWidget()
        hook_columns = QHBoxLayout(hook_page)
        editor_column = QVBoxLayout()
        guidance = QLabel("Salin prompt ke ChatGPT, lalu kembali untuk paste judul. Anda juga dapat menulis judul langsung.")
        guidance.setWordWrap(True)
        editor_column.addWidget(guidance)
        editor_column.addWidget(self.copy_prompt_button)
        editor_column.addWidget(QLabel("Arahan khusus (opsional)"))
        editor_column.addWidget(self.instruction)
        editor_column.addWidget(self.transcript_button)
        editor_column.addSpacing(12)
        editor_column.addWidget(self.paste_button)
        editor_column.addWidget(QLabel("Judul hook"))
        editor_column.addWidget(self.hook_text)
        editor_column.addWidget(self.save_status)
        editor_column.addWidget(self.settings_summary)
        editor_column.addStretch()
        editor_column.addWidget(self.render_reason)
        editor_column.addWidget(self.render_button)
        change_video = QPushButton("Video / proyek lain")
        editor_column.addWidget(change_video)
        preview_column = QVBoxLayout()
        self.style_button = QPushButton("Edit hook / subtitle")
        self.style_button.setEnabled(False)
        self.style_button.clicked.connect(self._edit_hook_style)
        preview_column.addWidget(self.style_button)
        preview_column.addWidget(self.preview_label, 1)
        preview_column.addWidget(self.time_label)
        preview_column.addWidget(self.preview_slider)
        preview_column.addWidget(self.hook_lines_label)
        preview_column.addWidget(self.preview_status)
        preview_column.addWidget(self.preview_progress)
        title_controls = QWidget()
        title_controls.setLayout(editor_column)
        self.hook_left = QStackedWidget()
        self.hook_left.addWidget(title_controls)
        self.style_placeholder = QWidget()
        self.hook_left.addWidget(self.style_placeholder)
        self.hook_tabs = QTabBar()
        self.hook_tabs.addTab("Judul")
        self.hook_tabs.addTab("Gaya")
        self.hook_tabs.setExpanding(True)
        self.hook_tabs.setTabEnabled(1, False)
        self.hook_tabs.currentChanged.connect(self._hook_tab_changed)
        left_column = QVBoxLayout()
        left_column.addWidget(self.hook_tabs)
        left_column.addWidget(self.hook_left, 1)
        hook_columns.addLayout(left_column, 1)
        hook_columns.addLayout(preview_column, 1)
        self.pages.addWidget(hook_page)

        result_page = QWidget()
        result_layout = QVBoxLayout(result_page)
        result_layout.addWidget(QLabel("Video siap"))
        result_layout.addWidget(self.result_label)
        result_layout.addWidget(self.open_video_button)
        result_layout.addWidget(self.open_button)
        result_layout.addWidget(self.edit_button)
        result_layout.addWidget(self.more_button)
        result_layout.addStretch()
        new_video = QPushButton("Mulai video / proyek lain")
        result_layout.addWidget(new_video)
        self.pages.addWidget(result_page)
        menu = QMenu(self)
        menu.addAction("Buka folder hasil", self._open_output)
        menu.addAction("Buka folder proyek / log", self._open_project_folder)
        menu.addAction("Catat evaluasi / keluhan", self._record_evaluation)
        self.more_button.setMenu(menu)

        self.settings_dialog = QDialog(self)
        self.settings_dialog.setWindowTitle("Pengaturan hook")
        settings = QFormLayout(self.settings_dialog)
        settings.addRow(self.hook_enabled)
        settings.addRow("Pemenggalan", self.wrap_mode)
        settings.addRow(QLabel("Mode manual memakai newline pada editor judul."))
        settings.addRow("Durasi pembuka", self.duration)
        settings.addRow(self.full_video)
        settings.addRow("Posisi tepi atas", self.top_position)
        done = QPushButton("Selesai")
        settings.addRow(done)
        done.clicked.connect(self.settings_dialog.accept)
        self.transcript_dialog = QDialog(self)
        self.transcript_dialog.setWindowTitle("Transkrip video")
        self.transcript_dialog.resize(600, 400)
        transcript_layout = QVBoxLayout(self.transcript_dialog)
        transcript_layout.addWidget(self.transcript)
        transcript_layout.addWidget(self.copy_transcript_button)
        transcript_done = QPushButton("Tutup")
        transcript_layout.addWidget(transcript_done)
        transcript_done.clicked.connect(self.transcript_dialog.accept)
        self.settings_summary.clicked.connect(self.settings_dialog.exec)
        self.transcript_button.clicked.connect(self.transcript_dialog.exec)
        self.edit_button.clicked.connect(lambda: self._show_stage(1))
        self.open_video_button.clicked.connect(self._open_video)
        change_video.clicked.connect(self._return_to_video)
        new_video.clicked.connect(self._return_to_video)

        layout = QVBoxLayout()
        layout.addWidget(self.stage_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.pages, 1)
        layout.addWidget(self.cancel_button)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.worker = self._new_process()
        self.worker.readyReadStandardOutput.connect(self._read_worker_output)
        self.worker.readyReadStandardError.connect(self._read_worker_error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.errorOccurred.connect(self._worker_error)
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(350)
        self.draft_timer.timeout.connect(self._save_draft)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(300)
        self.preview_timer.timeout.connect(self._start_preview)
        self.escape_style = QShortcut(QKeySequence("Escape"), self)
        self.escape_style.activated.connect(self._cancel_style_edit)
        self.undo_style = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        self.redo_style = QShortcut(QKeySequence(QKeySequence.StandardKey.Redo), self)
        self.undo_style.activated.connect(lambda: self._style_editor.undo() if self._style_editing else None)
        self.redo_style.activated.connect(lambda: self._style_editor.redo() if self._style_editing else None)

        self.choose_button.clicked.connect(self._choose_file)
        self.project_button.clicked.connect(self._open_project)
        self.project_folder_button.clicked.connect(self._open_project_folder)
        self.folder_button.clicked.connect(self._choose_output)
        self.transcribe_button.clicked.connect(self._start_transcription)
        self.cancel_button.clicked.connect(self._cancel_operation)
        self.copy_transcript_button.clicked.connect(self._copy_transcript)
        self.copy_prompt_button.clicked.connect(self._copy_prompt)
        self.paste_button.clicked.connect(self._paste_hook)
        self.render_button.clicked.connect(self._start_render)
        self.open_button.clicked.connect(self._open_output)
        self.evaluation_button.clicked.connect(self._record_evaluation)
        self.preview_slider.valueChanged.connect(self._schedule_preview)
        for widget in (self.hook_text, self.instruction):
            widget.textChanged.connect(self._draft_changed)
        for widget in (self.hook_enabled, self.full_video):
            widget.stateChanged.connect(self._draft_changed)
        for widget in (self.wrap_mode,):
            widget.currentIndexChanged.connect(self._draft_changed)
        for widget in (self.duration, self.top_position):
            widget.valueChanged.connect(self._draft_changed)
        self.hook_text.textChanged.connect(self._schedule_preview)
        self.hook_enabled.stateChanged.connect(self._schedule_preview)
        self.wrap_mode.currentIndexChanged.connect(self._schedule_preview)
        self.duration.valueChanged.connect(self._schedule_preview)
        self.full_video.stateChanged.connect(self._schedule_preview)
        self.top_position.valueChanged.connect(self._schedule_preview)
        self._set_project_controls(False)
        self._show_stage(0)

    def _new_process(self) -> QProcess:
        process = QProcess(self)
        process.setProgram(sys.executable)
        return process

    def _choose_file(self) -> None:
        if not self._leave_style_session():
            return
        if self.project_dir:
            self.draft_timer.stop()
            if not self._save_draft():
                QMessageBox.warning(self, "Draft belum tersimpan", "Perbaiki penyimpanan draft sebelum mengganti proyek.")
                return
        path, _ = QFileDialog.getOpenFileName(self, "Pilih video", str(Path.home()), "Video (*.mp4 *.MP4 *.mov *.MOV)")
        if path:
            self._discard_preview()
            self.source = Path(path)
            self.project_dir = None
            self.last_result_dir = None
            self.last_video = None
            self._video_duration = 0
            self.open_button.setEnabled(False)
            self.file_label.setText(str(self.source))
            self._show_stage(0)
            self.transcript.clear()
            self.preview_label.setText("Preview hook + subtitle")
            self.preview_label.setPixmap(QPixmap())
            self._preview_image = None
            self.preview_slider.setEnabled(False)
            self.evaluation_button.setEnabled(False)
            self._preview_valid = False
            self.transcribe_button.setEnabled(True)
            self._set_project_controls(False)
            self.status_label.setText("Sumber dipilih. Transkripsikan video untuk membuat proyek.")

    def _open_project(self) -> None:
        if not self._leave_style_session():
            return
        if self.project_dir:
            self.draft_timer.stop()
            if not self._save_draft():
                QMessageBox.warning(self, "Draft belum tersimpan", "Perbaiki penyimpanan draft sebelum berpindah proyek.")
                return
        folder = QFileDialog.getExistingDirectory(self, "Buka proyek Videogen", str(self.output_dir))
        if not folder:
            return
        path = Path(folder)
        try:
            project, _words, _info = load_project(path)
            self._video_width, self._video_height = _info.display_width, _info.display_height
            transcript = (path / project["transcript_file"]).read_text(encoding="utf-8")
            draft = normalize_draft(path, json.loads((path / "draft.json").read_text(encoding="utf-8")))
            if draft.get("hook_style") is not None:
                HookStyle.from_dict(draft["hook_style"])
        except Exception as error:
            QMessageBox.warning(self, "Proyek tidak dapat dibuka", str(error))
            return
        self._discard_preview()
        self.project_dir = path
        self.source = Path(project["source_path"])
        self.last_result_dir = None
        self.last_video = None
        self.output_dir = path.parent
        self.output_label.setText(f"Folder hasil: {self.output_dir}")
        self.file_label.setText(str(self.source))
        self.project_folder_button.setEnabled(True)
        self.transcript.setPlainText(transcript)
        self._load_draft(draft)
        self.preview_slider.setEnabled(True)
        self.evaluation_button.setEnabled(True)
        self.render_button.setEnabled(False)
        latest = sorted((p for p in (path / "revisions").glob("*/render.json") if not p.parent.name.startswith(".")), key=lambda item: item.stat().st_mtime)
        self.open_button.setEnabled(False)
        if latest:
            for metadata in reversed(latest):
                candidates = list(metadata.parent.glob('*_subtitled.mp4'))
                if candidates:
                    self.last_video = candidates[0]
                    self.last_result_dir = self.last_video.parent
                    self.result_label.setText(self.last_video.name)
                    self.open_button.setEnabled(True)
                    break
        else:
            self.open_button.setEnabled(False)
        self.status_label.setText(f"Proyek siap: {path.name}")
        self.preview_status.setText("Memuat preview draft…")
        self._set_project_controls(True)
        self._video_duration = float(project["duration"])
        self._show_stage(1)
        self._schedule_preview()

    def _load_draft(self, draft: dict) -> None:
        hook = draft.get("hook", draft)
        self._draft_loading = True
        self.hook_style = asdict(HookStyle.from_dict(draft.get("hook_style")))
        self.subtitle_style = asdict(SubtitleStyle.from_dict(draft.get("subtitle_style")))
        if self.hook_style is not None:
            HookStyle.from_dict(self.hook_style)
        self.instruction.setText(draft.get("instruction", ""))
        self.hook_text.setPlainText(hook.get("text", ""))
        self.hook_enabled.setChecked(bool(hook.get("enabled", True)))
        self.wrap_mode.setCurrentIndex(1 if hook.get("manual", False) else 0)
        self.top_position.setValue(float(hook.get("top_fraction", 0.15)) * 100)
        self.duration.setValue(max(0.1, float(hook.get("duration", 5.0))))
        self.full_video.setChecked(bool(hook.get("full_video", False)))
        self._draft_loading = False
        self._update_settings_summary()

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Pilih folder hasil", str(self.output_dir))
        if selected:
            self.output_dir = Path(selected)
            self.output_label.setText(f"Folder hasil: {self.output_dir}")

    def _start_transcription(self) -> None:
        if not self.source:
            return
        self.project_dir = None
        self._start_operation("transcribe", ["--operation", "transcribe", "--source", str(self.source),
                                               "--output", str(self.output_dir)])

    def _start_render(self) -> None:
        if not self.project_dir or self._style_editing:
            return
        if not self._preview_valid:
            self.preview_status.setText("Tunggu preview draft terbaru sebelum render.")
            return
        if self.hook_enabled.isChecked() and not self.hook_text.toPlainText().strip():
            QMessageBox.information(self, "Hook kosong", "Isi Hook title atau matikan Tampilkan hook.")
            return
        request = {"hook": self._hook_spec(), "hook_style": self._hook_style_snapshot(), "subtitle_style": self.subtitle_style, "validated_words_sha256": self._preview_words_hash}
        request_path = self._write_request(request)
        self._active_request = request_path
        self._start_operation("render", ["--operation", "render", "--project", str(self.project_dir), "--request", str(request_path)])

    def _start_operation(self, operation: str, args: list[str]) -> None:
        if self.worker.state() != QProcess.ProcessState.NotRunning:
            return
        self.draft_timer.stop()
        if not self._save_draft():
            if self._active_request:
                self._active_request.unlink(missing_ok=True)
                self._active_request = None
            return
        self._operation = operation
        self._line_buffer = ""
        self._terminal = None
        self._stopping = False
        self._cancel_requested = False
        self._set_busy(True)
        self._last_progress_value = 0
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFormat("Memulai proses…")
        self.progress_bar.show()
        self.status_label.setText("Memulai proses…")
        self.worker.setArguments(["-m", "videogen.worker_main", *args, "--log-file", str(self.log_path)])
        self.worker.start()

    def _read_worker_output(self) -> None:
        chunk = bytes(self.worker.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._line_buffer += chunk
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "stage":
                message = event.get("message", "Sedang memproses…")
                percent = event.get("percent")
                if isinstance(percent, (int, float)):
                    self.progress_bar.setRange(0, 100)
                    self._last_progress_value = min(99, max(0, int(percent)))
                    self.progress_bar.setValue(self._last_progress_value)
                    self.progress_bar.setFormat(message+" %p%")
                    self.status_label.setText(f"{message} {int(percent)}%")
                elif event.get("stage") != "completed":
                    self.progress_bar.setRange(0, 0)
                    self.progress_bar.setFormat(message)
                    self.status_label.setText(message)
            elif kind in {"completed", "failed", "cancelled"}:
                self._terminal = event

    def _read_worker_error(self) -> None:
        text = bytes(self.worker.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if text:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(f"QProcess stderr: {text}\n")
            except OSError:
                pass

    def _worker_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._read_worker_output()
        if self._active_request:
            self._active_request.unlink(missing_ok=True)
            self._active_request = None
        self._set_busy(False)
        terminal = self._terminal or {}
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(getattr(self, "_last_progress_value", 0))
        if terminal.get("type") == "completed" and exit_code == 0:
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("Selesai · %p%")
            operation = terminal.get("operation")
            if operation == "transcribe":
                self._open_project_path(Path(terminal["project"]))
                self.status_label.setText("Transkripsi tersimpan. Salin prompt atau tulis hook.")
            elif operation == "render":
                self.last_result_dir = Path(terminal["revision"])
                self.last_video = Path(terminal["video"])
                self.result_label.setText(self.last_video.name)
                self._show_stage(2)
                self.open_button.setEnabled(True)
                self.status_label.setText(f"Render selesai: {Path(terminal['video']).name}")
                self._schedule_preview()
        elif terminal.get("type") == "cancelled" or self._stopping or self._cancel_requested:
            self.progress_bar.setFormat("Dibatalkan")
            self.status_label.setText("Proses dibatalkan; proyek dan revisi sebelumnya dipertahankan.")
        else:
            self.progress_bar.setFormat("Gagal")
            message = terminal.get("message", f"{self._operation} berhenti sebelum selesai. Log: {self.log_path}")
            self.status_label.setText(f"Gagal: {message}")
            QMessageBox.warning(self, "Pemrosesan gagal", message)
        if self._stopping:
            self.close()

    def _worker_error(self, _error: QProcess.ProcessError) -> None:
        if self.worker.state() == QProcess.ProcessState.NotRunning:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Gagal memulai")
            self.status_label.setText(f"Worker tidak dapat dijalankan. Log: {self.log_path}")
            self._set_busy(False)

    def _open_project_path(self, path: Path) -> None:
        try:
            project, _words, _info = load_project(path)
            self._video_width, self._video_height = _info.display_width, _info.display_height
            draft = normalize_draft(path, json.loads((path / "draft.json").read_text(encoding="utf-8")))
            if draft.get("hook_style") is not None:
                HookStyle.from_dict(draft["hook_style"])
            transcript = (path / project["transcript_file"]).read_text(encoding="utf-8")
        except Exception as error:
            QMessageBox.warning(self, "Proyek transkripsi gagal dibuka", str(error))
            return
        self.project_dir = path
        self._video_duration = float(project["duration"])
        self.source = Path(project["source_path"])
        self.last_result_dir = None
        self.last_video = None
        self.transcript.setPlainText(transcript)
        self.project_folder_button.setEnabled(True)
        self._load_draft(draft)
        self._set_project_controls(True)
        self.preview_slider.setEnabled(True)
        self.evaluation_button.setEnabled(True)
        self._show_stage(1)
        self._schedule_preview()

    def _set_project_controls(self, active: bool) -> None:
        for widget in (self.copy_transcript_button, self.copy_prompt_button, self.hook_text, self.instruction,
                       self.hook_enabled, self.wrap_mode, self.duration, self.full_video, self.top_position,
                       self.paste_button, self.render_button, self.evaluation_button, self.style_button):
            widget.setEnabled(active)
        self.evaluation_button.setEnabled(active)
        self.render_button.setEnabled(active)
        self.hook_tabs.setTabEnabled(1, active)

    def _set_busy(self, busy: bool) -> None:
        self.choose_button.setEnabled(not busy)
        self.project_button.setEnabled(not busy)
        self.folder_button.setEnabled(not busy)
        self.transcribe_button.setEnabled(not busy and self.source is not None and self.project_dir is None)
        self.render_button.setEnabled(not busy and self.project_dir is not None and self._preview_valid)
        self.cancel_button.setEnabled(busy)
        self.cancel_button.setVisible(busy)
        self.style_button.setEnabled(not busy and self.project_dir is not None)
        self.hook_tabs.setTabEnabled(1, not busy and self.project_dir is not None)

    def _cancel_operation(self) -> None:
        if self.worker.state() == QProcess.ProcessState.NotRunning:
            return
        answer = QMessageBox.question(self, "Batalkan proses?", "Hentikan transkripsi atau render yang sedang berjalan?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._cancel_requested = True
            self.status_label.setText("Membatalkan proses…")
            self.progress_bar.setFormat("Membatalkan…")
            self._terminate_process_tree(self.worker)

    def _copy_transcript(self) -> None:
        text = self.transcript.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_label.setText("Transkrip disalin")

    def _copy_prompt(self) -> None:
        text = self.transcript.toPlainText()
        if text:
            instruction = self.instruction.text().strip() or "Tidak ada; pilih hook yang paling kuat berdasarkan transkrip."
            QApplication.clipboard().setText(PROMPT.format(instruction=instruction, transcript=text))
            self.status_label.setText("Prompt dan transkrip disalin")

    def _paste_hook(self) -> None:
        self.hook_text.setPlainText(QApplication.clipboard().text())

    def _hook_style_snapshot(self) -> dict | None:
        if self.hook_style is None:
            return None
        return dict(self.hook_style, top_fraction=self.top_position.value() / 100)

    def _apply_hook_style(self, style: dict, manual: bool, text: str | None = None, subtitle_style: dict | None = None) -> None:
        # Persist before committing widget state so failed writes preserve the session.
        hook = dict(self._hook_spec(), top_fraction=style["top_fraction"], manual=manual)
        if text is not None:
            hook["text"] = text
        save_draft(self.project_dir, {"hook": hook, "instruction": self.instruction.text(),
                                   "prompt_version": 1, "hook_style": style, "subtitle_style": subtitle_style or self.subtitle_style})
        self._draft_loading = True
        self.hook_style = style
        self.subtitle_style = subtitle_style or self.subtitle_style
        if text is not None:
            self.hook_text.setPlainText(text)
        self.top_position.setValue(style["top_fraction"] * 100)
        self.wrap_mode.setCurrentIndex(1 if manual else 0)
        self._draft_loading = False
        self.save_status.setText("Draft tersimpan")
        self._update_settings_summary()

    def _hook_tab_changed(self, index: int) -> None:
        if index == 1:
            self._edit_hook_style()
        elif self._style_editing:
            if not self._leave_style_session():
                self.hook_tabs.blockSignals(True)
                self.hook_tabs.setCurrentIndex(1)
                self.hook_tabs.blockSignals(False)
        else:
            self.hook_left.setCurrentIndex(0)

    def _edit_hook_style(self) -> None:
        if self._style_editing:
            return
        if not self.project_dir or self.worker.state() != QProcess.ProcessState.NotRunning:
            self._reset_hook_tab()
            return
        self.draft_timer.stop()
        if not self._save_draft():
            self._reset_hook_tab()
            return
        self._discard_preview()
        self._style_editing = True
        try:
            editor = HookStyleEditor(self)
        except Exception as error:
            self._style_editing = False
            self._reset_hook_tab()
            self._schedule_preview()
            QMessageBox.warning(self, "Editor gaya gagal dibuka", str(error))
            return
        self._style_editor = editor
        self.hook_left.addWidget(editor)
        self.hook_left.setCurrentWidget(editor)
        self.hook_tabs.blockSignals(True)
        self.hook_tabs.setCurrentIndex(1)
        self.hook_tabs.blockSignals(False)
        for widget in (self.hook_text, self.instruction, self.paste_button, self.settings_summary):
            widget.setEnabled(False)
        self.status_label.setText("Editor visual · pilih Hook atau Subtitle. Frame subtitle berlaku seluruh video.")
        self._refresh_render_button()

    def _reset_hook_tab(self) -> None:
        self.hook_tabs.blockSignals(True)
        self.hook_tabs.setCurrentIndex(0)
        self.hook_tabs.blockSignals(False)
        self.hook_left.setCurrentIndex(0)

    def _end_style_session(self, action: str) -> None:
        if not self._style_editing:
            return
        editor = self._style_editor
        editor.stop_session()
        self._discard_preview()
        self._style_editing = False
        self._style_editor = None
        self._reset_hook_tab()
        self.hook_left.removeWidget(editor)
        editor.deleteLater()
        for widget in (self.hook_text, self.instruction, self.paste_button, self.settings_summary):
            widget.setEnabled(True)
        self._update_settings_summary()
        try:
            _append_event(self.project_dir, operation="style_session", status="completed", editor_mode="visual",
                          session_id=editor.session_id, exit_action=action)
        except OSError as error:
            self.save_status.setText(f"Draft proyek tersimpan sebelumnya; log sesi gagal ditulis: {error}")
        self._schedule_preview()
        self.status_label.setText("Hook dan subtitle diterapkan." if action == "terapkan" else "Sesi editor ditutup; periksa preview proyek.")

    def _leave_style_session(self) -> bool:
        if not self._style_editing:
            return True
        editor = self._style_editor
        self.preview_label.finish_text(False)
        if not editor.is_dirty():
            self._end_style_session("navigasi_tanpa_perubahan")
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Perubahan editor belum diterapkan")
        box.setText("Terapkan hook dan frame subtitle sebelum berpindah? Preset/default yang disimpan tetap berlaku.")
        apply = box.addButton("Terapkan", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Buang perubahan", QMessageBox.ButtonRole.DestructiveRole)
        stay = box.addButton("Tetap mengedit", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(stay)
        box.exec()
        if box.clickedButton() is apply:
            return editor.apply_style()
        if box.clickedButton() is discard:
            self._end_style_session("buang_navigasi")
            return True
        return False

    def _cancel_style_edit(self) -> None:
        if self._style_editing and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None:
            if self.preview_label.cancel_gesture("escape"):
                return
            if not self.preview_label.finish_text(True):
                self._end_style_session("batal")

    def _hook_spec(self) -> dict:
        return {"text": self.hook_text.toPlainText(), "enabled": self.hook_enabled.isChecked(),
                "manual": self.wrap_mode.currentIndex() == 1, "top_fraction": self.top_position.value() / 100,
                "duration": self.duration.value(), "full_video": self.full_video.isChecked()}

    def _draft_changed(self, *_args) -> None:
        self._update_settings_summary()
        if not self._draft_loading and self.project_dir and not self._style_editing:
            self.draft_timer.start()

    def _save_draft(self) -> bool:
        if not self.project_dir or self._draft_loading or self._style_editing:
            return True
        try:
            save_draft(self.project_dir, {"hook": self._hook_spec(), "instruction": self.instruction.text(),
                                          "prompt_version": 1, "hook_style": self._hook_style_snapshot(), "subtitle_style": self.subtitle_style})
            self.save_status.setText("Draft tersimpan")
            return True
        except OSError as error:
            self.save_status.setText(f"Draft belum tersimpan: {error}")
            return False

    def _write_request(self, data: dict) -> Path:
        path = Path(tempfile.gettempdir()) / f"videogen-request-{uuid4().hex}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def _set_preview_progress(self, running: bool) -> None:
        self.preview_progress.setRange(0, 0 if running else 100)
        self.preview_progress.setVisible(running)

    def _schedule_preview(self, *_args) -> None:
        if self.project_dir and not self._style_editing:
            self._preview_request += 1
            self._update_time_label()
            self._preview_valid = False
            self._set_preview_progress(True)
            self.preview_status.setText("Preview memperbarui…")
            self._refresh_render_button()
            self.preview_timer.start(300)

    def _start_preview(self) -> None:
        if not self.project_dir:
            return
        if self._style_editing and self.preview_label._drag is not None:
            return
        if self._preview_process and self._preview_process.state() != QProcess.ProcessState.NotRunning:
            if not getattr(self._preview_process, "terminating", False):
                self._preview_process.terminating = True
                self._terminate_process_tree(self._preview_process)
            self.preview_timer.start(100)
            return
        request_id = self._preview_request
        if self._preview_request_path:
            self._preview_request_path.unlink(missing_ok=True)
        try:
            duration = self._video_duration
            timestamp = duration * self.preview_slider.value() / 1000
            preview_path = Path(tempfile.gettempdir()) / f"videogen-preview-{uuid4().hex}.png"
            request = {"request_id": request_id, "output": str(preview_path), "timestamp": timestamp,
                       "hook": self._hook_spec(), "hook_style": self._hook_style_snapshot(), "subtitle_style": self.subtitle_style}
            if self._style_editing:
                request.update(self._style_editor.preview_request())
            request_path = self._write_request(request)
        except Exception as error:
            self._set_preview_progress(False)
            self.preview_status.setText(f"Preview gagal: {error}")
            if self._style_editing:
                self._style_editor.valid = False
                self._style_editor.apply.setEnabled(False)
            return
        process = self._new_process()
        self._preview_process = process
        self._preview_temp = preview_path
        self._preview_request_path = request_path
        process.preview_terminal_message = ""
        process.preview_cue_timestamp = None
        process.preview_line_buffer = ""
        process.preview_finished = False
        process.readyReadStandardOutput.connect(lambda p=process: self._read_preview_output(p))
        process.readyReadStandardError.connect(lambda p=process: self._read_preview_error(p))
        process.setArguments(["-m", "videogen.worker_main", "--operation", "preview", "--project",
                              str(self.project_dir), "--request", str(request_path), "--log-file", str(self.log_path)])
        process.finished.connect(lambda code, _status, rid=request_id, p=preview_path, q=process, req=request_path:
                                  self._preview_finished(rid, p, q, req, code))
        process.errorOccurred.connect(lambda error, rid=request_id, p=preview_path, q=process, req=request_path:
            self._preview_finished(rid, p, q, req, 1) if error == QProcess.ProcessError.FailedToStart else None)
        process.start()

    def _preview_finished(self, request_id: int, path: Path, process: QProcess, request_path: Path, exit_code: int) -> None:
        if process.preview_finished:
            return
        process.preview_finished = True
        if self._preview_process is process:
            self._preview_process = None
        self._read_preview_output(process)
        process.deleteLater()
        request_path.unlink(missing_ok=True)
        if request_id != self._preview_request:
            path.unlink(missing_ok=True)
            path.with_suffix(".layout.json").unlink(missing_ok=True)
            return
        self._set_preview_progress(False)
        try:
            layout = json.loads(path.with_suffix(".layout.json").read_text())
        except (OSError, ValueError):
            layout = {}
        path.with_suffix(".layout.json").unlink(missing_ok=True)
        if exit_code == 0 and path.is_file():
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self.preview_status.setText("Frame preview tidak dapat dibaca; coba ubah waktu preview.")
                path.unlink(missing_ok=True)
                return
            self._preview_words_hash = layout.get("words_sha256")
            self._preview_image = pixmap
            self._scale_preview()
            self._read_preview_output(process)
            self.preview_status.setText("Preview siap")
            lines = getattr(process, "preview_hook_lines", None)
            end = getattr(process, "preview_hook_end", None)
            line_text = f"{lines} baris" if lines is not None else "layout siap"
            self.hook_lines_label.setText(f"Hook: {line_text}; tampil sampai {end:.2f} dtk" if end is not None
                                          else f"Hook: {line_text}; tidak aktif")
            if self._style_editing:
                self._style_editor.preview_ready(layout)
                self.hook_lines_label.setText("Subtitle · Seluruh video" if self._style_editor.target == "subtitle" else "Contoh gaya — bukan judul video" if self._style_editor.example else f"Edit gaya sementara · {line_text}")
                self._preview_valid = False
            else:
                self._preview_valid = bool(layout.get("all_cues_valid"))
                errors = layout.get("validation_errors") or []
                if errors:
                    self.preview_status.setText(errors[0]["reason"]+" · Buka editor untuk memperbaiki frame subtitle.")
            self._refresh_render_button()
            self._update_settings_summary()
            path.unlink(missing_ok=True)
        else:
            message = process.preview_terminal_message or f"Preview gagal. Periksa log: {self.log_path}"
            self.preview_status.setText(message)
            if self._style_editing:
                self._style_editor.valid = False
                self._style_editor.apply.setEnabled(False)
                self._style_editor.preview_failed(process.preview_cue_timestamp)
            self._preview_valid = False
            self._refresh_render_button()
            path.unlink(missing_ok=True)

    @staticmethod
    def _read_preview_output(process: QProcess) -> None:
        chunk = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        process.preview_line_buffer += chunk
        while "\n" in process.preview_line_buffer:
            line, process.preview_line_buffer = process.preview_line_buffer.split("\n", 1)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "failed":
                process.preview_terminal_message = event.get("message", "Preview gagal.")
                process.preview_cue_timestamp = event.get("cue_timestamp")
            elif event.get("type") == "completed":
                process.preview_hook_lines = int(event.get("hook_lines", 0))
                process.preview_hook_end = event.get("hook_end")

    def _read_preview_error(self, process: QProcess) -> None:
        chunk = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if chunk:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as log:
                    log.write(f"Preview stderr: {chunk}\n")
            except OSError:
                pass

    def _refresh_render_button(self) -> None:
        busy = self.worker.state() != QProcess.ProcessState.NotRunning
        self.render_button.setEnabled(bool(self.project_dir) and self._preview_valid and not busy and not self._style_editing)
        if self._style_editing:
            reason = "Terapkan atau batalkan sesi editor sebelum render."
        elif busy:
            reason = "Proses sedang berjalan."
        elif self.hook_enabled.isChecked() and not self.hook_text.toPlainText().strip():
            reason = "Isi judul hook atau klik dua kali contoh pada tab Gaya; hook juga dapat dimatikan."
        elif not self._preview_valid:
            reason = self.preview_status.text() or "Tunggu preview terbaru."
        else:
            reason = "Preview siap. Render video untuk menyimpan hasil."
        self.render_reason.setText(reason)
        self.copy_prompt_button.setDefault(not self._preview_valid)
        self.render_button.setDefault(self._preview_valid and not busy)
        self._set_primary(self.copy_prompt_button, not self._preview_valid)
        self._set_primary(self.render_button, self._preview_valid and not busy)

    def _record_evaluation(self) -> None:
        if not self.project_dir:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Catat evaluasi")
        form = QFormLayout(dialog)
        check = QComboBox()
        check.addItems(["visual_reference", "preview_render_match", "face_coverage", "reels_position",
                        "whisper_word_onset", "hook_style_readability", "editor_usability", "preset_portability", "subtitle_global_frame", "progress_feedback", "open_result_folder", "user_observation"])
        status = QComboBox()
        status.addItems(["pending", "passed", "failed", "inconclusive"])
        method = QLineEdit("manual")
        result = QPlainTextEdit()
        evidence = QLineEdit()
        form.addRow("Pemeriksaan", check)
        form.addRow("Status", status)
        form.addRow("Metode", method)
        form.addRow("Hasil / keluhan", result)
        form.addRow("Path bukti", evidence)
        save = QPushButton("Simpan evaluasi")
        form.addRow(save)
        def persist() -> None:
            try:
                revision = self.last_result_dir.name if self.last_result_dir else ""
                record_evaluation(self.project_dir, revision, {"check_id": check.currentText(),
                    "status": status.currentText(), "method": method.text(), "result": result.toPlainText(),
                    "evidence": evidence.text()})
                self.status_label.setText("Evaluasi tersimpan")
                dialog.close()
            except Exception as error:
                QMessageBox.warning(dialog, "Evaluasi gagal disimpan", str(error))
        save.clicked.connect(persist)
        dialog.exec()

    def _show_stage(self, index: int) -> None:
        if index != 1 and not self._leave_style_session():
            return
        self.pages.setCurrentIndex(index)
        names = ["Video", "Hook", "Hasil"]
        self.stage_label.setText("   →   ".join(
            f'<span style="color:#2463b6"><b>{i+1}. {name}</b></span>' if i == index else f"{i+1}. {name}"
            for i, name in enumerate(names)))
        self.cancel_button.setVisible(self.worker.state() != QProcess.ProcessState.NotRunning)
        needs_transcript = self.source is not None and self.project_dir is None
        self.transcribe_button.setVisible(needs_transcript)
        self._set_primary(self.choose_button, not needs_transcript)
        self._set_primary(self.transcribe_button, needs_transcript)
        self._set_primary(self.open_video_button, True)
        if index == 1:
            self.status_label.setText("Tulis atau paste judul, periksa preview, lalu render video.")
            self._refresh_render_button()
        self._update_settings_summary()

    def _return_to_video(self) -> None:
        if not self._leave_style_session():
            return
        if self.worker.state() != QProcess.ProcessState.NotRunning:
            return
        self.draft_timer.stop()
        if not self._save_draft():
            return
        self._show_stage(0)
        self.status_label.setText("Pilih video baru atau buka proyek tersimpan.")

    @staticmethod
    def _set_primary(button: QPushButton, primary: bool) -> None:
        button.setProperty("primary", primary)
        button.style().unpolish(button)
        button.style().polish(button)

    def _discard_preview(self) -> None:
        self._set_preview_progress(False)
        self.preview_timer.stop()
        self._preview_request += 1
        if self._preview_process and self._preview_process.state() != QProcess.ProcessState.NotRunning:
            self._terminate_process_tree(self._preview_process)
        self._preview_valid = False
        self._preview_image = None
        self.preview_label.clear()
        self.preview_label.setText("Preview hook + subtitle")

    def _update_settings_summary(self) -> None:
        mode = self.wrap_mode.currentText()
        interval = "Sepanjang video" if self.full_video.isChecked() else f"{min(self.duration.value(), self._video_duration or self.duration.value()):g} detik"
        text = f"Pengaturan hook · {mode} · {interval} · Posisi {self.top_position.value():g}%"
        self.settings_summary.setText(text if self.hook_enabled.isChecked() else "Pengaturan hook · Hook tidak aktif")
        self.duration.setEnabled(not self.full_video.isChecked())

    def _update_time_label(self) -> None:
        def format_time(seconds: float) -> str:
            total = int(seconds)
            return f"{total // 60:02}:{total % 60:02}"
        current = self._video_duration * self.preview_slider.value() / 1000
        self.time_label.setText(f"{format_time(current)} / {format_time(self._video_duration)}")

    def _open_video(self) -> None:
        if self.last_video and self.last_video.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_video)))

    def _open_output(self) -> None:
        folder = self.last_video.parent if self.last_video else self.last_result_dir
        reason = None
        if not folder or not folder.is_dir():
            reason = 'Folder hasil tidak tersedia atau sudah dipindahkan.'
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            reason = 'Aplikasi pembuka folder gagal dijalankan.'
        if reason:
            QMessageBox.warning(self, 'Folder hasil', reason)
        if self.project_dir:
            try:
                _append_event(self.project_dir, operation='open_result_folder', status='failed' if reason else 'completed',
                              revision_id=folder.name if folder else None, reason=reason)
            except OSError as error:
                self.status_label.setText(f'Log folder gagal ditulis: {error}')

    def _open_project_folder(self) -> None:
        if self.project_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project_dir)))

    def _scale_preview(self) -> None:
        if self._preview_image and not self._preview_image.isNull():
            self.preview_label.source_size = (self._video_width, self._video_height)
            self.preview_label.setPixmap(self._preview_image.scaled(
                self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale_preview()

    def closeEvent(self, event) -> None:
        if not self._stopping and not self._leave_style_session():
            event.ignore()
            return
        self.draft_timer.stop()
        if self._stopping:
            active_now = self.worker.state() != QProcess.ProcessState.NotRunning
            preview_now = self._preview_process and self._preview_process.state() != QProcess.ProcessState.NotRunning
            if active_now or preview_now:
                event.ignore()
                QTimer.singleShot(250, self.close)
                return
            event.accept()
            return
        if not self._save_draft():
            answer_save = QMessageBox.question(self, "Draft belum tersimpan",
                "Simpan draft lagi sebelum menutup? Pilih Tidak untuk menutup tanpa menyimpan.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer_save == QMessageBox.StandardButton.Yes and not self._save_draft():
                event.ignore()
                return
        active = self.worker.state() != QProcess.ProcessState.NotRunning
        preview_active = self._preview_process and self._preview_process.state() != QProcess.ProcessState.NotRunning
        if not active and not preview_active:
            event.accept()
            return
        answer = QMessageBox.question(self, "Batalkan pemrosesan?", "Proses sedang berjalan. Tutup dan batalkan pekerjaan?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        event.ignore()
        self._stopping = True
        self.status_label.setText("Menghentikan proses…")
        for process in (self.worker, self._preview_process):
            if process and process.state() != QProcess.ProcessState.NotRunning:
                self._terminate_process_tree(process)
        QTimer.singleShot(2300, self.close)

    @staticmethod
    def _terminate_process_tree(process: QProcess) -> None:
        pid = int(process.processId())
        if pid > 0 and sys.platform.startswith("linux"):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            QTimer.singleShot(2000, lambda group=pid: _kill_group(group))
        else:
            process.terminate()
            QTimer.singleShot(2000, process.kill)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
