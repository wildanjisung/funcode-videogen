from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Protocol

from videogen.domain.models import MediaInfo


class HookLayoutError(ValueError):
    """Hook content or placement cannot fit the configured frame bounds."""


class FontMetrics(Protocol):
    def width(self, text: str, size: int) -> float: ...
    def metrics(self, size: int): ...
    def validate_text(self, text: str) -> None: ...


@dataclass(frozen=True)
class HookStyle:
    schema_version: int = 3
    width_fraction: float = 0.84
    size_fraction: float | None = None
    auto_size: bool = False
    padding_x: float = 0.01
    padding_y: float = 0.005
    line_gap: float = 0.1
    radius_fraction: float | None = None
    top_fraction: float = 0.15
    center_fraction: float = 0.5
    alignment: str = "center"
    text_color: str = "#000000"
    background_color: str = "#FFFFFF"
    background_enabled: bool = True
    font: dict | None = None
    preset_id: str | None = None
    preset_version: int | None = None

    def validate(self) -> None:
        if type(self.schema_version) is not int or self.schema_version not in (1, 2, 3) or not isinstance(self.auto_size, bool):
            raise HookLayoutError("Versi atau mode gaya hook tidak didukung.")
        if self.font is not None:
            required = ("path", "family", "postscript_name", "sha256")
            if not isinstance(self.font, dict) or any(not isinstance(self.font.get(k), str) or not self.font[k] for k in required):
                raise HookLayoutError("Referensi font hook tidak valid; pilih kembali font.")
        if self.alignment not in {"left", "center", "right"} or not isinstance(self.background_enabled, bool):
            raise HookLayoutError("Perataan atau mode latar tidak valid.")
        if any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in (self.text_color, self.background_color)):
            raise HookLayoutError("Warna hook harus berupa warna RGB yang valid.")
        flexible = self.schema_version >= 2
        values = [(self.width_fraction, .01 if flexible else .40, 1 if flexible else .90), (self.padding_x, 0, .03),
                  (self.padding_y, 0, .01), (self.line_gap, 0, .30),
                  (self.top_fraction, -math.inf if flexible else .12, math.inf if flexible else .30),
                  (self.center_fraction, -math.inf, math.inf)]
        if self.size_fraction is not None:
            values.append((self.size_fraction, .0001 if flexible else .022, 1 if flexible else .06))
        if self.radius_fraction is not None:
            values.append((self.radius_fraction, 0, .02))
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi
               for v, lo, hi in values):
            raise HookLayoutError("Nilai gaya hook berada di luar rentang yang diizinkan.")

    @classmethod
    def from_dict(cls, value: dict | None) -> HookStyle:
        try:
            payload = dict(value or {})
            if payload.get("schema_version", 1) < 3:
                payload.update(schema_version=3, auto_size=False)
            result = cls(**payload)
            result.validate()
            return result
        except (TypeError, AttributeError) as error:
            raise HookLayoutError("Data gaya hook tidak valid.") from error


@dataclass(frozen=True)
class HookSpec:
    text: str = ""
    enabled: bool = True
    manual: bool = False
    top_fraction: float = 0.15
    duration: float = 5.0
    full_video: bool = False


@dataclass(frozen=True)
class HookLine:
    text: str
    x: float
    y: float
    width: float
    height: float
    radius: float


@dataclass(frozen=True)
class HookLayout:
    lines: tuple[HookLine, ...]
    font_size: int
    start: float
    end: float
    width: int
    height: int


