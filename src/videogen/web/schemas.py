"""Editable values only; paths and font references stay under server ownership."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HookPatch(Input):
    text: str = Field(default="", max_length=500)
    enabled: bool = True
    manual: bool = False
    duration: float = Field(default=5, gt=0, le=86400)
    full_video: bool = False


class StylePatch(Input):
    width_fraction: float = .84
    size_fraction: float | None = None
    top_fraction: float = .15
    center_fraction: float = .5
    alignment: Literal["left", "center", "right"] = "center"
    text_color: str = "#000000"
    background_color: str = "#FFFFFF"
    background_enabled: bool = True
    auto_size: bool = False


class SubtitlePatch(StylePatch):
    active_word_color: str = "#FFFF00"
    outline_color: str = "#101010"
    outline_fraction: float = .025


class DraftPatch(Input):
    version: int = Field(ge=0)
    hook: HookPatch = Field(default_factory=HookPatch)
    hook_style: StylePatch = Field(default_factory=StylePatch)
    subtitle_style: SubtitlePatch = Field(default_factory=SubtitlePatch)


class SnapshotInput(Input):
    version: int = Field(ge=0)


class PreviewInput(SnapshotInput):
    timestamp: float = Field(default=0, ge=0)


class RenderInput(SnapshotInput):
    preview_job_id: str
