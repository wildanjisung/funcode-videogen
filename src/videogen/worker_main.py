import argparse
import json
import logging
import os
import signal
import sys
import traceback
import threading
from pathlib import Path

from videogen.application.ports import Cancelled, UserFacingError
from videogen.application.projects import create_preview, render_project, transcribe_project
from videogen.application.projects import _append_event
from videogen.infrastructure.ffmpeg import FFmpegMediaProcessor, request_cancel, reset_cancel
from videogen.infrastructure.logging_config import configure_logging, default_log_path
from videogen.infrastructure.fonts import SubtitleFont, default_font_path
from videogen.infrastructure.subtitles import SubtitleFiles
from videogen.infrastructure.whisper import FasterWhisperTranscriber
from videogen.infrastructure.paths import default_model_path


def send(kind: str, **payload: object) -> None:
    print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=("transcribe", "render", "preview", "playback"), default="transcribe")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--log-file", type=Path, default=default_log_path())
    parser.add_argument("--cancel-file", type=Path)
    args = parser.parse_args()
    try:
        configure_logging(args.log_file)
    except OSError as error:
        print(f"Cannot create application log at {args.log_file}: {error}", file=sys.stderr, flush=True)
        send(
            "failed",
            message=f"Folder log tidak dapat ditulis. Periksa izin folder: {args.log_file.parent}",
            log_path=str(args.log_file),
        )
        return 1
    logger = logging.getLogger(__name__)

    if sys.platform.startswith("linux"):
        os.setsid()
    signal.signal(signal.SIGTERM, request_cancel)
    signal.signal(signal.SIGINT, request_cancel)
    reset_cancel()
    if args.cancel_file:
        def watch_cancel() -> None:
            from videogen.infrastructure.ffmpeg import _CANCELLED
            while not _CANCELLED.wait(.15):
                if args.cancel_file.exists():
                    request_cancel(0, None)
        threading.Thread(target=watch_cancel, daemon=True).start()
    logger.info("Operation started: operation=%s", args.operation)
    send("ready")

    model_path = default_model_path()
    def check_cancelled() -> None:
        if _cancel_requested():
            raise Cancelled("Proses dibatalkan.")

    try:
        FFmpegMediaProcessor.check_environment()
        if args.operation == "playback":
            if args.source is None or args.output is None:
                raise UserFacingError("Playback memerlukan sumber dan file hasil.")
            media = FFmpegMediaProcessor()
            media.progress = lambda stage, message, percent=None, measurement=None: send(
                "stage", stage=stage, message=message, percent=percent, measurement=measurement)
            info = media.probe(args.source)
            media.create_playback(args.source, args.output, info)
            send("completed", operation="playback", video=str(args.output))
            return 0
        font = SubtitleFont(default_font_path())
        media = FFmpegMediaProcessor(font_path=font.path, expected_font=font.postscript_name)
        subtitles = SubtitleFiles(font)
        subtitles.check_cancelled = check_cancelled
        check_cancelled()
        def report_progress(stage: str, message: str, percent=None, measurement=None) -> None:
            logger.info("Progress stage=%s percent=%s measurement=%s", stage, percent, measurement)
            send("stage", stage=stage, message=message, percent=percent, measurement=measurement)
            if args.operation == "render" and args.project:
                _append_event(args.project, operation="progress", status="running", stage=stage,
                              percent=percent, measurement=measurement, job_id=args.request.stem if args.request else None)
        media.progress = report_progress

        if args.operation == "transcribe":
            if args.source is None or args.output is None:
                raise UserFacingError("Operasi transkripsi memerlukan sumber dan folder hasil.")
            logger.info("Stage started: load transcription model")
            send("stage", stage="model", message="Memuat model transkripsi")
            transcriber = FasterWhisperTranscriber(model_path, cpu_threads=min(4, os.cpu_count() or 1))
            transcriber.progress = report_progress
            transcriber.check_cancelled = check_cancelled
            project = transcribe_project(args.source, args.output, media, transcriber, subtitles, font,
                                         report_progress, check_cancelled)
            send("completed", operation="transcribe", project=str(project),
                 transcript=str(project / "transcript.txt"), words=str(project / "words.json"))
            logger.info("Transcription completed: project_id=%s", project.name)
        else:
            if args.project is None or args.request is None:
                raise UserFacingError("Operasi render/preview memerlukan proyek dan request JSON.")
            request = json.loads(args.request.read_text(encoding="utf-8"))
            if args.operation == "render":
                video = render_project(args.project, request, media, subtitles, font, report_progress, check_cancelled)
                send("completed", operation="render", video=str(video), revision=str(video.parent))
            else:
                output = Path(request["output"])
                preview, hook_lines, hook_end = create_preview(args.project, request, media, subtitles, font, output, check_cancelled)
                send("completed", operation="preview", preview=str(preview), hook_lines=hook_lines,
                     hook_end=hook_end, request_id=request.get("request_id"))
        logger.info("Operation completed: operation=%s", args.operation)
        return 0
    except Cancelled:
        logger.info("Operation cancelled: operation=%s", args.operation)
        if _record_project_event(args, "cancelled"):
            send("failed", operation=args.operation, message="Proses dibatalkan, tetapi diagnostics.jsonl gagal ditulis.")
            return 1
        send("cancelled", operation=args.operation)
        return 130
    except UserFacingError as error:
        logger.exception("Processing failed: source=%s", args.source)
        diagnostics_failed = _record_project_event(args, "failed", type(error).__name__, str(error))
        suffix = "\nProject diagnostics.jsonl gagal ditulis." if diagnostics_failed else ""
        send("failed", operation=args.operation, error_type=type(error).__name__,
             traceback=traceback.format_exc()[-12000:], cue_timestamp=getattr(error, "cue_timestamp", None),
             message=f"{error}{suffix}\nLog: {args.log_file}", log_path=str(args.log_file))
        return 1
    except Exception as error:
        logger.exception("Unhandled worker error: source=%s", args.source)
        diagnostics_failed = _record_project_event(args, "failed", "UnhandledError")
        suffix = " Project diagnostics.jsonl gagal ditulis." if diagnostics_failed else ""
        send("failed", operation=args.operation, error_type=type(error).__name__,
             traceback=traceback.format_exc()[-12000:],
             message=f"Pemrosesan gagal.{suffix} Lihat log: {args.log_file}", log_path=str(args.log_file))
        return 1