def layout_hook(spec: HookSpec, info: MediaInfo, font: FontMetrics, style: HookStyle | None = None) -> HookLayout | None:
    explicit_style = style is not None
    style = style or HookStyle(top_fraction=spec.top_fraction)
    style.validate()
    if not spec.enabled:
        return None
    raw = spec.text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        raise HookLayoutError("Isi Hook title atau matikan Tampilkan hook sebelum render.")
    if not spec.full_video and (not math.isfinite(spec.duration) or spec.duration <= 0):
        raise HookLayoutError("Durasi hook harus berupa angka positif.")
    duration = info.duration if spec.full_video else min(spec.duration, info.duration)
    if duration <= 0:
        raise HookLayoutError("Durasi video tidak valid untuk hook.")

    text = raw.upper()
    if len(text) > 500 or len(text.split()) > 80:
        raise HookLayoutError("Hook terlalu panjang untuk diedit. Sisakan judul saja, maksimal 500 karakter.")
    font.validate_text(text)
    width = info.display_width
    height = info.display_height
    max_panel = width * style.width_fraction
    pad_x = width * style.padding_x
    pad_y = height * style.padding_y
    max_text_width = max_panel - 2 * pad_x
    legacy_min = max(18, math.ceil(height * 0.022))
    min_size = 1 if style.schema_version >= 2 else legacy_min
    start_size = max(legacy_min, round(min(height * 0.03, width * 0.06)))

    if style.size_fraction is not None:
        start_size = max(min_size, round(height * style.size_fraction))

    if spec.manual:
        rows = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
        if any(not row for row in rows) or len(rows) > 3:
            raise HookLayoutError("Pemenggalan manual harus berisi satu sampai tiga baris tanpa baris kosong.")
        candidates = [rows]
    else:
        words = re.sub(r"\s+", " ", text).split()
        if not words:
            raise HookLayoutError("Hook title tidak boleh kosong.")
        candidates = []
        for count in range(1, min(3, len(words)) + 1):
            def partitions(at: int, left: int, built: list[str]):
                if left == 1:
                    row = " ".join(words[at:])
                    if row:
                        yield [*built, row]
                    return
                for stop in range(at + 1, len(words) - left + 2):
                    yield from partitions(stop, left - 1, [*built, " ".join(words[at:stop])])
            candidates.extend(partitions(0, count, []))

    metrics = font.metrics(start_size)
    for size in range(start_size, (min_size if style.auto_size else start_size) - 1, -1):
        metrics = font.metrics(size)
        candidates_fitting = []
        for rows in candidates:
            widths = [font.width(row, size) for row in rows]
            if max(widths, default=0) <= max_text_width:
                required_height = len(rows) * metrics.height() + (len(rows) if explicit_style else 1) * 2 * pad_y + (len(rows) - 1) * size * style.line_gap
                if style.schema_version >= 3 or required_height <= (height * (1-style.top_fraction) if style.schema_version == 2 else height * .14):
                    short_last = len(rows) > 1 and len(rows[-1].split()) == 1 and len(rows[-1]) <= 3
                    punctuation = sum(bool(re.search(r"[,.;:!?]$", row)) for row in rows[:-1])
                    balance = max(widths, default=0) - min(widths, default=0)
                    candidates_fitting.append((punctuation, not short_last, -balance, -len(rows), tuple(rows), widths))
        if candidates_fitting:
            chosen = max(candidates_fitting)
            rows, widths = chosen[4], chosen[5]
            block_height = len(rows) * metrics.height() + (len(rows) if explicit_style else 1) * 2 * pad_y + (len(rows) - 1) * size * style.line_gap
            y = (style.top_fraction if explicit_style else spec.top_fraction) * height
            if style.schema_version < 3 and y + block_height > height:
                raise HookLayoutError("Hook tidak muat pada posisi ini; geser ke atas atau pendekkan judul.")
            lines = []
            line_h = metrics.height()
            for index, (row, text_width) in enumerate(zip(rows, widths)):
                panel_w = text_width + 2 * pad_x
                panel_h = line_h + 2 * pad_y
                line_y = y + index * (line_h + 2 * pad_y + size * style.line_gap)
                center = width * style.center_fraction
                panel_x = center - panel_w / 2
                if style.alignment == "left":
                    panel_x = center - max_panel / 2
                elif style.alignment == "right":
                    panel_x = center + max_panel / 2 - panel_w
                if style.schema_version < 3 and (panel_x < -0.01 or panel_x + panel_w > width + .01 or line_y + panel_h > height + .01):
                    raise HookLayoutError("Hook terpotong di tepi frame. Geser kotak atau kurangi ukuran/lebar.")
                lines.append(HookLine(row, panel_x, line_y, panel_w, panel_h, min(size * 0.22 if style.radius_fraction is None else height * style.radius_fraction, panel_h / 2, panel_w / 2)))
            return HookLayout(tuple(lines), size, 0.0, duration, width, height)
    raise HookLayoutError("Hook tidak muat. Pendekkan judul, ubah lebar, atau pilih Otomatis agar muat." if not style.auto_size else "Hook tidak muat pada tiga baris dan ukuran font minimum. Pendekkan judul.")
