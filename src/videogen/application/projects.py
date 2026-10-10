from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import uuid

from videogen.application.ports import Cancelled, CheckCancelled, DependencyUnavailable, EmptyTranscription, MediaProcessor, Progress, SubtitleWriter, Transcriber, UserFacingError
from videogen.domain.hook import HookSpec, HookStyle
from videogen.domain.subtitle_style import SubtitleStyle
from videogen.domain.models import MediaInfo, Word, build_cues, max_line_characters, validate_words
from videogen.infrastructure.fonts import SubtitleFont
from videogen.infrastructure.hook_ass import append_hook_ass

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 1


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_project(path: Path) -> tuple[dict, list[Word], MediaInfo]:
    path = path.expanduser().resolve()
    try:
        project = json.loads((path / "project.json").read_text(encoding="utf-8"))
        if project.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("schema version")
        source = Path(project["source_path"])
        if not source.is_file() or file_sha256(source) != project["source_sha256"]:
            raise UserFacingError("Sumber proyek hilang atau berubah. Transkripsikan sumber kembali.")
        payload = json.loads((path / "media.json").read_text(encoding="utf-8"))
        info = MediaInfo(**payload)
        words_data = json.loads((path / "words.json").read_text(encoding="utf-8"))
        loaded_words = [Word(**item) for item in words_data]
        words = validate_words(loaded_words)
        if not words or len(words) != len(loaded_words):
            raise ValueError("missing word timings")
        return project, words, info
    except UserFacingError:
        raise
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise UserFacingError("Proyek rusak atau versinya tidak didukung.") from error


