from copy import deepcopy
from dataclasses import asdict
import os
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget)

from videogen.application.projects import _append_event
from videogen.application.hook_presets import HookPresets, font_reference
from videogen.domain.hook import HookStyle
from videogen.domain.subtitle_style import SubtitleStyle
from videogen.infrastructure.fonts import SubtitleFont, default_font_path


class HookStyleEditor(QWidget):
    """One temporary text/style session; global preset writes are independent."""
    def __init__(self, owner) -> None:
        super().__init__(owner)
        self.owner = owner
        self.store = HookPresets()
        self.session_id = uuid4().hex
        self.hook = deepcopy(owner._hook_spec())
        self.initial_hook = deepcopy(self.hook)
        self.main_slider_value = owner.preview_slider.value()
        self.current = asdict(HookStyle.from_dict(owner._hook_style_snapshot())) if owner.hook_style else asdict(HookStyle(top_fraction=self.hook['top_fraction']))
        self.current['schema_version'] = 3
        self.target = 'hook'
        self.styles = {'hook': deepcopy(self.current), 'subtitle': asdict(SubtitleStyle.from_dict(owner.subtitle_style))}
        self.cue_starts = []
        self.error_timestamp = None
        self.loading = True
        self.history = []
        self.history_index = 0
        self.gesture_before = None
        self.gesture_origin = None
        self.typing_before = None
        self.gesture_state = None
        self.valid = False
        self.reference = self.current['font']
        self.selected_id = self.current['preset_id']
        self.preset_version = self.current['preset_version']
        self.example = not self.hook['enabled'] or not self.hook['text'].strip()
        self.interval = max(.01, owner._video_duration)
        self.preview_limit = max(0, self.interval-.02)
        self.status, self.preview, self.time, self.slider = owner.preview_status, owner.preview_label, owner.time_label, owner.preview_slider
        self.slider.setEnabled(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        self.target_combo = QComboBox()
        self.target_combo.addItem('Hook', 'hook')
        self.target_combo.addItem('Subtitle · Seluruh video', 'subtitle')
        layout.addWidget(self.target_combo)
        self.target_hint = QLabel('Hook')
        layout.addWidget(self.target_hint)
        self.center_button = QPushButton('Pusatkan hook')
        self.next_cue_button = QPushButton('Ke subtitle berikutnya')
        self.invalid_cue_button = QPushButton('Ke cue yang tidak muat')
        self.invalid_cue_button.hide()
        layout.addWidget(self.center_button)
        layout.addWidget(self.next_cue_button)
        layout.addWidget(self.invalid_cue_button)
        hint = QLabel('Tarik teks/frame untuk memindahkan objek aktif. Klik dua kali hook untuk mengetik. Sisi mengubah lebar; sudut mengubah font.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.font_combo = QComboBox()
        self.font_button = QPushButton('Impor font…')
        self.font_refs = {}
        font_row = QHBoxLayout()
        font_row.addWidget(self.font_combo, 1)
        font_row.addWidget(self.font_button)
        layout.addLayout(font_row)
        self.bold = QPushButton('B')
        self.italic = QPushButton('I')
        self.bold.setCheckable(True)
        self.italic.setCheckable(True)
        self.alignment = QComboBox()
        self.alignment.addItem('Rata kiri', 'left')
        self.alignment.addItem('Tengah', 'center')
        self.alignment.addItem('Rata kanan', 'right')
        appearance_row = QHBoxLayout()
        appearance_row.addWidget(self.bold)
        appearance_row.addWidget(self.italic)
        appearance_row.addWidget(self.alignment, 1)
        layout.addLayout(appearance_row)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(1, 1000)
        self.size_slider.setToolTip('Ukuran font; tarik sudut pada preview untuk penyesuaian visual.')
        layout.addWidget(QLabel('Ukuran huruf'))
        layout.addWidget(self.size_slider)
        colors = QHBoxLayout()
        self.text_color_button = QPushButton('Warna teks')
        self.background_color_button = QPushButton('Warna latar')
        self.background_enabled = QCheckBox('Latar')
        colors.addWidget(self.text_color_button)
        colors.addWidget(self.background_color_button)
        colors.addWidget(self.background_enabled)
        layout.addLayout(colors)
        subtitle_colors = QHBoxLayout()
        self.active_color_button = QPushButton('Warna kata aktif')
        self.stroke_color_button = QPushButton('Warna stroke')
        subtitle_colors.addWidget(self.active_color_button)
        subtitle_colors.addWidget(self.stroke_color_button)
        layout.addLayout(subtitle_colors)
        self.auto_size = QComboBox()
        self.auto_size.addItems(['Otomatis agar muat', 'Ukuran tetap'])
        self.manual = QComboBox()
        self.manual.addItems(['Baris otomatis', 'Newline manual'])
        modes = QHBoxLayout()
        modes.addWidget(self.auto_size, 1)
        modes.addWidget(self.manual, 1)
        layout.addLayout(modes)
        history_row = QHBoxLayout()
        self.undo_button = QPushButton('↶ Undo')
        self.redo_button = QPushButton('↷ Redo')
        history_row.addWidget(self.undo_button)
        history_row.addWidget(self.redo_button)
        layout.addLayout(history_row)
        self.advanced_button = QPushButton('▸ Pengaturan lanjutan')
        self.advanced_button.setCheckable(True)
        layout.addWidget(self.advanced_button)
        self.advanced = QWidget()
        form = QFormLayout(self.advanced)
        self.controls = {}
        for key, label, lo, hi, value in [
            ('width_fraction', 'Lebar maksimum', 1, 100, 84),
            ('size_fraction', 'Font / tinggi video', .01, 100, 3),
            ('center_fraction', 'Pusat horizontal', -1000000, 1000000, 50),
            ('top_fraction', 'Posisi vertikal', -1000000, 1000000, 15),
            ('padding_x', 'Padding horizontal', 0, 3, 1),
            ('padding_y', 'Padding vertikal', 0, 1, .5),
            ('line_gap', 'Jarak baris / font', 0, 30, 10),
            ('radius_fraction', 'Radius / tinggi', 0, 2, .5),
            ('outline_fraction', 'Stroke / ukuran font', 0, 50, 2.5),
        ]:
            control = QDoubleSpinBox()
            control.setDecimals(3)
            control.setRange(lo, hi)
            control.setValue(value)
            control.setSuffix('%')
            self.controls[key] = control
            form.addRow(label, control)
            control.field_label = form.labelForField(control)
            control.valueChanged.connect(self.changed)
        self.advanced.hide()
        layout.addWidget(self.advanced)
        self.preset = QComboBox()
        self.preset_status = QLabel()
        self.preset_status.setWordWrap(True)
        layout.addWidget(QLabel('Preset'))
        layout.addWidget(self.preset)
        layout.addWidget(self.preset_status)
        self.save_preset = QPushButton('Simpan preset…')
        self.update_preset = QPushButton('Perbarui preset')
        self.default_preset = QPushButton('Jadikan default')
        self.delete_preset = QPushButton('Hapus preset')
        self.reset_style = QPushButton('Kembalikan gaya bawaan')
        preset_row = QHBoxLayout()
        preset_row.addWidget(self.save_preset)
        preset_row.addWidget(self.default_preset)
        layout.addLayout(preset_row)
        self.preset_more = QWidget()
        more = QVBoxLayout(self.preset_more)
        for button in (self.update_preset, self.delete_preset, self.reset_style):
            more.addWidget(button)
        more_button = QPushButton('Lainnya untuk preset ▸')
        more_button.setCheckable(True)
        more_button.toggled.connect(self.preset_more.setVisible)
        layout.addWidget(more_button)
        layout.addWidget(self.preset_more)
        self.preset_more.hide()
        note = QLabel('Preset/default yang disimpan tetap berlaku setelah Batal. Teks tidak disimpan dalam preset.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.apply = QPushButton('Terapkan')
        self.apply.setEnabled(False)
        cancel = QPushButton('Batal')
        footer = QHBoxLayout()
        footer.addWidget(self.apply)
        footer.addWidget(cancel)
        root = QVBoxLayout(self)
        root.addWidget(QLabel('Edit hook / subtitle sementara'))
        root.addWidget(scroll, 1)
        root.addLayout(footer)
        self.timer = owner.preview_timer
        self.catalogue_fonts()
        self.target_combo.currentIndexChanged.connect(self.switch_target)
        self.center_button.clicked.connect(self.center_object)
        self.next_cue_button.clicked.connect(self.next_cue)
        self.invalid_cue_button.clicked.connect(self.goto_invalid_cue)
        self.active_color_button.clicked.connect(lambda: self.choose_subtitle_color('active_word_color'))
        self.stroke_color_button.clicked.connect(lambda: self.choose_subtitle_color('outline_color'))
        self.advanced_button.toggled.connect(self.toggle_advanced)
        self.size_slider.valueChanged.connect(self.slider_size_changed)
        self.font_combo.currentIndexChanged.connect(self.select_font)
        self.font_button.clicked.connect(self.import_font)
        self.bold.clicked.connect(lambda: self.select_variant(True))
        self.italic.clicked.connect(lambda: self.select_variant(False))
        self.alignment.currentIndexChanged.connect(self.changed)
        self.background_enabled.toggled.connect(self.changed)
        self.auto_size.currentIndexChanged.connect(self.changed)
        self.manual.currentIndexChanged.connect(self.changed)
        self.text_color_button.clicked.connect(lambda: self.choose_color(False))
        self.background_color_button.clicked.connect(lambda: self.choose_color(True))
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.preset.currentIndexChanged.connect(self.select_preset)
        self.save_preset.clicked.connect(lambda: self.persist(False))
        self.update_preset.clicked.connect(lambda: self.persist(True))
        self.default_preset.clicked.connect(self.make_default)
        self.delete_preset.clicked.connect(self.remove_preset)
        self.reset_style.clicked.connect(lambda: self.load_style(asdict(self.model()())))
        self.apply.clicked.connect(self.apply_style)
        cancel.clicked.connect(lambda: owner._end_style_session('batal'))
        self.slider.valueChanged.connect(self.changed)
        self.preview.gestureStarted.connect(self.gesture_started)
        self.preview.gestureChanged.connect(self.gesture_changed)
        self.preview.gestureFinished.connect(self.gesture_finished)
        self.preview.textStarted.connect(self.text_started)
        self.preview.textChanged.connect(self.text_changed)
        self.preview.textFinished.connect(self.text_finished)
        self.preview.set_editor(True)
        self.load_style(self.current, manual=self.hook['manual'])
        self.history = [self.state()]
        self.initial_state = deepcopy(self.history[0])
        self.refresh_history_buttons()
        self.refresh_target()

    def model(self):
        return SubtitleStyle if self.target == 'subtitle' else HookStyle

    def refresh_target(self):
        subtitle = self.target == 'subtitle'
        self.preview.target = self.target
        self.target_hint.setText('Subtitle · Seluruh video' if subtitle else 'Hook · Judul video')
        self.center_button.setText('Pusatkan subtitle' if subtitle else 'Pusatkan hook')
        self.next_cue_button.setText('Ke subtitle berikutnya' if subtitle else 'Ke hook')
        for widget in (self.background_color_button, self.background_enabled, self.auto_size, self.manual):
            widget.setVisible(not subtitle)
        for widget in (self.active_color_button, self.stroke_color_button):
            widget.setVisible(subtitle)
        for key in ('padding_x', 'padding_y', 'line_gap', 'radius_fraction', 'outline_fraction'):
            visible = (key == 'outline_fraction') == subtitle
            self.controls[key].setVisible(visible)
            self.controls[key].field_label.setVisible(visible)
        self.controls['top_fraction'].field_label.setText('Pusat vertikal' if subtitle else 'Posisi tepi atas')

    def switch_target(self):
        if self.loading:
            return
        self.preview.finish_text(False)
        self.preview.cancel_gesture()
        self.styles[self.target] = self.style()
        self.target = self.target_combo.currentData()
        self.preview.target = self.target
        self.preview._block_fraction = .1
        self.load_style(self.styles[self.target], record=False)
        self.refresh_target()
        self.log('target_select')

    def center_object(self):
        self.preview.finish_text(False)
        self.controls['center_fraction'].blockSignals(True)
        self.controls['top_fraction'].blockSignals(True)
        self.controls['center_fraction'].setValue(50)
        self.controls['top_fraction'].setValue(50 if self.target == 'subtitle' else 50-self.preview._block_fraction*50)
        self.controls['center_fraction'].blockSignals(False)
        self.controls['top_fraction'].blockSignals(False)
        self.changed()
        self.log('center_object')

    def next_cue(self):
        if self.target == "hook":
            self.slider.setValue(0)
            return
        timestamp = self.preview_limit*self.slider.value()/1000
        next_time = next((t for t in self.cue_starts if t > timestamp+.02), self.cue_starts[0] if self.cue_starts else None)
        if next_time is not None:
            self.slider.setValue(min(1000, round((next_time+.01)/max(.01,self.preview_limit)*1000)))

    def goto_invalid_cue(self):
        if self.error_timestamp is not None:
            self.slider.setValue(min(1000, round(self.error_timestamp/max(.01,self.preview_limit)*1000)))

    def preview_failed(self, timestamp):
        self.error_timestamp = timestamp
        self.invalid_cue_button.setVisible(timestamp is not None)

    def choose_subtitle_color(self, key):
        color = QColorDialog.getColor(QColor(getattr(self, key)), self, 'Warna subtitle')
        if color.isValid():
            setattr(self, key, color.name())
            self.changed()

    def catalogue_fonts(self) -> None:
        paths = {default_font_path()}
        paths.update(default_font_path().parent.glob('*.otf'))
        paths.update(default_font_path().parent.glob('*.ttf'))
        cache = Path(os.environ.get('XDG_CACHE_HOME') or Path.home()/'.cache')/'videogen'/'fonts'
        paths.update(cache.glob('*.otf')); paths.update(cache.glob('*.ttf'))
        for item in self.store.data['presets']:
            ref = item['style'].get('font')
            if ref:
                paths.add(Path(ref['path']))
        for style in self.styles.values():
            if style.get("font"):
                paths.add(Path(style["font"]["path"]))
        if self.reference:
            paths.add(Path(self.reference['path']))
        for path in sorted(paths):
            try:
                ref = font_reference(SubtitleFont(path, strict_subtitle=False))
                self.font_refs[ref['sha256']] = ref
            except Exception:
                continue
        self.refresh_fonts()

    def refresh_fonts(self) -> None:
        self.font_combo.blockSignals(True)
        self.font_combo.clear()
        for digest, ref in self.font_refs.items():
            self.font_combo.addItem(f"{ref['family']} · {ref['style']}", digest)
        if self.reference and self.reference['sha256'] not in self.font_refs:
            self.font_combo.addItem('Font proyek tidak tersedia', self.reference['sha256'])
        current = self.reference or next((r for r in self.font_refs.values() if r['path'] == str(default_font_path())), {})
        index = self.font_combo.findData(current.get('sha256'))
        self.font_combo.setCurrentIndex(index)
        self.font_combo.blockSignals(False)
        self.refresh_variants()

    def refresh_variants(self) -> None:
        ref = self.reference or next((r for r in self.font_refs.values() if r['path'] == str(default_font_path())), {})
        bold, italic = ref.get('weight', 700) >= 600, bool(ref.get('italic', False))
        for button, target_bold, target_italic in ((self.bold, not bold, italic), (self.italic, bold, not italic)):
            button.blockSignals(True)
            button.setChecked(bold if button is self.bold else italic)
            available = any(r['family'] == ref.get('family') and (r['weight'] >= 600) == target_bold and r['italic'] == target_italic for r in self.font_refs.values())
            button.setEnabled(available)
            button.setToolTip('Pilih varian font asli' if available else 'Varian belum tersedia; impor file font yang sesuai.')
            button.blockSignals(False)

    def select_font(self) -> None:
        if self.loading:
            return
        ref = self.font_refs.get(self.font_combo.currentData())
        if ref:
            self.reference = deepcopy(ref)
            self.refresh_variants()
            self.changed()

    def select_variant(self, toggle_bold: bool) -> None:
        ref = self.reference or next((r for r in self.font_refs.values() if r['path'] == str(default_font_path())), {})
        bold, italic = ref.get('weight', 700) >= 600, bool(ref.get('italic', False))
        target = next((r for r in self.font_refs.values() if r['family'] == ref.get('family') and (r['weight'] >= 600) == (not bold if toggle_bold else bold) and r['italic'] == (italic if toggle_bold else not italic)), None)
        if target:
            self.reference = deepcopy(target)
            self.refresh_fonts()
            self.changed()

    def import_font(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, 'Pilih font', '', 'Font (*.ttf *.otf)')
        if path:
            try:
                self.reference = self.store.import_font(Path(path))
                self.font_refs[self.reference['sha256']] = self.reference
                self.refresh_fonts()
                self.changed()
            except Exception as error:
                QMessageBox.warning(self, 'Font gagal diimpor', str(error))

    def choose_color(self, background: bool) -> None:
        old = self.background_color if background else self.text_color
        color = QColorDialog.getColor(QColor(old), self, 'Warna latar' if background else 'Warna teks')
        if color.isValid():
            if background:
                self.background_color = color.name()
            else:
                self.text_color = color.name()
            self.changed()

    def toggle_advanced(self, visible: bool) -> None:
        self.advanced.setVisible(visible)
        self.advanced_button.setText('▾ Pengaturan lanjutan' if visible else '▸ Pengaturan lanjutan')

    def slider_size_changed(self, value: int) -> None:
        if not self.loading:
            self.controls['size_fraction'].setValue(value/10)

    def style(self) -> dict:
        values = {key: control.value()/100 for key, control in self.controls.items()}
        if not self.size_changed:
            values['size_fraction'] = self.current.get('size_fraction')
        if not self.radius_changed:
            values['radius_fraction'] = self.current.get('radius_fraction')
        outline = values.pop('outline_fraction')
        extra = {'active_word_color': self.active_word_color, 'outline_color': self.outline_color, 'outline_fraction': outline} if self.target == 'subtitle' else {}
        return asdict(self.model()(**values, **extra, auto_size=self.target == 'hook' and self.auto_size.currentIndex() == 0,
            alignment=self.alignment.currentData(), text_color=self.text_color,
            background_color=self.background_color, background_enabled=self.target == 'hook' and self.background_enabled.isChecked(),
            font=self.reference, preset_id=self.selected_id, preset_version=self.preset_version))

    def state(self) -> dict:
        styles = deepcopy(self.styles)
        styles[self.target] = self.style()
        return {'styles': styles, 'text': self.hook['text'], 'manual': self.manual.currentIndex() == 1}

    def load_style(self, style: dict, manual: bool | None = None, *, record: bool = True) -> None:
        self.loading = True
        self.current = asdict(self.model().from_dict(style))
        self.current['schema_version'] = 3
        self.selected_id, self.preset_version = self.current['preset_id'], self.current['preset_version']
        self.reference = self.current['font']
        if self.reference and self.reference["sha256"] in self.font_refs:
            available = self.font_refs[self.reference["sha256"]]
            self.reference = dict(self.reference, weight=available["weight"], italic=available["italic"], style=available["style"])
        height, width = self.owner._video_height, self.owner._video_width
        initial = max(18, round(min((.045 if self.target == "subtitle" else .03)*height, (.08 if self.target == "subtitle" else .06)*width)))
        for key, control in self.controls.items():
            value = self.current.get(key, .025 if key == "outline_fraction" else None)
            if value is None:
                value = initial/height if key == 'size_fraction' else min(initial*.22/height, .02)
            control.setValue(value*100)
        self.size_changed = self.radius_changed = False
        self.auto_size.setCurrentIndex(0 if self.current['auto_size'] else 1)
        if manual is not None:
            self.manual.setCurrentIndex(1 if manual else 0)
        self.alignment.setCurrentIndex(self.alignment.findData(self.current['alignment']))
        self.background_enabled.setChecked(self.current['background_enabled'])
        self.text_color, self.background_color = self.current['text_color'], self.current['background_color']
        self.active_word_color = self.current.get("active_word_color", "#FFFF00")
        self.outline_color = self.current.get("outline_color", "#101010")
        self.refresh_fonts()
        self.refresh_presets()
        self.loading = False
        self.changed(record=record)

    def push_history(self) -> None:
        state = self.state()
        if self.history and state != self.history[self.history_index]:
            self.history = self.history[:self.history_index+1] + [state]
            self.history_index += 1
        self.refresh_history_buttons()

    def refresh_history_buttons(self) -> None:
        typing = self.preview._text_active
        self.undo_button.setEnabled(self.preview.input.document().isUndoAvailable() if typing else self.history_index > 0)
        self.redo_button.setEnabled(self.preview.input.document().isRedoAvailable() if typing else self.history_index < len(self.history)-1)

    def undo(self) -> None:
        if self.preview._text_active:
            self.preview.input.undo()
            return
        if self.history_index:
            self.history_index -= 1
            self.restore_history('undo')

    def redo(self) -> None:
        if self.preview._text_active:
            self.preview.input.redo()
            return
        if self.history_index < len(self.history)-1:
            self.history_index += 1
            self.restore_history('redo')

    def restore_history(self, action: str) -> None:
        value = self.history[self.history_index]
        self.hook['text'] = value['text']
        self.styles = deepcopy(value['styles'])
        self.load_style(self.styles[self.target], value['manual'], record=False)
        self.refresh_history_buttons()
        self.log(action)

    def changed(self, *_args, record: bool = True) -> None:
        if self.loading:
            return
        if self.sender() is self.controls['size_fraction']:
            self.size_changed = True
        if self.sender() is self.controls['radius_fraction']:
            self.radius_changed = True
        self.example = not self.hook['enabled'] or not self.hook['text'].strip()
        self.preview._text_value = self.hook['text']
        self.slider.setEnabled(True)
        self.owner._preview_request += 1
        self.owner._set_preview_progress(self.gesture_before is None)
        self.valid = False
        self.apply.setEnabled(False)
        self.refresh_history_buttons()
        self.status.setText('Sedang menggeser · lepas untuk memperbarui preview' if self.gesture_before is not None else 'Sedang mengetik · preview belum tervalidasi' if self.preview._text_active else 'Preview memperbarui…')
        self.time.setText(f"{self.preview_limit*self.slider.value()/1000:.2f} / {self.interval:.2f} detik")
        if self.gesture_before is None:
            self.timer.start(300)
        else:
            self.timer.stop()
        self.preview.set_layout(self.controls['top_fraction'].value()/100, self.controls['width_fraction'].value()/100,
            center=self.controls['center_fraction'].value()/100, size=self.controls['size_fraction'].value()/100, validated=False)
        self.size_slider.blockSignals(True)
        self.size_slider.setValue(round(self.controls['size_fraction'].value()*10))
        self.size_slider.blockSignals(False)
        self.update_input_font()
        self.text_color_button.setStyleSheet(f'color:{self.text_color};background:#ddd')
        self.background_color_button.setStyleSheet(f'background:{self.background_color};color:#333')
        self.owner._refresh_render_button()
        if record and self.gesture_before is None and self.typing_before is None and not self.preview._text_active:
            self.push_history()
        selected = self.selected()
        baseline = asdict(self.model().from_dict(selected['style'])) if selected else asdict(self.model()())
        baseline['schema_version'] = 3
        clean = self.same_style(baseline, self.style())
        self.preset_status.setText('Gaya sesuai preset' if clean else 'Gaya diubah · belum disimpan sebagai preset')
        self.refresh_history_buttons()
        self.update_preset.setEnabled(selected is not None)
        self.delete_preset.setEnabled(selected is not None)
        self.default_preset.setEnabled(clean and (selected is not None or self.selected_id is None))

    def update_input_font(self) -> None:
        ref = self.reference or next((r for r in self.font_refs.values() if r['path'] == str(default_font_path())), {})
        font = QFont(ref.get('family', 'Helvetica Neue'))
        font.setWeight(QFont.Weight(ref.get('weight', 700)))
        font.setItalic(ref.get('italic', False))
        if ref.get('style'):
            font.setStyleName(ref['style'])
        font.setPixelSize(max(1, round(self.preview.image_rect().height()*self.controls['size_fraction'].value()/100)))
        self.preview.input.setFont(font)
        color = self.background_color if self.background_enabled.isChecked() else '#eeeeee'
        self.preview.input.setStyleSheet(f'QPlainTextEdit {{color:{self.text_color};background:{color};border:2px dashed #2689ff;}}')

    def text_started(self) -> None:
        self.typing_before = self.state()
        self.update_input_font()
        self.apply.setEnabled(False)
        self.refresh_history_buttons()
        self.status.setText('Sedang mengetik · Ctrl+Enter selesai, Escape batal teks')

    def text_changed(self, text: str) -> None:
        self.hook['text'] = text
        self.changed(record=False)

    def text_finished(self, cancelled: bool) -> None:
        if self.typing_before is None:
            return
        if cancelled:
            self.hook['text'] = self.typing_before['text']
        self.typing_before = None
        self.changed(record=False)
        if not cancelled:
            self.push_history()
        self.refresh_history_buttons()
        self.log('text_cancel' if cancelled else 'text_commit')

    def gesture_started(self) -> None:
        self.gesture_before = self.state()
        self.gesture_origin = {key: self.gesture_before['styles'][self.target][key]
                               for key in ('top_fraction', 'center_fraction', 'width_fraction', 'size_fraction')}
        self.gesture_state = 'started'
        self.timer.stop()
        self.owner._set_preview_progress(False)
        self.status.setText('Sedang menggeser · lepas untuk memperbarui preview')
        self.owner._preview_request += 1
        self.valid = False
        self.apply.setEnabled(False)
        self.log('gesture_start')

    def gesture_changed(self, top: float, center: float, width: float, size: float) -> None:
        if abs(self.controls['size_fraction'].value()/100-size) > .00001:
            self.size_changed = True
        for key, value in (('top_fraction', top), ('center_fraction', center), ('width_fraction', width), ('size_fraction', size)):
            control = self.controls[key]
            control.blockSignals(True)
            control.setValue(value*100)
            control.blockSignals(False)
        self.gesture_state = 'moving'
        self.changed(record=False)

    def gesture_finished(self, cancelled: bool) -> None:
        initial = self.gesture_before
        self.gesture_before = None
        self.gesture_state = 'cancelled' if cancelled else 'released'
        if cancelled and initial:
            self.hook['text'] = initial['text']
            self.styles = deepcopy(initial['styles'])
            self.load_style(self.styles[self.target], initial['manual'], record=False)
        else:
            self.changed(record=False)
            self.push_history()
        self.timer.start(0)
        self.log('gesture_cancel' if cancelled else 'gesture_commit')

    def preview_request(self) -> dict:
        styles = self.state()['styles']
        hook = dict(self.hook, top_fraction=styles['hook']['top_fraction'], manual=self.manual.currentIndex() == 1)
        if self.example:
            hook.update(text='CONTOH GAYA HOOK', enabled=True, manual=False)
        return {'timestamp': self.preview_limit*self.slider.value()/1000,
                'hook': hook, 'hook_style': styles['hook'], 'subtitle_style': styles['subtitle'], 'style_example': self.example,
                'style_session_id': self.session_id, 'editor_mode': 'visual', 'editor_target': self.target,
                'gesture_state': self.gesture_state}

    def preview_ready(self, layout: dict) -> None:
        errors = layout.get("validation_errors") or []
        self.preview_failed(errors[0]["timestamp"] if errors else None)
        self.cue_starts = layout.get('cue_starts', [])
        if self.target == 'subtitle':
            bounds = layout.get('subtitle_bounds')
            block = bounds['height']/self.owner._video_height if bounds else .1
        else:
            panels = layout.get('panel_bounds') or []
            block = (max(p['y']+p['height'] for p in panels)-min(p['y'] for p in panels))/self.owner._video_height if panels else .10
        self.valid = bool(layout.get('all_cues_valid')) and not self.preview._text_active and self.gesture_before is None
        self.preview.set_layout(self.controls['top_fraction'].value()/100, self.controls['width_fraction'].value()/100,
            block, center=self.controls['center_fraction'].value()/100, size=self.controls['size_fraction'].value()/100, validated=self.valid)
        prefix = 'Contoh hook · ' if self.example and self.target == 'hook' else ''
        if self.target == 'hook' and not layout.get('hook_visible'):
            prefix += 'Hook tidak tampil pada waktu ini · '
        if self.target == 'subtitle' and not layout.get('subtitle_visible'):
            prefix = 'Jeda ucapan · frame global · '
        self.status.setText(errors[0]['reason'] if errors else prefix + ('Preview siap · semua cue valid' if self.valid else 'Preview sementara · lanjutkan edit'))
        self.apply.setEnabled(self.valid and not (self.hook['enabled'] and not self.hook['text'].strip()))
        self.update_input_font()

    def is_dirty(self) -> bool:
        return self.state() != self.initial_state

    def apply_style(self) -> bool:
        if self.preview.finish_text(False):
            return False
        if not self.valid or not self.apply.isEnabled():
            self.status.setText('Tunggu preview terbaru yang valid sebelum Terapkan.')
            return False
        try:
            self.owner._apply_hook_style(self.state()['styles']['hook'], self.manual.currentIndex() == 1, self.hook['text'], self.state()['styles']['subtitle'])
        except Exception as error:
            QMessageBox.warning(self, 'Hook belum tersimpan', str(error))
            return False
        self.owner._end_style_session('terapkan')
        return True

    def stop_session(self) -> None:
        self.timer.stop()
        self.preview.finish_text(True)
        self.preview.cancel_gesture()
        for signal, slot in ((self.slider.valueChanged, self.changed), (self.preview.gestureStarted, self.gesture_started),
            (self.preview.gestureChanged, self.gesture_changed), (self.preview.gestureFinished, self.gesture_finished),
            (self.preview.textStarted, self.text_started), (self.preview.textChanged, self.text_changed), (self.preview.textFinished, self.text_finished)):
            signal.disconnect(slot)
        self.preview.set_editor(False)
        self.slider.blockSignals(True)
        self.slider.setValue(self.main_slider_value)
        self.slider.setEnabled(True)
        self.slider.blockSignals(False)
        self.timer.stop()

    def log(self, action: str) -> None:
        values = self.style()
        values.pop('font', None)
        try:
            _append_event(self.owner.project_dir, operation='visual_editor', status='completed', editor_mode='visual',
                session_id=self.session_id, request_id=self.owner._preview_request, action=action, target=self.target,
                subtitle_scope='whole_video', style=values,
                gesture_mode=self.preview.gesture_mode if action.startswith('gesture_') else None,
                gesture_reason=self.preview.gesture_reason if action.startswith('gesture_') else None,
                gesture_from=self.gesture_origin if action.startswith('gesture_') else None)
        except OSError as error:
            self.preset_status.setText(f'Log editor gagal ditulis: {error}')

    @staticmethod
    def same_style(left: dict, right: dict) -> bool:
        def normalized(value):
            result = {k:v for k,v in value.items() if k not in ('preset_id', 'preset_version')}
            if result.get('font'):
                result['font'] = {k:result['font'].get(k) for k in ('path','family','postscript_name','sha256')}
            return result
        return normalized(left) == normalized(right)

    def selected(self):
        return next((p for p in self.store.data['presets'] if p['id'] == self.selected_id and p.get('target', 'hook') == self.target), None)

    def refresh_presets(self) -> None:
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem('Gaya bawaan', None)
        for item in self.store.data['presets']:
            if item.get('target', 'hook') != self.target:
                continue
            self.preset.addItem(item['name']+(' · default' if item['id'] == self.store.data.get('subtitle_default_id' if self.target == 'subtitle' else 'default_id') else ''), item['id'])
        index = self.preset.findData(self.selected_id)
        if index < 0:
            self.preset.addItem('Preset asal tidak tersedia', self.selected_id)
            index = self.preset.count()-1
        self.preset.setCurrentIndex(index)
        self.preset.blockSignals(False)

    def select_preset(self) -> None:
        item = next((p for p in self.store.data['presets'] if p['id'] == self.preset.currentData()), None)
        self.load_style(dict(item['style'], preset_id=item['id'], preset_version=item['version']) if item else asdict(self.model()()))
        self.log('preset_apply')

    def persist(self, update: bool) -> None:
        self.preview.finish_text(False)
        old = self.selected()
        name, ok = QInputDialog.getText(self, 'Nama preset', 'Nama preset', text=old['name'] if old else '')
        if not ok:
            return
        try:
            item = self.store.save(name, self.style(), self.selected_id if update else None, self.target)
            self.selected_id, self.preset_version = item['id'], item['version']
            self.reference = item['style']['font']
            self.refresh_fonts()
            self.refresh_presets()
            self.changed(record=False)
            self.preset_status.setText('Preset tersimpan; judul proyek tetap perlu divalidasi.')
            self.log('preset_save')
        except Exception as error:
            QMessageBox.warning(self, 'Preset gagal disimpan', str(error))

    def make_default(self) -> None:
        try:
            self.store.set_default(self.selected_id, self.target)
            self.refresh_presets()
            self.preset_status.setText('Default tersimpan untuk proyek baru.')
            self.log('preset_default')
        except Exception as error:
            QMessageBox.warning(self, 'Default gagal disimpan', str(error))

    def remove_preset(self) -> None:
        selected = self.selected()
        if not selected:
            return
        message = f"Hapus preset {selected['name']}? Proyek lama tetap memakai gaya tersimpan."
        if selected['id'] == self.store.data.get('subtitle_default_id' if self.target == 'subtitle' else 'default_id'):
            message += ' Default kembali ke gaya bawaan.'
        if QMessageBox.question(self, 'Hapus preset', message) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(selected['id'])
            self.refresh_presets()
            self.changed(record=False)
            self.log('preset_delete')
        except Exception as error:
            QMessageBox.warning(self, 'Preset gagal dihapus', str(error))