def _cancel_requested() -> bool:
    from videogen.infrastructure.ffmpeg import _CANCELLED

    return _CANCELLED.is_set()


def _request_id(path: Path | None) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("request_id") if path else None
    except (OSError, json.JSONDecodeError):
        return None


def _record_project_event(args: argparse.Namespace, status: str, error_type: str | None = None, reason: str | None = None) -> bool:
    if args.operation not in {"render", "preview"} or not args.project or not args.project.is_dir():
        return False
    try:
        details = {"request_id": _request_id(args.request), "check_id": "preview_render_match"} if args.operation == "preview" else {}
        if error_type:
            details["error_type"] = error_type
        if reason:
            details["validation_reason"] = reason[:500]
        if args.request:
            try:
                request = json.loads(args.request.read_text(encoding="utf-8"))
                style = request.get("hook_style") or {}
                keys = ("schema_version", "width_fraction", "size_fraction", "auto_size", "padding_x", "padding_y", "line_gap", "radius_fraction", "top_fraction", "preset_id", "preset_version", "center_fraction", "alignment", "text_color", "background_color", "background_enabled")
                details["hook_style"] = {k: style[k] for k in keys if k in style}
                subtitle_style = dict(request.get("subtitle_style") or {})
                subtitle_style.pop("font", None)
                details["subtitle_style"] = subtitle_style
                details["editor_target"] = request.get("editor_target")
                details["style_session_id"] = request.get("style_session_id")
                details["style_example"] = bool(request.get("style_example"))
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        _append_event(args.project, operation=args.operation, status=status, **details)
        return False
    except OSError:
        logger.exception("Failed to record operation in project diagnostics")
        return True


if __name__ == "__main__":
    raise SystemExit(main())
