"""One frame and appearance shared by every subtitle cue."""
from dataclasses import dataclass
import math
import re
from videogen.domain.hook import HookStyle, HookLayoutError


@dataclass(frozen=True)
class SubtitleStyle(HookStyle):
    top_fraction: float = .74  # Vertical centre anchor (hook uses top edge).
    text_color: str = "#FFFFFF"
    background_enabled: bool = False
    active_word_color: str = "#FFFF00"
    outline_color: str = "#101010"
    outline_fraction: float = .025  # Relative to font size.

    def validate(self) -> None:
        super().validate()
        if self.auto_size:
            raise HookLayoutError("Subtitle memakai ukuran tetap.")
        for color in (self.active_word_color, self.outline_color):
            if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise HookLayoutError("Warna subtitle tidak valid.")
        if isinstance(self.outline_fraction, bool) or not isinstance(self.outline_fraction, (int, float)) or not math.isfinite(self.outline_fraction) or not 0 <= self.outline_fraction <= .5:
            raise HookLayoutError("Ketebalan stroke subtitle tidak valid.")
