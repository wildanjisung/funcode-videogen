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


@dataclass(frozen=True)
class Cue:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class ProcessResult:
    video_path: Path
    transcript_path: Path
    srt_path: Path


def validate_words(words: list[Word], duration: float) -> list[Word]:
    valid = [
        word for word in words
        if word.text.strip() and word.end > word.start
    ]
    valid.sort(key=lambda word: (word.start, word.end))

    clamped = [
        Word(
            text=word.text.strip(),
            start=max(0.0, word.start),
            end=min(duration, word.end),
        )
        for word in valid
        if word.end > 0 and word.start < duration
    ]
    return [word for word in clamped if word.end > word.start]


def max_line_characters(info: MediaInfo) -> int:
    font_size = max(18, round(min(info.display_height * 0.04, info.display_width * 0.065)))
    usable_width = info.display_width * 0.84
    return max(12, math.floor(usable_width / (font_size * 0.55)))


def build_cues(
    words: list[Word],
    duration: float,
    offset: float,
    max_characters: int,
    max_duration: float = 6.0,
    pause: float = 0.65,
) -> list[Cue]:
    """Group word timestamps into readable, frame-relative subtitle cues."""
    cues: list[Cue] = []
    current: list[Word] = []

    def emit() -> None:
        if not current:
            return
        text = " ".join(word.text for word in current).strip()
        start = max(0.0, current[0].start + offset)
        end = min(duration, current[-1].end + offset)
        if text and end > start:
            cues.append(Cue(text=text, start=start, end=end))
        current.clear()

    for word in words:
        if not word.text.strip() or word.end <= word.start:
            continue
        candidate = " ".join([*(item.text for item in current), word.text]).strip()
        previous = current[-1] if current else None
        has_pause = previous is not None and word.start - previous.end >= pause
        sentence_end = previous is not None and previous.text.rstrip().endswith((".", "?", "!"))
        too_long = bool(current) and len(candidate) > max_characters
        too_long_in_time = bool(current) and word.end - current[0].start > max_duration

        if current and (has_pause or sentence_end or too_long or too_long_in_time):
            emit()
        current.append(word)

    emit()
    return cues
