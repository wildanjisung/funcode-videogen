import re
from pathlib import Path

from videogen.domain.models import Cue, MediaInfo, Word, max_line_characters


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
    def write_ass(self, destination: Path, info: MediaInfo, cues: list[Cue]) -> None:
        width, height = info.display_width, info.display_height
        font_size = max(18, round(min(height * 0.04, width * 0.065)))
        margin_lr = round(width * 0.08)
        margin_v = round(height * 0.06)
        lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,DejaVu Sans,{font_size},&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,{max(1, round(font_size * 0.06))},0,2,{margin_lr},{margin_lr},{margin_v},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        for cue in cues:
            text = self._wrap_two_lines(_plain_text(cue.text), max_line_characters(info))
            text = text.replace("{", "\\{").replace("}", "\\}")
            lines.append(
                f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},Default,,0,0,0,,{text}"
            )
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")

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
        destination.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")

    def write_transcript(self, destination: Path, words: list[Word]) -> None:
        text = _plain_text(" ".join(word.text for word in words))
        destination.write_text(text + "\n", encoding="utf-8")
