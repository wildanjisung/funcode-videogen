"""The exact caption/layout snapshot used by playback and FFmpeg output."""
from dataclasses import dataclass, replace
from pathlib import Path

from videogen.application.hook_presets import resolve_style_font
from videogen.application.projects import load_project
from videogen.domain.hook import HookSpec, HookStyle
from videogen.domain.subtitle_style import SubtitleStyle
from videogen.domain.timeline import TimelineEdit, project_cues, edited_transcript
from videogen.infrastructure.fonts import SubtitleFont, default_font_path
from videogen.infrastructure.hook_ass import append_hook_ass
from videogen.infrastructure.subtitles import SubtitleFiles


@dataclass
class EditorContext:
    source: Path
    source_info: object
    info: object
    edit: TimelineEdit
    words: list
    cues: list
    subtitles: SubtitleFiles
    subtitle_font: SubtitleFont
    hook_font: SubtitleFont
    hook: HookSpec
    hook_style: HookStyle | None

    @property
    def transcript(self):
        return edited_transcript(self.words)

    def write_ass(self, path):
        self.subtitles.write_ass(path, self.info, self.cues)
        return append_hook_ass(path, self.info, self.hook, self.hook_font, self.hook_style)


def editor_context(project_dir, request, *, allow_invalid=False):
    project, original_words, source_info = load_project(project_dir)
    edit = TimelineEdit.from_dict(request.get("timeline"), source_info.duration)
    if not edit.segments:
        raise ValueError("Timeline kosong. Pulihkan segmen sebelum preview atau ekspor.")
    info = replace(source_info, duration=edit.duration, video_start=0.0, audio_start=0.0)
    words = edit.map_words(original_words, source_info.subtitle_offset)
    fallback = SubtitleFont(default_font_path())
    subtitle_style = SubtitleStyle.from_dict(request.get("subtitle_style"))
    subtitle_font = resolve_style_font(subtitle_style, fallback)
    hook_style = HookStyle.from_dict(request["hook_style"]) if request.get("hook_style") is not None else None
    hook_font = resolve_style_font(hook_style, fallback) if hook_style else fallback
    subtitles = SubtitleFiles(subtitle_font)
    subtitles.configure_style(subtitle_style, subtitle_font)
    cues = subtitles.prepare_cues(info, project_cues(words, info), allow_invalid=allow_invalid)
    return EditorContext(Path(project["source_path"]), source_info, info, edit, words, cues,
        subtitles, subtitle_font, hook_font, HookSpec(**request.get("hook", {})), hook_style)
