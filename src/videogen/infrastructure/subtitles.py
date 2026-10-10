import re
import unicodedata
from pathlib import Path

from dataclasses import replace
from videogen.domain.subtitle_style import SubtitleStyle

from videogen.domain.models import Cue, MediaInfo, Word, max_line_characters, subtitle_font_size
from videogen.application.ports import UserFacingError
from videogen.infrastructure.fonts import SubtitleFont, default_font_path


def _ass_time(seconds: float) -> str:
    total = max(0, round(seconds * 100))
    hours, rem = divmod(total, 360000)
    minutes, rem = divmod(rem, 6000)
    whole, centiseconds = divmod(rem, 100)
    return f"{hours}:{minutes:02}:{whole:02}.{centiseconds:02}"


def _srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    whole, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{whole:02},{millis:03}"


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\ufeff", "")).strip()


class SubtitleFiles:
    def __init__(self, font: SubtitleFont | None = None) -> None:
        self._font = font
        self.style = None
        self.validation_errors = []
        self.check_cancelled = lambda: None

    def configure_style(self, style: SubtitleStyle, font: SubtitleFont) -> None:
        style.validate()
        self.style, self._font = style, font

    def style_size(self, info: MediaInfo) -> int:
        return max(1, round(info.display_height * self.style.size_fraction)) if self.style and self.style.size_fraction is not None else subtitle_font_size(info)

    def cue_bounds(self, info: MediaInfo, cue: Cue) -> dict:
        size = cue.font_size or self.style_size(info)
        rows = 1 + sum(separator == r"\N" for _, separator, _ in cue.layout)
        border = size * self.style.outline_fraction
        height = rows * self._font.metrics(size).height() + 2 * border
        width = info.display_width * self.style.width_fraction
        return {"x": info.display_width*self.style.center_fraction-width/2, "y": info.display_height*self.style.top_fraction-height/2, "width": width, "height": height, "font_size": size}

    def prepare_cues(self, info: MediaInfo, cues: list[Cue], allow_invalid: bool = False) -> list[Cue]:
        if self._font is None:
            self._font = SubtitleFont(default_font_path())
        prepared: list[Cue] = []
        self.validation_errors = []
        if self.style is not None:
            size = self.style_size(info)
            width = info.display_width*self.style.width_fraction-2*size*self.style.outline_fraction
            for cue in cues:
                self.check_cancelled()
                self._font.validate_text(_plain_text(cue.text))
                words = cue.words or (Word(cue.text, cue.start, cue.end, False),)
                layout = self._measured_layout(words, size, width)
                if layout is None:
                    error = UserFacingError(f"Subtitle pada {cue.start:.2f} detik tidak muat dua baris. Perbesar lebar atau kecilkan font.")
                    error.cue_timestamp = cue.start
                    if not allow_invalid:
                        raise error
                    self.validation_errors.append({'timestamp': cue.start, 'reason': str(error)})
                    # Provisional overflow is never eligible for Apply/export.
                    layout = tuple((i, ' ' if i else '', _plain_text(w.text)) for i, w in enumerate(words))
                prepared.append(replace(cue, words=words, layout=layout, font_size=size))
            return prepared
        base_size = subtitle_font_size(info)
        for cue in cues:
            self._font.validate_text(_plain_text(cue.text))
            words = cue.words or (Word(cue.text, cue.start, cue.end, False),)
            # An overlapping group is indivisible: retain every word's interval.
            groups: list[list[Word]] = []
            for word in words:
                if groups and word.start < max(item.end for item in groups[-1]):
                    groups[-1].append(word)
                else:
                    groups.append([word])
            current: list[Word] = []
            chunks: list[list[Word]] = []
            width = info.display_width * 0.84 - 2 * max(1, round(base_size * 0.025, 2))
            for group in groups:
                candidate = " ".join(_plain_text(word.text) for word in current + group)
                if current and self._font.width(candidate, base_size) > width:
                    chunks.append(current)
                    current = []
                current.extend(group)
            if current:
                chunks.append(current)
            for chunk in chunks:
                text = " ".join(_plain_text(word.text) for word in chunk)
                for size in range(base_size, 17, -1):
                    border = max(1, round(size * 0.025, 2))
                    layout = self._measured_layout(chunk, size, info.display_width * 0.84 - 2 * border)
                    if layout is not None:
                        rows = 1 + sum(separator == r"\N" for _, separator, _ in layout)
                        height = rows * self._font.metrics(size).height() + 2 * border
                        if height <= info.display_height * 0.52:
                            break
                else:
                    raise UserFacingError(
                        "Subtitle terlalu panjang untuk dua baris pada ukuran minimum 18 piksel. "
                        "Gunakan video dengan frame lebih besar atau transkripsi dengan timestamp kata."
                    )
                prepared.append(Cue(
                    text=text, start=chunk[0].start, end=max(word.end for word in chunk),
                    words=tuple(chunk), layout=layout, font_size=size,
                ))
        if any(previous.end > following.start for previous, following in zip(prepared, prepared[1:])):
            raise UserFacingError("Timing cue subtitle bertumpang tindih setelah penyusunan layout.")
        return prepared

    def _measured_layout(
        self, words: list[Word], size: int, width: float,
    ) -> tuple[tuple[int, str, str], ...] | None:
        assert self._font is not None
        rows: list[list[tuple[int, str]]] = [[]]
        for index, word in enumerate(words):
            for token in _plain_text(word.text).split():
                candidate = " ".join([*(text for _, text in rows[-1]), token])
                if self._font.width(candidate, size) <= width:
                    rows[-1].append((index, token))
                    continue
                if rows[-1]:
                    rows.append([])
                if self._font.width(token, size) <= width:
                    rows[-1].append((index, token))
                else:
                    # Keep combining accents attached when wrapping a long word.
                    glyphs: list[str] = []
                    for char in token:
                        if glyphs and unicodedata.combining(char):
                            glyphs[-1] += char
                        else:
                            glyphs.append(char)
                    fragment = ""
                    for glyph in glyphs:
                        if self._font.width(fragment + glyph, size) > width:
                            if not fragment:
                                return None
                            rows[-1].append((index, fragment))
                            rows.append([])
                            fragment = ""
                            if len(rows) > 2:
                                return None
                        fragment += glyph
                    if fragment:
                        if self._font.width(fragment, size) > width:
                            return None
                        rows[-1].append((index, fragment))
                if len(rows) > 2:
                    return None
        layout: list[tuple[int, str, str]] = []
        for row in rows:
            for position, (index, token) in enumerate(row):
                separator = (r"\N" if layout else "") if position == 0 else " "
                layout.append((index, separator, token))
        return tuple(layout)

    def write_ass(self, destination: Path, info: MediaInfo, cues: list[Cue]) -> None:
        if any(not cue.layout for cue in cues):
            cues = self.prepare_cues(info, cues)
        width, height = info.display_width, info.display_height
        font_size = self.style_size(info)
        style = self.style or SubtitleStyle()
        color = lambda c: c[5:7]+c[3:5]+c[1:3]
        fontname = self._font.postscript_name if self.style else "Helvetica Neue"
        bold = -1 if self._font.raw.weight() >= 600 else 0
        italic = -1 if self._font.raw.style().value else 0
        margin_lr = round(width * 0.08)
        margin_v = round(height * 0.26)
        lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{fontname},{font_size},&H00{color(style.text_color)},&H00{color(style.active_word_color)},&H00{color(style.outline_color)},&H80000000,{bold},{italic},0,0,100,100,0,0,1,{font_size*style.outline_fraction:g},0,2,{margin_lr},{margin_lr},{margin_v},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        event_count = 0
        for cue in cues:
            for start, end, text in self._highlight_events(cue, max_line_characters(info), style.text_color, style.active_word_color):
                event_count += 1
                anchor = {"left": 4, "center": 5, "right": 6}[style.alignment]
                x = width * (style.center_fraction + ({"left": -.5, "center": 0, "right": .5}[style.alignment])*style.width_fraction)
                x += ({"left": 1, "center": 0, "right": -1}[style.alignment])*((cue.font_size or font_size)*style.outline_fraction)
                position = f"{{\\an{anchor}\\pos({x:g},{height * style.top_fraction:g})}}"
                if cue.font_size is not None:
                    position += f"{{\\fs{cue.font_size}\\bord{cue.font_size * style.outline_fraction:g}}}"
                lines.append(
                    f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{position}{text}"
                )
        if cues and not event_count:
            raise UserFacingError("Subtitle tidak memiliki interval yang dapat dirender pada presisi ASS 10 ms.")
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")

    @staticmethod
    def _escape_text(text: str) -> str:
        # User text must not introduce ASS overrides or line-break escapes.
        return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")

    @classmethod
    def _highlight_events(cls, cue: Cue, limit: int, base_color: str = "#FFFFFF", active_color: str = "#FFFF00") -> list[tuple[float, float, str]]:
        bgr = lambda c: c[5:7]+c[3:5]+c[1:3]
        base_tag = "{\\1c&H"+bgr(base_color)+"&}"
        active_tag = "{\\1c&H"+bgr(active_color)+"&}"
        start, end = round(cue.start * 100), round(cue.end * 100)
        if end <= start:
            return []
        if not cue.words:
            text = cls._wrap_two_lines(_plain_text(cue.text), limit)
            text = r"\N".join(cls._escape_text(row) for row in text.split(r"\N"))
            return [(start / 100, end / 100, text)]

        # Decide wrapping before adding colour tags so every event has identical layout.
        tokens: list[tuple[int, str, str]] = [
            (index, separator, cls._escape_text(text)) for index, separator, text in cue.layout
        ]
        row_length, row = 0, 0
        for index, word in enumerate(() if cue.layout else cue.words):
            for token in _plain_text(word.text).split():
                separator = " " if tokens else ""
                if row_length and row_length + len(token) + 1 > limit and row == 0:
                    separator, row_length, row = r"\N", 0, 1
                tokens.append((index, separator, cls._escape_text(token)))
                row_length += len(token) + (1 if row_length else 0)

        timings = [
            (max(start, round(word.start * 100)), min(end, round(word.end * 100)))
            for word in cue.words
        ]
        boundaries = sorted({start, end, *(time for a, b in timings if b > a for time in (a, b))})
        events: list[tuple[float, float, str]] = []
        for a, b in zip(boundaries, boundaries[1:]):
            # If model timings overlap, the latest starting word takes precedence.
            active = max(
                (index for index, (word_start, word_end) in enumerate(timings)
                 if word_start <= a < word_end and cue.words[index].has_word_timing),
                key=lambda index: (timings[index][0], index),
                default=None,
            )
            text = "".join(
                separator + (active_tag + token + base_tag if index == active else token)
                for index, separator, token in tokens
            )
            if events and events[-1][2] == text:
                previous_start, _, _ = events[-1]
                events[-1] = (previous_start, b / 100, text)
            else:
                events.append((a / 100, b / 100, text))
        return events

    @staticmethod
    def _wrap_two_lines(text: str, limit: int) -> str:
        words = text.split()
        rows: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > limit and len(rows) < 1:
                rows.append(current)
                current = word
            else:
                current = candidate
        if current:
            rows.append(current)
        return r"\N".join(rows[:2])

    def write_srt(self, destination: Path, cues: list[Cue]) -> None:
        blocks = [
            f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n{_plain_text(cue.text)}"
            for index, cue in enumerate(cues, start=1)
        ]
        destination.write_text("\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8")

    def write_transcript(self, destination: Path, words: list[Word]) -> None:
        text = _plain_text(" ".join(word.text for word in words))
        destination.write_text(text + "\n", encoding="utf-8")
