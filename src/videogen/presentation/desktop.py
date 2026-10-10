from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
import os
import signal
import sys
import tempfile
import traceback
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QProcess, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QPlainTextEdit, QProgressBar, QMenu, QScrollArea, QScrollBar, QStackedWidget, QTabBar, QSlider, QSizePolicy, QVBoxLayout, QWidget,
)

from videogen.application.projects import load_project, record_evaluation, save_draft, normalize_draft, _append_event
from videogen.domain.hook import HookStyle
from videogen.domain.subtitle_style import SubtitleStyle
from videogen.domain.models import build_cues, max_line_characters
from videogen.presentation.hook_style_editor import HookStyleEditor
from videogen.presentation.hook_preview import HookPreview
from videogen.infrastructure.logging_config import default_log_path
from videogen.infrastructure.mvp3_diagnostics import MVP3RunLog
from videogen.infrastructure.libopenshot_player import LibOpenShotPlayback
from videogen.domain.timeline import TimelineEdit, project_cues, nearest_boundary, edited_transcript
from videogen.presentation.timeline import EditorTimeline
from videogen.application.editor_context import editor_context
from videogen.infrastructure.ass_overlay import ASSOverlay
from videogen.infrastructure.frame_index import frame_boundaries


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
        self.mvp3_log = MVP3RunLog()
        self.mvp3_log.record("application_ready", status="completed")
        self._previous_excepthook = sys.excepthook
        sys.excepthook = self._record_uncaught_exception
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
        self._openshot_playback = None
        self._openshot_ready = False
        self._openshot_syncing = False
        self._openshot_metadata = None
        self._timeline_cues = []
        self._timeline_syncing = False
        self._edit = None
        self._source_info = None
        self._source_words = []
        self._source_transcript = ""
        self._edit_history = []
        self._edit_history_index = 0
        self._edit_revision = 0
        self._hook_needs_review = False
        self._ass_overlay = None
        self._overlay_temp = None
        self._frame_boundaries = None
        self._diagnostic_process = None
        self._frame_index_process = None

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
        # Millisecond source-time scale avoids the coarse 50 ms jumps of 0..1000.
        self.preview_slider.setRange(0, 0)
        self.preview_slider.setEnabled(False)
        self.timeline_label = QLabel("Timeline · belum ada cue")
        self.cue_list = QListWidget()
        self.cue_list.setMaximumHeight(130)
        self.cue_list.setToolTip("Pilih cue untuk berpindah ke waktu mulai subtitle.")
        self.evaluation_button = QPushButton("Catat evaluasi / keluhan")
        self.evaluation_button.setEnabled(False)

        self.stage_label = QLabel("1. Video   →   2. Hook   →   3. Hasil")
        self.stage_label.setStyleSheet("font-size:18px;padding:8px")
        self.setStyleSheet('QPushButton[primary="true"] { background:#2463b6; color:white; padding:8px; border-radius:4px; } QPushButton { padding:5px; }')
        self.save_status = QLabel("")
        self.render_reason = QLabel("Isi judul hook atau matikan hook melalui Pengaturan hook.")
        self.render_reason.setWordWrap(True)
        self.time_label = QLabel("00:00 / 00:00")
        self.openshot_button = QPushButton("Putar dengan libopenshot")
        self.openshot_button.setEnabled(False)
        self.ffmpeg_preview_button = QPushButton("Kembali ke preview hasil")
        self.ffmpeg_preview_button.setEnabled(False)
        self.openshot_note = QLabel("Preview native untuk evaluasi engine. Overlay hook/subtitle belum disamakan dengan hasil FFmpeg.")
        self.openshot_note.setText("Playback memakai ASS/libass. Periksa kesamaan dengan frame FFmpeg melalui diagnostik.")
        self.openshot_note.setWordWrap(True)
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
        self.preview_label.setMinimumSize(220, 120)
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
        hook_root = QVBoxLayout(hook_page)
        hook_columns = QHBoxLayout()
        hook_root.addLayout(hook_columns, 1)
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
        canvas_toolbar = QHBoxLayout()
        for button in (self.style_button, self.openshot_button, self.ffmpeg_preview_button, self.render_button):
            canvas_toolbar.addWidget(button)
        preview_column.addLayout(canvas_toolbar)
        preview_column.addWidget(self.preview_label, 1)
        self.openshot_note.hide()
        self.openshot_button.setToolTip(self.openshot_note.text())
        self.cue_list.hide()
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
        inspector_content = QWidget()
        inspector_content.setLayout(left_column)
        self.inspector = QScrollArea()
        self.inspector.setWidgetResizable(True)
        self.inspector.setWidget(inspector_content)
        self.inspector.setMinimumWidth(230)
        self.inspector.setMaximumWidth(360)
        hook_columns.addWidget(self.inspector, 1)
        hook_columns.addLayout(preview_column, 2)
        self.timeline = EditorTimeline()
        self.timeline.interactionStarted.connect(self._pause_for_edit)
        self.timeline.seekRequested.connect(lambda seconds: self.preview_slider.setValue(round(seconds*1000)))
        self.timeline.boundaryCommitted.connect(self._trim_boundary)
        self.timeline.objectSelected.connect(self._select_canvas_object)
        self.timeline_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.timeline_scroll.valueChanged.connect(lambda value: self._scroll_timeline(value/1000))
        tools_row = QHBoxLayout()
        self.inspector_toggle = QPushButton("Pengaturan")
        self.inspector_toggle.clicked.connect(lambda: self.inspector.setVisible(not self.inspector.isVisible()))
        self.split_button = QPushButton("Split")
        self.delete_segment_button = QPushButton("Hapus segmen")
        self.cut_before_button = QPushButton("Buang sebelum")
        self.cut_after_button = QPushButton("Buang sesudah")
        self.edit_undo_button, self.edit_redo_button = QPushButton("↶ Undo"), QPushButton("↷ Redo")
        self.snap_words = QCheckBox("Snap kata")
        self.snap_words.setChecked(True)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(1, 20)
        self.zoom_slider.setMaximumWidth(120)
        self.zoom_slider.valueChanged.connect(self._zoom_timeline)
        self.diagnostic_button = QPushButton("Periksa editor / log")
        self.diagnostic_button.clicked.connect(self._start_diagnostics)
        for widget in (self.inspector_toggle, self.split_button, self.delete_segment_button, self.cut_before_button,
                self.cut_after_button, self.edit_undo_button, self.edit_redo_button, self.snap_words):
            tools_row.addWidget(widget)
        self.split_button.clicked.connect(self._split_at_playhead)
        self.delete_segment_button.clicked.connect(self._delete_segment)
        self.cut_before_button.clicked.connect(lambda: self._trim_at_playhead(True))
        self.cut_after_button.clicked.connect(lambda: self._trim_at_playhead(False))
        self.edit_undo_button.clicked.connect(lambda: self._undo_cut(-1))
        self.edit_redo_button.clicked.connect(lambda: self._undo_cut(1))
        hook_root.addLayout(tools_row)
        navigation = QHBoxLayout()
        navigation.addWidget(self.time_label)
        navigation.addWidget(self.preview_slider, 1)
        navigation.addWidget(QLabel("Zoom"))
        navigation.addWidget(self.zoom_slider)
        navigation.addWidget(self.diagnostic_button)
        hook_root.addLayout(navigation)
        hook_root.addWidget(self.timeline)
        hook_root.addWidget(self.timeline_scroll)
        hook_root.addWidget(self.timeline_label)
        self.timeline_label.setWordWrap(True)
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
        self.transcript_mode = QComboBox()
        self.transcript_mode.addItems(["Transkrip hasil edit", "Transkrip sumber"])
        self.transcript_mode.currentIndexChanged.connect(self._update_transcript)
        transcript_layout.addWidget(self.transcript_mode)
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
        self.openshot_timer = QTimer(self)
        self.openshot_timer.setInterval(100)
        self.openshot_timer.timeout.connect(self._sync_openshot_position)
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
        self.preview_slider.valueChanged.connect(self._seek_openshot)
        self.preview_slider.valueChanged.connect(lambda value: self._sync_timeline_selection(value / 1000))
        self.preview_slider.sliderReleased.connect(self._record_openshot_seek)
        self.cue_list.currentRowChanged.connect(self._select_timeline_cue)
        self.openshot_button.clicked.connect(self._toggle_openshot_playback)
        self.ffmpeg_preview_button.clicked.connect(self._return_to_ffmpeg_preview)
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
        self._mvp3_log_warning = None
        self._diagnostic_health_timer = QTimer(self)
        self._diagnostic_health_timer.setInterval(750)
        self._diagnostic_health_timer.timeout.connect(self._check_mvp3_log_health)
        self._diagnostic_health_timer.start()

    def _check_mvp3_log_health(self) -> None:
        error = self.mvp3_log.write_error
        if error and error != self._mvp3_log_warning:
            self._mvp3_log_warning = error
            self.project_folder_button.setToolTip(f"Log run MVP 3A: {self.mvp3_log.root}")
            self.status_label.setText(f"Log utama gagal ditulis: {error}. Arsip cadangan: {self.mvp3_log.root}")
        elif not error:
            self._mvp3_log_warning = None

    def _record_uncaught_exception(self, error_type, error, tb) -> None:
        self.mvp3_log.record("uncaught_python_exception", status="failed", error_type=getattr(error_type, "__name__", str(error_type)),
                             error_message=str(error)[:1000], traceback="".join(traceback.format_exception(error_type, error, tb))[-12000:])
        self._previous_excepthook(error_type, error, tb)

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
            self._close_openshot_playback("source_changed")
            self.openshot_button.setEnabled(False)
            self.project_dir = None
            self.last_result_dir = None
            self.last_video = None
            self._video_duration = 0
            self._source_info, self._source_words, self._edit = None, [], None
            self.timeline.edit, self.timeline.cues = None, []
            self.cue_list.clear()
            self.timeline.update()
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
            project, words, info = load_project(path)
            self._video_width, self._video_height = info.display_width, info.display_height
            transcript = (path / project["transcript_file"]).read_text(encoding="utf-8")
            draft = normalize_draft(path, json.loads((path / "draft.json").read_text(encoding="utf-8")))
            if draft.get("hook_style") is not None:
                HookStyle.from_dict(draft["hook_style"])
        except Exception as error:
            QMessageBox.warning(self, "Proyek tidak dapat dibuka", str(error))
            return
        self._discard_preview()
        self._close_openshot_playback("project_changed")
        self.project_dir = path
        self.source = Path(project["source_path"])
        self._source_info, self._source_words, self._source_transcript = info, words, transcript
        self._frame_boundaries = None
        try:
            self.mvp3_log.attach_project(path, project)
        except OSError as error:
            self.mvp3_log.record("project_attach_failed", status="failed", error_message=str(error))
            self.status_label.setText(f"Arsip proyek gagal; log cadangan: {self.mvp3_log.root}")
        self._video_duration = float(project["duration"])
        self.openshot_button.setEnabled(True)
        self.last_result_dir = None
        self.last_video = None
        self.output_dir = path.parent
        self.output_label.setText(f"Folder hasil: {self.output_dir}")
        self.file_label.setText(str(self.source))
        self.project_folder_button.setEnabled(True)
        self.transcript.setPlainText(transcript)
        self._load_draft(draft)
        self._populate_timeline(words, info)
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
        duration = self._source_info.duration if self._source_info else self._video_duration
        if duration > 0:
            self._edit = TimelineEdit.from_dict(draft.get("timeline"), duration)
            self._video_duration = self._edit.duration
            self.preview_slider.setRange(0, max(1, round(self._video_duration*1000)))
            self._edit_history = [self._edit.to_dict()]
            self._edit_history_index = 0
            self._edit_revision = int(draft.get("edit_revision", 0))
            self._hook_needs_review = bool(draft.get("hook_needs_review", False))
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
        self.mvp3_log.record("operation_started", status="running", operation="transcribe",
                             source_path=str(self.source))
        self.project_dir = None
        self._start_operation("transcribe", ["--operation", "transcribe", "--source", str(self.source),
                                               "--output", str(self.output_dir)])

    def _start_render(self) -> None:
        if not self.project_dir or self._style_editing or self._diagnostic_process or self._frame_index_process or self.worker.state() != QProcess.ProcessState.NotRunning:
            return
        if not self._preview_valid:
            self.preview_status.setText("Tunggu preview draft terbaru sebelum render.")
            return
        if self.hook_enabled.isChecked() and not self.hook_text.toPlainText().strip():
            QMessageBox.information(self, "Hook kosong", "Isi Hook title atau matikan Tampilkan hook.")
            return
        request = dict(self._editor_snapshot(), validated_words_sha256=self._preview_words_hash)
        snapshot_hash = hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()
        self.mvp3_log.record("export_started", status="running", operation="render", snapshot_sha256=snapshot_hash,
                             validated_words_sha256=self._preview_words_hash)
        self._close_openshot_playback("export_started")
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
        self.mvp3_log.record("operation_started", status="running", operation=operation,
                             project_id=self.project_dir.name if self.project_dir else None)
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
                if event.get("stage"):
                    self.mvp3_log.record("worker_progress", status="running", operation=self._operation,
                                         stage=event.get("stage"), percent=event.get("percent"))
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
            self.mvp3_log.record("worker_stderr", status="warning", operation=self._operation,
                                 stderr=text[-4000:])
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
            self.mvp3_log.record("operation_finished", status="completed", operation=operation,
                                 exit_code=exit_code, result_path=terminal.get("video") or terminal.get("project"),
                                 revision_id=Path(terminal["revision"]).name if terminal.get("revision") else None)
            if operation == "transcribe":
                try:
                    metadata = json.loads((Path(terminal["project"]) / "project.json").read_text(encoding="utf-8"))
                    self.mvp3_log.attach_project(Path(terminal["project"]), metadata)
                except (OSError, ValueError) as error:
                    self.mvp3_log.record("project_attach_failed", status="failed", error_type=type(error).__name__,
                                         error_message=str(error)[:500])
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
            self.mvp3_log.record("operation_finished", status="cancelled", operation=self._operation,
                                 exit_code=exit_code)
            self.progress_bar.setFormat("Dibatalkan")
            self.status_label.setText("Proses dibatalkan; proyek dan revisi sebelumnya dipertahankan.")
        else:
            self.mvp3_log.record("operation_finished", status="failed", operation=self._operation,
                                 exit_code=exit_code, error_type=terminal.get("error_type"),
                                 error_message=str(terminal.get("message", "worker terminated without a terminal event"))[:1000],
                                 traceback=str(terminal.get("traceback", ""))[-12000:])
            self.progress_bar.setFormat("Gagal")
            message = terminal.get("message", f"{self._operation} berhenti sebelum selesai. Log: {self.log_path}")
            self.status_label.setText(f"Gagal: {message}")
            QMessageBox.warning(self, "Pemrosesan gagal", message)
        if self._stopping:
            self.close()

    def _worker_error(self, _error: QProcess.ProcessError) -> None:
        self.mvp3_log.record("worker_process_error", status="failed", operation=self._operation,
                             process_error=int(_error.value))
        if self.worker.state() == QProcess.ProcessState.NotRunning:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("Gagal memulai")
            self.status_label.setText(f"Worker tidak dapat dijalankan. Log: {self.log_path}")
            self._set_busy(False)

    def _open_project_path(self, path: Path) -> None:
        try:
            project, words, info = load_project(path)
            self._video_width, self._video_height = info.display_width, info.display_height
            draft = normalize_draft(path, json.loads((path / "draft.json").read_text(encoding="utf-8")))
            if draft.get("hook_style") is not None:
                HookStyle.from_dict(draft["hook_style"])
            transcript = (path / project["transcript_file"]).read_text(encoding="utf-8")
        except Exception as error:
            self.mvp3_log.record("project_open_failed", status="failed", project_path=str(path),
                                 error_type=type(error).__name__, error_message=str(error)[:1000],
                                 traceback=traceback.format_exc()[-12000:])
            QMessageBox.warning(self, "Proyek transkripsi gagal dibuka", str(error))
            return
        self._close_openshot_playback("project_changed")
        self.project_dir = path
        self._source_info, self._source_words, self._source_transcript = info, words, transcript
        self._frame_boundaries = None
        try:
            self.mvp3_log.attach_project(path, project)
        except OSError as error:
            self.mvp3_log.record("project_attach_failed", status="failed", error_type=type(error).__name__,
                                 error_message=str(error)[:500], fallback_path=str(self.mvp3_log.root))
            self.status_label.setText(f"Arsip log proyek gagal ditulis; log sementara: {self.mvp3_log.root}")
        self.project_folder_button.setToolTip(f"Log run MVP 3A: {self.mvp3_log.root}")
        self.mvp3_log.record("project_opened", status="completed", project_id=project.get("project_id"),
                             source_hash=project.get("source_sha256"))
        self._video_duration = float(project["duration"])
        self.source = Path(project["source_path"])
        self.openshot_button.setEnabled(True)
        self.last_result_dir = None
        self.last_video = None
        self.transcript.setPlainText(transcript)
        self.project_folder_button.setEnabled(True)
        self._load_draft(draft)
        self._populate_timeline(words, info)
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
        for widget in (self.split_button, self.delete_segment_button, self.cut_before_button, self.cut_after_button,
                self.edit_undo_button, self.edit_redo_button, self.diagnostic_button, self.timeline):
            widget.setEnabled(active)

    def _set_busy(self, busy: bool) -> None:
        self.pages.setEnabled(not busy)
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
        auxiliary = self._diagnostic_process or self._frame_index_process
        if auxiliary and auxiliary.state() != QProcess.ProcessState.NotRunning:
            self._auxiliary_cancelled = True
            self.mvp3_log.record("auxiliary_cancel_requested", status="running")
            self._terminate_process_tree(auxiliary)
            return
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
        save_draft(self.project_dir, dict(self._editor_snapshot(), hook=hook,
            hook_style=style, subtitle_style=subtitle_style or self.subtitle_style, hook_needs_review=False))
        self._hook_needs_review = False
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
        self._pause_for_edit()
        self._close_openshot_playback("enter_overlay_editor")
        self._discard_preview(keep_image=True)
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
        self.mvp3_log.record("editor_session_started", status="running", project_id=self.project_dir.name,
                             session_id=editor.session_id, target=editor.target)
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
        self.mvp3_log.record("editor_session_finished", status="completed", project_id=self.project_dir.name,
                             session_id=editor.session_id, action=action,
                             dirty=editor.is_dirty(), target=editor.target)
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
        self._update_timeline_hook_track()
        if not self._draft_loading and self.project_dir and not self._style_editing:
            self.draft_timer.start()

    def _save_draft(self) -> bool:
        if not self.project_dir or self._draft_loading or self._style_editing:
            return True
        try:
            save_draft(self.project_dir, self._editor_snapshot())
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
        if self._openshot_ready:
            if self.sender() is self.preview_slider or self._openshot_syncing:
                self._update_time_label()
                return
            self._pause_for_edit()
            self._close_openshot_playback("snapshot_changed")
        if self.project_dir and not self._style_editing:
            self._preview_request += 1
            self._update_time_label()
            self._preview_valid = False
            self._set_preview_progress(True)
            self.preview_status.setText("Preview memperbarui…")
            self._refresh_render_button()
            self.preview_timer.start(300)

    def _toggle_openshot_playback(self) -> None:
        if not self.source or not self.source.is_file():
            return
        try:
            if not self._openshot_ready:
                self._discard_preview()
                context = editor_context(self.project_dir, self._editor_snapshot())
                self._overlay_temp = tempfile.TemporaryDirectory(prefix="videogen-playback-")
                ass = Path(self._overlay_temp.name) / "captions.ass"
                context.write_ass(ass)
                self._ass_overlay = ASSOverlay(ass, [context.subtitle_font.path, context.hook_font.path],
                    context.info.display_width, context.info.display_height)
                self._openshot_playback = LibOpenShotPlayback(self.preview_label)
                self._openshot_metadata = self._openshot_playback.open(self.source, context.edit)
                self.preview_label.native_active = True
                self.preview_label.frame_clock = self._openshot_playback.position_seconds
                self.preview_label.frame_compositor = self._ass_overlay.compose
                self._openshot_ready = True
                self._preview_words_hash = hashlib.sha256((self.project_dir / "words.json").read_bytes()).hexdigest()
                self._preview_valid = True
                self._refresh_render_button()
                self.mvp3_log.update_engine(engine_version=self._openshot_playback.openshot.GetVersion().ToString(),
                                            player="QtPlayer", native_build="local Qt6 / Python 3.13",
                                            playback_source_metadata=self._openshot_metadata)
                self.ffmpeg_preview_button.setEnabled(True)
                self.mvp3_log.record("engine_initialized", status="completed", engine="libopenshot",
                                     engine_version=self._openshot_playback.openshot.GetVersion().ToString(),
                                     player="QtPlayer", source=str(self.source),
                                     source_metadata=self._openshot_metadata,
                                     audio_video_offset=context.source_info.subtitle_offset,
                                     subtitle_offset_policy="applied_once_before_source_to_output_mapping",
                                     frame_time_source="QtPlayer.Position sampled in queued image callback",
                                     snapshot_sha256=hashlib.sha256(json.dumps(self._editor_snapshot(), sort_keys=True).encode()).hexdigest())
                self.preview_status.setText("Playback + Hook/Subtitle aktif · renderer libass. Diagnostik memeriksa parity.")
            player = self._openshot_playback
            if int(player.player.Mode()) == int(player.openshot.PLAYBACK_PLAY):
                player.pause()
                self.openshot_timer.stop()
                self.openshot_button.setText("Lanjutkan dengan libopenshot")
                self.mvp3_log.record("playback_paused", status="completed", position_seconds=player.position_seconds())
            else:
                if self.preview_slider.value() >= self.preview_slider.maximum():
                    self._openshot_syncing = True
                    self.preview_slider.setValue(0)
                    self._openshot_syncing = False
                player.seek_seconds(self.preview_slider.value() / 1000)
                player.play()
                self.openshot_button.setText("Jeda libopenshot")
                self.openshot_timer.start()
                self.mvp3_log.record("playback_started", status="running", position_seconds=player.position_seconds())
        except Exception as error:
            self._close_openshot_playback("initialization_failed")
            detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))[-12000:]
            self.mvp3_log.record("engine_initialization_failed", status="failed", engine="libopenshot",
                                 error_type=type(error).__name__, error_message=str(error)[:1000], traceback=detail)
            self.preview_status.setText(f"libopenshot gagal. Log: {self.mvp3_log.root} · {error}")
            self.openshot_button.setText("Coba lagi dengan libopenshot")

    def _seek_openshot(self, *_args) -> None:
        if not self._openshot_ready or self._openshot_syncing or not self._openshot_playback:
            return
        try:
            timestamp = self.preview_slider.value() / 1000
            self._openshot_playback.seek_seconds(timestamp)
        except Exception as error:
            self.mvp3_log.record("seek_failed", status="failed", error_type=type(error).__name__,
                                 error_message=str(error)[:1000])

    def _record_openshot_seek(self) -> None:
        if not self._openshot_ready or not self._openshot_playback:
            return
        requested = self.preview_slider.value() / 1000
        try:
            actual = self._openshot_playback.position_seconds()
            self.mvp3_log.record("seek_completed", status="completed", requested_seconds=requested,
                                 player_position_seconds=actual, error_seconds=actual-requested)
        except Exception as error:
            self.mvp3_log.record("seek_position_read_failed", status="failed", requested_seconds=requested,
                                 error_type=type(error).__name__, error_message=str(error)[:1000])

    def _sync_openshot_position(self) -> None:
        if not self._openshot_ready or not self._openshot_playback:
            self.openshot_timer.stop()
            return
        try:
            position = self._openshot_playback.position_seconds()
            self._openshot_syncing = True
            self.preview_slider.setValue(round(max(0, min(position, self._video_duration)) * 1000))
            self._openshot_syncing = False
            self._sync_timeline_selection(position)
            self._update_time_label()
            fps = (self._openshot_metadata or {}).get("fps", 30)
            if position >= max(0, self._video_duration-1/max(fps, 1)):
                self._openshot_playback.pause()
                self.openshot_timer.stop()
                self._openshot_syncing = True
                self.preview_slider.setValue(self.preview_slider.maximum())
                self._openshot_syncing = False
                self.openshot_button.setText("Putar ulang dengan libopenshot")
                self.mvp3_log.record("playback_ended", status="completed", position_seconds=position)
        except Exception as error:
            self._openshot_syncing = False
            self.openshot_timer.stop()
            self._close_openshot_playback("position_failed")
            self.mvp3_log.record("playback_position_failed", status="failed", error_type=type(error).__name__,
                                 error_message=str(error)[:1000])

    def _close_openshot_playback(self, reason: str) -> None:
        self.openshot_timer.stop()
        self.preview_label.native_active = False
        self.preview_label.frame_clock = None
        self.preview_label.frame_compositor = None
        if self._openshot_playback:
            try:
                self._openshot_playback.close()
                self.mvp3_log.record("engine_released", status="completed", reason=reason)
            except Exception as error:
                self.mvp3_log.record("engine_release_failed", status="failed", reason=reason,
                                     error_type=type(error).__name__, error_message=str(error)[:1000])
        self._openshot_playback = None
        if self._ass_overlay:
            self._ass_overlay.close()
            self._ass_overlay = None
        if self._overlay_temp:
            self._overlay_temp.cleanup()
            self._overlay_temp = None
        self._openshot_metadata = None
        self._openshot_ready = False
        self.openshot_button.setText("Putar dengan libopenshot")
        self.ffmpeg_preview_button.setEnabled(False)

    def _return_to_ffmpeg_preview(self) -> None:
        self._close_openshot_playback("return_to_ffmpeg_preview")
        self._preview_valid = False
        self._schedule_preview()

    def _start_preview(self) -> None:
        if not self.project_dir:
            return
        if self._style_editing and (self.preview_label._drag is not None or self.preview_label._pending_drag is not None):
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
            timestamp = self.preview_slider.value() / 1000
            preview_path = Path(tempfile.gettempdir()) / f"videogen-preview-{uuid4().hex}.png"
            request = dict(self._editor_snapshot(), request_id=request_id, output=str(preview_path), timestamp=timestamp)
            if self._style_editing:
                request.update(self._style_editor.preview_request())
            preview_snapshot = hashlib.sha256(json.dumps(
                {key: request.get(key) for key in ("hook", "hook_style", "subtitle_style")},
                sort_keys=True, default=str).encode()).hexdigest()
            self.mvp3_log.record("preview_requested", status="running", request_id=request_id,
                                 timestamp=timestamp, snapshot_sha256=preview_snapshot,
                                 target=self._style_editor.target if self._style_editing else "main",
                                 gesture_state=self._style_editor.gesture_state if self._style_editing else None)
            request_path = self._write_request(request)
        except Exception as error:
            self._set_preview_progress(False)
            self.preview_status.setText(f"Preview gagal: {error}")
            if self._style_editing:
                self._style_editor.valid = False
                self._style_editor.apply.setEnabled(False)
                self._style_editor.preview_failed(None, str(error))
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
        if request_id != self._preview_request or (self._style_editing and
                (self.preview_label._drag is not None or self.preview_label._pending_drag is not None)):
            self.mvp3_log.record("preview_discarded_stale", status="ignored", request_id=request_id,
                                 current_request_id=self._preview_request, exit_code=exit_code)
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
                self.mvp3_log.record("preview_finished", status="failed", request_id=request_id,
                                     exit_code=exit_code, failure="invalid_preview_image")
                self.preview_status.setText("Frame preview tidak dapat dibaca; coba ubah waktu preview.")
                path.unlink(missing_ok=True)
                return
            self.mvp3_log.record("preview_finished", status="completed", request_id=request_id,
                                 exit_code=exit_code, cue_timestamp=process.preview_cue_timestamp)
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
            self.mvp3_log.record("preview_finished", status="failed", request_id=request_id,
                                 exit_code=exit_code, error_message=message[:1000],
                                 traceback=str(getattr(process, "preview_traceback", ""))[-12000:])
            self.preview_status.setText(message)
            if self._style_editing:
                self._style_editor.valid = False
                self._style_editor.apply.setEnabled(False)
                self._style_editor.preview_failed(process.preview_cue_timestamp, message)
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
                process.preview_traceback = event.get("traceback", "")
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
                self.mvp3_log.evaluate(check.currentText(), status.currentText(), method=method.text(),
                    result=result.toPlainText(), evidence_path=evidence.text(), revision_id=revision or None)
                self.status_label.setText("Evaluasi tersimpan")
                dialog.close()
            except Exception as error:
                QMessageBox.warning(dialog, "Evaluasi gagal disimpan", str(error))
        save.clicked.connect(persist)
        dialog.exec()

    def _start_diagnostics(self):
        if not self.project_dir or self._style_editing or self._diagnostic_process or self._frame_index_process:
            self.status_label.setText("Terapkan sesi editor dan tunggu proses selesai sebelum pemeriksaan.")
            return
        if not self._save_draft():
            return
        self._pause_for_edit()
        self._close_openshot_playback("diagnostics_started")
        process = self._new_process()
        self._diagnostic_process = process
        request_path = self._write_request(self._editor_snapshot())
        output = self.mvp3_log.root / f"diagnostic-{uuid4().hex[:12]}"
        process.setArguments(["-m", "videogen.diagnostics_runner", "--project", str(self.project_dir),
            "--request", str(request_path), "--output", str(output)])
        self.pages.setEnabled(False)
        self._auxiliary_cancelled = False
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        buffer = ""
        def read():
            nonlocal buffer
            buffer += bytes(process.readAllStandardOutput()).decode(errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "progress":
                    self.progress_bar.setValue(event["percent"])
                    self.status_label.setText(event["stage"])
        done = False
        def finished(code, *_args):
            nonlocal done
            if done:
                return
            done = True
            read()
            stderr = bytes(process.readAllStandardError()).decode(errors="replace")
            self.mvp3_log.record("diagnostics_finished", status="cancelled" if self._auxiliary_cancelled else "completed" if code == 0 else "failed",
                exit_code=code, evidence_path=str(output), stderr=stderr[-12000:])
            request_path.unlink(missing_ok=True)
            self._diagnostic_process = None
            self.pages.setEnabled(True)
            self.cancel_button.hide()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setFormat("Pemeriksaan selesai · %p%" if code == 0 else "Periksa hasil diagnostik")
            self.status_label.setText(f"Diagnostik tersimpan: {output}")
            process.deleteLater()
        process.readyReadStandardOutput.connect(read)
        process.finished.connect(finished)
        process.errorOccurred.connect(lambda error: finished(1) if error == QProcess.ProcessError.FailedToStart else None)
        self.mvp3_log.record("diagnostics_started", status="running", evidence_path=str(output))
        process.start()

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

    def _discard_preview(self, keep_image=False) -> None:
        self._set_preview_progress(False)
        self.preview_timer.stop()
        self._preview_request += 1
        if self._preview_process and self._preview_process.state() != QProcess.ProcessState.NotRunning:
            self._terminate_process_tree(self._preview_process)
        self._preview_valid = False
        if not keep_image:
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
            centiseconds = max(0, round(seconds * 100))
            minutes, remainder = divmod(centiseconds, 6000)
            return f"{minutes:02}:{remainder // 100:02}.{remainder % 100:02}"
        current = self.preview_slider.value() / 1000
        self.time_label.setText(f"{format_time(current)} / {format_time(self._video_duration)}")

    def _populate_timeline(self, words, info) -> None:
        """Build a navigable cue list from the same source-word timestamps as export."""
        self._source_words, self._source_info = words, info
        self._refresh_timeline()

    def _refresh_timeline(self):
        if not self._edit or not self._source_info:
            return
        self._video_duration = self._edit.duration
        self._mapped_words = self._edit.map_words(self._source_words, self._source_info.subtitle_offset)
        self._timeline_cues = project_cues(self._mapped_words, replace(self._source_info, duration=self._video_duration))
        self._timeline_syncing = True
        self.cue_list.clear()
        hook_item = QListWidgetItem("HOOK  ·  00:00 → " + ("video end" if self.full_video.isChecked() else f"{self.duration.value():.1f}s"))
        hook_item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.cue_list.addItem(hook_item)
        for index, cue in enumerate(self._timeline_cues):
            start = max(0, cue.start)
            item = QListWidgetItem(f"{start:06.2f}s   {cue.text}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.cue_list.addItem(item)
        self._timeline_syncing = False
        partial = sum(word.partial for word in self._mapped_words)
        self.timeline_label.setText(f"{len(self._edit.segments)} segmen · {len(self._timeline_cues)} cue · "
            f"{partial} bagian kata terpotong" + (" · Periksa kembali hook setelah potongan berubah" if self._hook_needs_review else ""))
        self.preview_slider.setRange(0, max(1, round(self._video_duration * 1000)))
        self.preview_slider.setSingleStep(33)
        self.preview_slider.setPageStep(1000)
        self.timeline.edit, self.timeline.cues = self._edit, self._timeline_cues
        self.timeline.selected = min(self.timeline.selected, len(self._edit.segments)-1)
        self._update_timeline_hook_track()
        self._zoom_timeline(self.zoom_slider.value())
        self._update_transcript()
        self.edit_undo_button.setEnabled(self._edit_history_index > 0)
        self.edit_redo_button.setEnabled(self._edit_history_index < len(self._edit_history)-1)
        for button in (self.split_button, self.delete_segment_button, self.cut_before_button, self.cut_after_button):
            button.setEnabled(bool(self._edit.segments))
        if not self._edit.segments:
            self._preview_valid = False
            self.preview_status.setText("Timeline kosong · Undo untuk mengembalikan segmen.")
            self._refresh_render_button()

    def _editor_snapshot(self):
        return {"hook": self._hook_spec(), "instruction": self.instruction.text(), "prompt_version": 1,
            "hook_style": self._hook_style_snapshot(), "subtitle_style": self.subtitle_style,
            "timeline": self._edit.to_dict() if self._edit else None,
            "edit_revision": self._edit_revision, "hook_needs_review": self._hook_needs_review}

    def _update_transcript(self, *_args):
        if not self._source_info:
            return
        original = self.transcript_mode.currentIndex() == 1
        self.transcript.setPlainText(self._source_transcript if original else edited_transcript(getattr(self, "_mapped_words", [])))

    def _pause_for_edit(self):
        if self._openshot_ready and self._openshot_playback:
            self._openshot_playback.pause()
            self.openshot_timer.stop()
            self._openshot_syncing = True
            self.preview_slider.setValue(round(self._openshot_playback.position_seconds()*1000))
            self._openshot_syncing = False
            self.openshot_button.setText("Lanjutkan playback")
            self.mvp3_log.record("gesture_playback_lock", status="completed", position_seconds=self.preview_slider.value()/1000)

    def _select_canvas_object(self, target):
        self._edit_hook_style()
        if self._style_editor:
            self.inspector.show()
            self._style_editor.target_combo.setCurrentIndex(1 if target == "subtitle" else 0)

    def _zoom_timeline(self, zoom):
        self.timeline.zoom = float(zoom)
        self.timeline_scroll.setRange(0, round(max(0, self._video_duration-self.timeline.visible_duration)*1000))
        self.timeline.update()

    def _scroll_timeline(self, seconds):
        self.timeline.scroll = seconds
        self.timeline.update()

    def _ensure_frame_index(self, continuation):
        if not self.project_dir or not self._edit or self._style_editing or self.worker.state() != QProcess.ProcessState.NotRunning:
            self.status_label.setText("Terapkan atau batalkan sesi gaya sebelum memotong video.")
            return False
        if self._frame_boundaries is not None:
            return True
        if self._frame_index_process:
            return False
        self._pause_for_edit()
        folder, revision = self.project_dir, self._edit_revision
        process = self._new_process()
        self._frame_index_process = process
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.status_label.setText("Membaca timestamp frame sumber…")
        self.timeline.setEnabled(False)
        self.preview_slider.setEnabled(False)
        self.pages.setEnabled(False)
        self._auxiliary_cancelled = False
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.mvp3_log.record("frame_index_started", status="running", revision=revision)
        finished_once = False
        def finished(code, *_args):
            nonlocal finished_once
            if finished_once:
                return
            finished_once = True
            self._frame_index_process = None
            self.progress_bar.hide()
            self.pages.setEnabled(True)
            self.cancel_button.hide()
            self.timeline.setEnabled(True)
            self.preview_slider.setEnabled(True)
            if folder == self.project_dir and revision == self._edit_revision:
                try:
                    if code:
                        raise RuntimeError(bytes(process.readAllStandardError()).decode(errors="replace")[-2000:])
                    self._frame_boundaries = json.loads((folder / "frame-index.json").read_text())["boundaries"]
                    self.mvp3_log.record("frame_index_completed", status="completed", frame_count=len(self._frame_boundaries)-1)
                    if not self._stopping:
                        continuation()
                except Exception as error:
                    self.mvp3_log.record("frame_index_failed", status="failed", error_message=str(error), traceback=traceback.format_exc())
                    self.status_label.setText(f"Potongan belum diterapkan: {error}")
            process.deleteLater()
        process.setArguments(["-m", "videogen.infrastructure.frame_index", "--project", str(folder)])
        process.finished.connect(finished)
        process.errorOccurred.connect(lambda error: finished(1) if error == QProcess.ProcessError.FailedToStart else None)
        process.start()
        return False

    def _snap_source(self, requested):
        candidate = requested
        if self.snap_words.isChecked() and self._source_words:
            offset = self._source_info.subtitle_offset
            word_edges = [0.0, self._source_info.duration, *(value+offset for word in self._source_words for value in (word.start, word.end))]
            candidate = min(word_edges, key=lambda value: (abs(value-requested), value))
        actual = nearest_boundary(candidate, self._frame_boundaries)
        self.mvp3_log.record("cut_boundary_resolved", status="completed", requested_source_seconds=requested,
            word_snap_seconds=candidate, actual_frame_seconds=actual, snap_words=self.snap_words.isChecked())
        return actual

    def _commit_cut(self, edit, action, *, history=True):
        edit = TimelineEdit.from_dict(edit.to_dict(), self._source_info.duration)
        before = self._edit.to_dict()
        snapshot = dict(self._editor_snapshot(), timeline=edit.to_dict(), edit_revision=self._edit_revision+1, hook_needs_review=True)
        try:
            save_draft(self.project_dir, snapshot)
        except OSError as error:
            self.mvp3_log.record("timeline_commit_failed", status="failed", error_message=str(error), traceback=traceback.format_exc())
            self.status_label.setText(f"Potongan belum tersimpan: {error}")
            return False
        self._pause_for_edit()
        self._close_openshot_playback("timeline_changed")
        self._discard_preview()
        self._edit, self._edit_revision, self._hook_needs_review = edit, self._edit_revision+1, True
        if history:
            self._edit_history = self._edit_history[:self._edit_history_index+1] + [edit.to_dict()]
            self._edit_history_index += 1
        self._refresh_timeline()
        self.mvp3_log.record("timeline_committed", status="completed", action=action, before=before,
            after=edit.to_dict(), revision=self._edit_revision, source_duration=self._source_info.duration,
            output_duration=edit.duration, partial_word_count=sum(word.partial for word in self._mapped_words))
        self.status_label.setText(f"{action} tersimpan · periksa kembali hook.")
        if edit.segments:
            self._schedule_preview()
        return True

    def _split_at_playhead(self):
        if not self._ensure_frame_index(self._split_at_playhead):
            return
        try:
            requested = self._edit.source_time(self.preview_slider.value()/1000)
            actual = self._snap_source(requested)
            cursor = 0.0
            for segment in self._edit.segments:
                if segment.start < actual < segment.end:
                    self._commit_cut(self._edit.split(cursor+actual-segment.start), "Split")
                    return
                cursor += segment.end-segment.start
            raise ValueError("Pilih titik di dalam segmen, bukan pada tepinya.")
        except ValueError as error:
            self.status_label.setText(str(error))

    def _trim_boundary(self, index, side, requested):
        if not self._ensure_frame_index(lambda: self._trim_boundary(index, side, requested)):
            return
        try:
            segments = list(self._edit.segments)
            actual = self._snap_source(requested)
            segments[index] = replace(segments[index], **{side: actual})
            self._commit_cut(replace(self._edit, segments=tuple(segments)), "Trim")
        except (ValueError, IndexError) as error:
            self.status_label.setText(str(error))

    def _trim_at_playhead(self, before):
        if not self._ensure_frame_index(lambda: self._trim_at_playhead(before)):
            return
        try:
            source = self._edit.source_time(self.preview_slider.value()/1000)
            actual = self._snap_source(source)
            segments = []
            for segment in self._edit.segments:
                start = max(segment.start, actual) if before else segment.start
                end = segment.end if before else min(segment.end, actual)
                if end > start:
                    segments.append(replace(segment, start=start, end=end))
            self._commit_cut(replace(self._edit, segments=tuple(segments)), "Trim awal" if before else "Trim akhir")
        except ValueError as error:
            self.status_label.setText(str(error))

    def _delete_segment(self):
        if self._style_editing or not self._edit:
            return
        index = self.timeline.selected
        if index < 0 or index >= len(self._edit.segments):
            self.status_label.setText("Pilih segmen pada track Video sebelum menghapus.")
            return
        self._commit_cut(replace(self._edit, segments=self._edit.segments[:index]+self._edit.segments[index+1:]), "Hapus segmen")

    def _undo_cut(self, delta):
        if self._style_editing or not self._source_info:
            return
        index = self._edit_history_index+delta
        if 0 <= index < len(self._edit_history):
            edit = TimelineEdit.from_dict(self._edit_history[index], self._source_info.duration)
            if self._commit_cut(edit, "Undo" if delta < 0 else "Redo", history=False):
                self._edit_history_index = index
                self._refresh_timeline()

    def _update_timeline_hook_track(self) -> None:
        if self.cue_list.count() == 0:
            return
        end = "video end" if self.full_video.isChecked() else f"{min(self.duration.value(), self._video_duration or self.duration.value()):.1f}s"
        self.cue_list.item(0).setText(f"HOOK  ·  00:00 → {end}")
        self.timeline.hook_end = (self._video_duration if self.full_video.isChecked() else min(self.duration.value(), self._video_duration)) if self.hook_enabled.isChecked() else 0
        self.timeline.update()

    def _select_timeline_cue(self, row: int) -> None:
        if self._timeline_syncing or row <= 0 or row > len(self._timeline_cues):
            return
        cue = self._timeline_cues[row - 1]
        self.preview_slider.setValue(round(cue.start * 1000))
        self.mvp3_log.record("timeline_cue_selected", status="completed", cue_index=row - 1,
                             requested_seconds=cue.start, cue_end_seconds=cue.end)

    def _sync_timeline_selection(self, seconds: float) -> None:
        self.timeline.position = seconds
        self.timeline.update()
        active = next((index for index, cue in enumerate(self._timeline_cues)
                       if cue.start <= seconds < cue.end), None)
        row = active + 1 if active is not None else -1
        if self.cue_list.currentRow() != row:
            self._timeline_syncing = True
            self.cue_list.setCurrentRow(row)
            self._timeline_syncing = False

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
        auxiliary = self._diagnostic_process or self._frame_index_process
        if auxiliary and auxiliary.state() != QProcess.ProcessState.NotRunning:
            self._stopping = True
            self._auxiliary_cancelled = True
            self._terminate_process_tree(auxiliary)
            event.ignore()
            QTimer.singleShot(250, self.close)
            return
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
            self._close_openshot_playback("application_shutdown")
            self.mvp3_log.finish("cancelled", close_reason="shutdown_after_cancel")
            if sys.excepthook == self._record_uncaught_exception:
                sys.excepthook = self._previous_excepthook
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
            self._close_openshot_playback("application_shutdown")
            self.mvp3_log.finish("completed", close_reason="window_closed")
            if sys.excepthook == self._record_uncaught_exception:
                sys.excepthook = self._previous_excepthook
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
