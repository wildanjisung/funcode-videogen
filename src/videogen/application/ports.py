from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from videogen.domain.subtitle_style import SubtitleStyle

from videogen.domain.models import Cue, MediaInfo, ProcessResult, Word


class Cancelled(Exception):
    """Raised when the user cancels a processing run."""


class MediaProcessor(Protocol):
    def configure_subtitle_font(self, path: Path, postscript_name: str) -> None: ...
    def configure_hook_font(self, path: Path, postscript_name: str) -> None: ...
    def extract_preview(self, source: Path, ass: Path, timestamp: float, output: Path, info: MediaInfo) -> None: ...
    def probe(self, source: Path) -> MediaInfo: ...
    def extract_audio(self, source: Path, destination: Path, info: MediaInfo) -> None: ...
    def render(self, source: Path, ass: Path, output: Path, info: MediaInfo) -> None: ...


class Transcriber(Protocol):
    def transcribe(self, audio: Path) -> list[Word]: ...


class SubtitleWriter(Protocol):
    validation_errors: list[dict]
    def configure_style(self, style: SubtitleStyle, font: Any) -> None: ...
    def cue_bounds(self, info: MediaInfo, cue: Cue) -> dict: ...
    def prepare_cues(self, info: MediaInfo, cues: list[Cue], allow_invalid: bool = False) -> list[Cue]: ...
    def write_ass(self, destination: Path, info: MediaInfo, cues: list[Cue]) -> None: ...
    def write_srt(self, destination: Path, cues: list[Cue]) -> None: ...
    def write_transcript(self, destination: Path, words: list[Word]) -> None: ...


Progress = Callable[[str, str], None]
CheckCancelled = Callable[[], None]


class UserFacingError(Exception):
    """An expected failure that can be shown directly in the desktop UI."""


class EmptyTranscription(UserFacingError):
    """The source audio contained no usable speech segments."""


class UnsupportedMedia(UserFacingError):
    """The selected media does not meet the MVP input contract."""


class DependencyUnavailable(UserFacingError):
    """A required local executable, model, or font is unavailable."""
