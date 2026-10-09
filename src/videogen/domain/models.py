from dataclasses import dataclass
import math
from pathlib import Path


@dataclass(frozen=True)
class MediaInfo:
    video_stream_index: int
    audio_stream_index: int
    width: int
    height: int
    display_width: int
    display_height: int
    duration: float
    video_start: float
    audio_start: float
    video_codec: str
    audio_codec: str
    pixel_format: str
    color_transfer: str
    sample_aspect_ratio: str

    @property
    def subtitle_offset(self) -> float:
        return self.audio_start - self.video_start


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    has_word_timing: bool = True


@dataclass(frozen=True)
class Cue:
    text: str
    start: float
    end: float
    words: tuple[Word, ...] = ()
    layout: tuple[tuple[int, str, str], ...] = ()
    font_size: int | None = None


@dataclass(frozen=True)
class ProcessResult:
    video_path: Path
    transcript_path: Path
    srt_path: Path


def validate_words(
    words: list[Word], duration: float | None = None, offset: float = 0.0,
) -> list[Word]:
    valid = [
        word for word in words
        if word.text.strip() and math.isfinite(word.start) and math.isfinite(word.end)
        and word.end > word.start
    ]
    valid.sort(key=lambda word: word.start)

    clamped = [
        Word(
            text=word.text.strip(),
            start=max(0.0, word.start + offset) if duration is not None else word.start,
            end=min(duration, word.end + offset) if duration is not None else word.end,
            has_word_timing=word.has_word_timing,
        )
        for word in valid
        if duration is None or (word.end + offset > 0 and word.start + offset < duration)
    ]
    return [word for word in clamped if word.end > word.start]


def subtitle_font_size(info: MediaInfo) -> int:
    return max(18, round(min(info.display_height * 0.045, info.display_width * 0.08)))


def max_line_characters(info: MediaInfo) -> int:
    font_size = subtitle_font_size(info)
    usable_width = info.display_width * 0.84
    return max(12, math.floor(usable_width / (font_size * 0.55)))


def build_cues(
    words: list[Word],
    duration: float,
    offset: float,
    max_characters: int,
    max_duration: float = 2.5,
    pause: float = 0.65,
    max_words: int = 4,
) -> list[Cue]:
    """Group word timestamps into readable, frame-relative subtitle cues."""
    cues: list[Cue] = []
    current: list[Word] = []
    words = validate_words(words, duration, offset)

    def emit() -> None:
        if not current:
            return
        text = " ".join(word.text for word in current).strip()
        start = current[0].start
        end = max(word.end for word in current)
        if text and end > start:
            cues.append(Cue(text=text, start=start, end=end, words=tuple(current)))
        current.clear()

    for word in words:
        if not word.text.strip() or word.end <= word.start:
            continue
        candidate = " ".join([*(item.text for item in current), word.text]).strip()
        previous = current[-1] if current else None
        current_end = max((item.end for item in current), default=word.start)
        has_pause = previous is not None and word.start - current_end >= pause
        sentence_end = previous is not None and previous.text.rstrip().endswith((".", "?", "!"))
        too_long = bool(current) and len(candidate) > max_characters
        too_long_in_time = bool(current) and max(current_end, word.end) - current[0].start > max_duration
        too_many_words = bool(current) and sum(len(item.text.split()) for item in current) + len(word.text.split()) > max_words

        # Keep overlapping speech in one cue; splitting it would stack captions or
        # truncate a still-active word. Layout handles this exceptional larger cue.
        overlaps = bool(current) and word.start < current_end
        if current and not overlaps and (has_pause or sentence_end or too_long or too_long_in_time or too_many_words):
            emit()
        current.append(word)

    emit()
    return cues