def _append_event(project_dir: Path, *, operation: str, status: str, **details: object) -> None:
    event = {"time_utc": datetime.now(timezone.utc).isoformat(), "operation": operation, "status": status, **details}
    with (project_dir / "diagnostics.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(event, ensure_ascii=False) + "\n")


def transcribe_project(
    source: Path, output_dir: Path, media: MediaProcessor, transcriber: Transcriber,
    subtitles: SubtitleWriter, font: SubtitleFont, progress: Progress, check_cancelled: CheckCancelled,
) -> Path:
    source = source.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in {".mp4", ".mov"}:
        raise UserFacingError("Pilih file video MP4 atau MOV yang tersedia.")
    if not os.access(output_dir, os.W_OK):
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise UserFacingError("Folder hasil tidak dapat dibuat atau ditulis.") from error
    from videogen.application.hook_presets import HookPresets
    presets = HookPresets()
    initial_style = presets.default_style()
    initial_subtitle_style = presets.default_style("subtitle")
    _subtitle_context({"subtitle_style": initial_subtitle_style}, font, media, subtitles)
    info = media.probe(source)
    project_id = uuid.uuid4().hex[:10]
    name = f"{source.stem}_project_{project_id}"
    final_dir = output_dir / name
    staging = output_dir / f".{name}.tmp"
    staging.mkdir()
    try:
        source_hash_before = file_sha256(source)
        check_cancelled()
        audio = staging / "audio.wav"
        progress("audio", "Mengekstrak audio")
        media.extract_audio(source, audio, info)
        check_cancelled()
        progress("transcription", "Mentranskripsikan video")
        words = validate_words(transcriber.transcribe(audio))
        if not words:
            raise EmptyTranscription("Ucapan tidak terdeteksi pada video ini.")
        progress("validation", "Memvalidasi semua cue subtitle")
        # Validate layout early, but preserve unclipped audio-relative timings.
        cues = build_cues(words, info.duration, info.subtitle_offset, min(24, max_line_characters(info)))
        cues = subtitles.prepare_cues(info, cues, allow_invalid=True)
        if not cues:
            raise EmptyTranscription("Transkrip tidak menghasilkan subtitle yang valid.")
        (staging / "transcript.txt").write_text(" ".join(word.text for word in words).strip() + "\n", encoding="utf-8")
        (staging / "words.json").write_text(json.dumps([asdict(word) for word in words], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "media.json").write_text(json.dumps(asdict(info), indent=2) + "\n", encoding="utf-8")
        source_hash = file_sha256(source)
        if source_hash != source_hash_before:
            raise UserFacingError("Sumber video berubah saat transkripsi. Pilih kembali file yang stabil.")
        project = {
            "schema_version": SCHEMA_VERSION, "project_id": project_id, "source_path": str(source),
            "source_sha256": source_hash, "source_name": source.name, "duration": info.duration,
            "subtitle_config": {"audio_video_offset": info.subtitle_offset, "cue_max_duration": 2.5,
                "cue_max_words": 4, "subtitle_position_fraction": 0.74, "font_family": "Helvetica Neue",
                "font_weight": 700, "font_size_formula": "max(18, round(min(0.045*H, 0.08*W)))",
                "text_color": "#FFFFFF", "active_word_color": "#FFFF00", "outline_color": "#101010",
                "outline_fraction": 0.025, "subtitle_style_version": 1},
            "font": {"family": "Helvetica Neue", "postscript_name": font.postscript_name, "sha256": file_sha256(font.path)},
            "transcript_file": "transcript.txt", "words_file": "words.json", "media_file": "media.json",
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        atomic_json(staging / "project.json", project)
        (staging / "draft.json").write_text(json.dumps({"hook": {"text": "", "enabled": True,
            "manual": False, "duration": 5.0, "full_video": False, "top_fraction": initial_style["top_fraction"]}, "hook_style": initial_style, "subtitle_style": initial_subtitle_style}, indent=2) + "\n", encoding="utf-8")
        (staging / "diagnostics.jsonl").write_text("", encoding="utf-8")
        (staging / "evaluation.json").write_text("{}\n", encoding="utf-8")
        _append_event(staging, operation="transcribe", status="pending", check_id="whisper_word_onset",
                      target_error_ms=200, measured_error_ms=None, method="independent annotation required")
        for label, index in (("awal", 0), ("tengah", len(words) // 2), ("akhir", len(words) - 1)):
            word = words[index]
            _append_event(staging, operation="timestamp_sample", status="pending", sample=label,
                          word_index=index, predicted_start_audio_seconds=word.start,
                          predicted_end_audio_seconds=word.end, has_word_timing=word.has_word_timing,
                          actual_onset_seconds=None, signed_error_ms=None, absolute_error_ms=None)
        check_cancelled()
        audio.unlink(missing_ok=True)
        staging.rename(final_dir)
        logger.info("Project transcribed: project_id=%s", project_id)
        return final_dir
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def save_draft(project_dir: Path, draft: dict) -> None:
    atomic_json(project_dir / "draft.json", draft)


def normalize_draft(project_dir: Path, draft: dict) -> dict:
    """User authorized replacing legacy editing policy, not source or words."""
    result = dict(draft)
    hook = result.get("hook", result)
    original = result.get("hook_style")
    result["hook_style"] = asdict(HookStyle.from_dict(original or {"top_fraction": hook.get("top_fraction", .15)}))
    result["subtitle_style"] = asdict(SubtitleStyle.from_dict(result.get("subtitle_style")))
    if "hook" not in result:
        result["hook"] = dict(hook)
    if result != draft:
        save_draft(project_dir, result)
        _append_event(project_dir, operation="normalize_draft", status="completed",
                      from_version=(original or {}).get("schema_version", 1), to_version=3,
                      layout_policy="fixed_size_clipping", subtitle_scope="whole_video")
    return result


def _subtitle_context(request, font, media, subtitles):
    from videogen.application.hook_presets import resolve_style_font, font_reference
    style = SubtitleStyle.from_dict(request.get("subtitle_style"))
    actual = resolve_style_font(style, font)
    subtitles.configure_style(style, actual)
    media.configure_subtitle_font(actual.path, actual.postscript_name)
    return style, font_reference(actual)


def _subtitle_event(style, reference, info, cues, subtitles):
    bounds = [dict(subtitles.cue_bounds(info, cue), start=cue.start, end=cue.end) for cue in cues]
    clipped = sum(b["x"] < 0 or b["y"] < 0 or b["x"]+b["width"] > info.display_width or b["y"]+b["height"] > info.display_height for b in bounds)
    values = asdict(style)
    values.pop("font", None)
    return {"subtitle_style": values, "subtitle_font": reference, "subtitle_scope": "whole_video", "subtitle_anchor": "center",
            "cue_count": len(cues), "frame_clipped_cue_count": clipped, "word_intervals_policy": "preserved", "validation_errors": subtitles.validation_errors}


def record_evaluation(project_dir: Path, revision_id: str, record: dict) -> None:
    project, _, _ = load_project(project_dir)
    check_id = str(record.get("check_id", "user_observation"))[:80]
    if not check_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in check_id):
        raise UserFacingError("ID evaluasi hanya boleh berisi huruf, angka, _ atau -.")
    status = record.get("status", "pending")
    if status not in {"pending", "passed", "failed", "inconclusive"}:
        raise UserFacingError("Status evaluasi tidak dikenal.")
    record = {"project_id": project["project_id"], "revision_id": revision_id or None,
              "check_id": check_id, "status": status, "method": str(record.get("method", "manual"))[:500],
              "result": str(record.get("result", ""))[:2000], "evidence": str(record.get("evidence", ""))[:1000],
              "time_utc": datetime.now(timezone.utc).isoformat()}
    _append_event(project_dir, operation="evaluation", status=status,
                  revision_id=record["revision_id"], check_id=check_id)
    path = project_dir / "evaluation.json"
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        previous = {}
    previous.setdefault("records", []).append(record)
    atomic_json(path, previous)


def _validate_render_context(project_dir: Path, media: MediaProcessor, font: SubtitleFont):
    project, words, stored_info = load_project(project_dir)
    current_info = media.probe(Path(project["source_path"]))
    if asdict(current_info) != asdict(stored_info):
        raise UserFacingError("Metadata sumber berubah; transkripsikan sumber kembali.")
    return project, words, current_info


def _hook_context(request: dict, font: SubtitleFont, media: MediaProcessor):
    from videogen.application.hook_presets import resolve_style_font, font_reference
    try:
        style = HookStyle.from_dict(request.get("hook_style")) if request.get("hook_style") is not None else None
    except ValueError as error:
        raise UserFacingError(str(error)) from error
    hook_font = resolve_style_font(style, font) if style and request.get("hook", {}).get("enabled", True) else font
    if hasattr(media, "configure_hook_font"):
        media.configure_hook_font(hook_font.path, hook_font.postscript_name)
    return style, hook_font, font_reference(hook_font)


def _style_event(style, reference, layout) -> dict:
    values = asdict(style) if style else asdict(HookStyle())
    values.pop("font", None)
    return {"hook_style": values, "hook_font": reference,
            "hook_font_size": layout.font_size if layout else None,
            "panel_bounds": [{"x": l.x, "y": l.y, "width": l.width, "height": l.height} for l in layout.lines] if layout else []}


def render_project(
    project_dir: Path, request: dict, media: MediaProcessor, subtitles: SubtitleWriter,
    font: SubtitleFont, progress: Progress, check_cancelled: CheckCancelled,
) -> Path:
    project_dir = project_dir.expanduser().resolve()
    project, words, info = _validate_render_context(project_dir, media, font)
    source_info = info
    edited = None
    if request.get("timeline") is not None:
        from videogen.application.editor_context import editor_context
        edited = editor_context(project_dir, request)
        info, words = edited.info, edited.words
    words_hash = file_sha256(project_dir / "words.json")
    if request.get("validated_words_sha256") and request["validated_words_sha256"] != words_hash:
        raise UserFacingError("Timing/transkrip proyek berubah sejak preview. Perbarui preview sebelum render.")
    progress("validation", "Memvalidasi semua cue subtitle")
    subtitle_style, subtitle_font_ref = _subtitle_context(request, font, media, subtitles)
    spec = HookSpec(**request.get("hook", {}))
    style, hook_font, hook_font_ref = _hook_context(request, font, media)
    if edited:
        from videogen.domain.timeline import project_cues
        cues = subtitles.prepare_cues(info, project_cues(words, info))
    else:
        cues = subtitles.prepare_cues(info, build_cues(words, info.duration, info.subtitle_offset,
                                                       min(24, max_line_characters(info))))
    if not cues and not edited:
        raise EmptyTranscription("Transkrip tidak menghasilkan subtitle yang valid.")
    progress("validation", "Semua cue valid; menyiapkan render")
    revision_id = uuid.uuid4().hex[:12]
    revisions = project_dir / "revisions"
    revisions.mkdir(exist_ok=True)
    staging = revisions / f".{revision_id}.tmp"
    final = revisions / revision_id
    staging.mkdir()
    source = Path(project["source_path"])
    try:
        check_cancelled()
        ass = staging / "captions.ass"
        subtitles.write_ass(ass, info, cues)
        hook_layout = append_hook_ass(ass, info, spec, hook_font, style)
        progress("render", "Merender revisi dari video sumber")
        video = staging / f"{source.stem}_subtitled.mp4"
        if edited:
            from videogen.infrastructure.frame_index import frame_boundaries
            boundaries = frame_boundaries(project_dir, project, source_info)
            for segment in edited.edit.segments:
                if any(not any(abs(edge-point) < 1e-7 for point in boundaries) for edge in (segment.start, segment.end)):
                    raise UserFacingError("Batas segmen harus mengikuti timestamp frame sumber. Perbarui potongan melalui editor.")
            media.render_edit(source, ass, video, source_info, edited.edit, boundaries)
        else:
            media.render(source, ass, video, info)
        check_cancelled()
        progress("finalizing", "Menyimpan hasil dan memeriksa revisi")
        if file_sha256(source) != project["source_sha256"]:
            raise UserFacingError("Sumber video berubah saat render. Revisi ini tidak diterbitkan.")
        transcript = staging / f"{source.stem}_subtitled.txt"
        transcript.write_text(edited.transcript + ("\n" if edited.transcript else "") if edited
            else (project_dir / "transcript.txt").read_text(encoding="utf-8"), encoding="utf-8")
        srt = staging / f"{source.stem}_subtitled.srt"
        subtitles.write_srt(srt, cues)
        (staging / "hook.txt").write_text("\n".join(line.text for line in hook_layout.lines) + "\n" if hook_layout else "", encoding="utf-8")
        render_info = {
            "revision_id": revision_id, "source_sha256": project["source_sha256"], "hook": asdict(spec),
            "hook_style": asdict(style) if style else None, "hook_font": hook_font_ref,
            "hook_layout": {"font_size": hook_layout.font_size, "lines": [asdict(line) for line in hook_layout.lines],
                            "start": hook_layout.start, "end": hook_layout.end} if hook_layout else None,
            "subtitle_config": project["subtitle_config"], "font": subtitle_font_ref,
            "subtitle_style": asdict(subtitle_style), "subtitle_scope": "whole_video", "subtitle_anchor": "center", "words_sha256": words_hash,
            "timeline": edited.edit.to_dict() if edited else None,
            "source_duration": source_info.duration, "output_duration": info.duration,
            "partial_word_count": sum(getattr(word, "partial", False) for word in words),
        }
        atomic_json(staging / "render.json", render_info)
        if not video.is_file() or video.stat().st_size == 0 or not all(path.is_file() for path in (transcript, srt)):
            raise UserFacingError("Output revisi tidak lengkap.")
        check_cancelled()
        ass.unlink(missing_ok=True)
        staging.rename(final)
        for check_id in ("visual_reference", "preview_render_match", "face_coverage", "reels_position", "whisper_word_onset", "hook_style_readability", "editor_usability", "preset_portability", "subtitle_global_frame", "progress_feedback", "open_result_folder"):
            _append_event(project_dir, operation="evaluation", status="pending", revision_id=revision_id,
                          check_id=check_id, reason="requires runtime evidence" if check_id != "whisper_word_onset" else "independent word onset annotation required",
                          target_error_ms=200 if check_id == "whisper_word_onset" else None)
        _append_event(project_dir, operation="render", status="completed", revision_id=revision_id,
                      hook_lines=len(hook_layout.lines) if hook_layout else 0,
                      hook_start=0, hook_end=hook_layout.end if hook_layout else None,
                      **_style_event(style, hook_font_ref, hook_layout),
                      **_subtitle_event(subtitle_style, subtitle_font_ref, info, cues, subtitles))
        progress("completed", "Render selesai")
        return final / video.name
    except BaseException as error:
        _append_event(project_dir, operation="render", status="cancelled" if isinstance(error, Cancelled) else "failed",
                      revision_id=revision_id, error_type=type(error).__name__)
        shutil.rmtree(staging, ignore_errors=True)
        raise


def create_preview(
    project_dir: Path, request: dict, media: MediaProcessor, subtitles: SubtitleWriter, font: SubtitleFont,
    output: Path, check_cancelled: CheckCancelled,
) -> tuple[Path, int, float | None]:
    project_dir = project_dir.expanduser().resolve()
    project, words, info = _validate_render_context(project_dir, media, font)
    edited = None
    if request.get("timeline") is not None:
        from videogen.application.editor_context import editor_context
        edited = editor_context(project_dir, request, allow_invalid=True)
        info, words = edited.info, edited.words
    subtitle_style, subtitle_font_ref = _subtitle_context(request, font, media, subtitles)
    timestamp = max(0.0, min(float(request.get("timestamp", 0)), info.duration - 0.01))
    spec = HookSpec(**request.get("hook", {}))
    style, hook_font, hook_font_ref = _hook_context(request, font, media)
    if edited:
        from videogen.domain.timeline import project_cues
        cues = subtitles.prepare_cues(info, project_cues(words, info), allow_invalid=True)
    else:
        cues = subtitles.prepare_cues(info, build_cues(words, info.duration, info.subtitle_offset,
                                                       min(24, max_line_characters(info))), allow_invalid=True)
    temp_dir = output.parent
    temp_dir.mkdir(parents=True, exist_ok=True)
    ass = temp_dir / f".{output.stem}.ass"
    try:
        subtitles.write_ass(ass, info, cues)
        hook_layout = append_hook_ass(ass, info, spec, hook_font, style)
        check_cancelled()
        if edited:
            media.extract_preview_mapped(Path(project["source_path"]), ass, timestamp,
                edited.edit.source_time(timestamp), output, edited.source_info)
        else:
            media.extract_preview(Path(project["source_path"]), ass, timestamp, output, info)
        ass_hash = file_sha256(ass)
        _append_event(project_dir, operation="preview", status="completed",
                      request_id=request.get("request_id"), check_id="preview_render_match",
                      timestamp_seconds=timestamp, ass_sha256=ass_hash, font_sha256=subtitle_font_ref["sha256"], words_sha256=file_sha256(project_dir / "words.json"),
                      hook_lines=len(hook_layout.lines) if hook_layout else 0,
                      example=bool(request.get("style_example")), session_id=request.get("style_session_id"),
                      editor_mode=request.get("editor_mode", "normal"), gesture_state=request.get("gesture_state"),
                      **_style_event(style, hook_font_ref, hook_layout),
                      **_subtitle_event(subtitle_style, subtitle_font_ref, info, cues, subtitles))
        active_cue = next((c for c in cues if c.start <= timestamp < c.end), None)
        sample = active_cue or (cues[0] if cues else None)
        atomic_json(output.with_suffix(".layout.json"), {"subtitle_bounds": subtitles.cue_bounds(info, sample) if sample else None,
                    "subtitle_visible": active_cue is not None, "hook_visible": bool(hook_layout and hook_layout.start <= timestamp < hook_layout.end), "cue_starts": [c.start for c in cues], "all_cues_valid": not subtitles.validation_errors,
                    "validation_errors": subtitles.validation_errors,
                    "timestamp": timestamp, "words_sha256": file_sha256(project_dir / "words.json"), "snapshot_sha256": hashlib.sha256(json.dumps({k:request.get(k) for k in ("hook", "hook_style", "subtitle_style", "timeline")}, sort_keys=True).encode()).hexdigest(),"font_size": hook_layout.font_size if hook_layout else None,
                    "panel_bounds": _style_event(style, hook_font_ref, hook_layout)["panel_bounds"]})
        return output, len(hook_layout.lines) if hook_layout else 0, hook_layout.end if hook_layout else None
    finally:
        ass.unlink(missing_ok=True)

