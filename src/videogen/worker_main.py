import argparse
import json
import logging
import os
import signal
import sys
from pathlib import Path

from videogen.application.ports import Cancelled, UserFacingError
from videogen.application.process_video import ProcessVideo
from videogen.infrastructure.ffmpeg import FFmpegMediaProcessor, request_cancel, reset_cancel
from videogen.infrastructure.logging_config import configure_logging, default_log_path
from videogen.infrastructure.subtitles import SubtitleFiles
from videogen.infrastructure.whisper import FasterWhisperTranscriber


def send(kind: str, **payload: object) -> None:
    print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--log-file", type=Path, default=default_log_path())
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
    logger.info("Processing started: source=%s output=%s", args.source, args.output)
    send("ready")

    model_path = Path(
        os.environ.get(
            "VIDEOGEN_MODEL_PATH",
            Path(__file__).parents[2] / ".cache" / "models" / "small",
        )
    )
    def check_cancelled() -> None:
        if _cancel_requested():
            raise Cancelled("Proses dibatalkan.")

    try:
        FFmpegMediaProcessor.check_environment()
        logger.info("Stage started: load transcription model")
        send("stage", stage="model", message="Memuat model transkripsi")
        transcriber = FasterWhisperTranscriber(model_path, cpu_threads=min(4, os.cpu_count() or 1))
        app = ProcessVideo(
            media=FFmpegMediaProcessor(),
            transcriber=transcriber,
            subtitles=SubtitleFiles(),
            font_path=Path(__file__).parent / "presentation" / "resources" / "DejaVuSans.ttf",
        )
        check_cancelled()
        def report_progress(stage: str, message: str) -> None:
            logger.info("Stage started: %s", stage)
            send("stage", stage=stage, message=message)

        result = app.execute(
            args.source,
            args.output,
            progress=report_progress,
            check_cancelled=check_cancelled,
        )
        send(
            "completed",
            video=str(result.video_path),
            transcript=str(result.transcript_path),
            srt=str(result.srt_path),
        )
        logger.info("Processing completed: output=%s", result.video_path)
        return 0
    except Cancelled:
        logger.info("Processing cancelled: source=%s", args.source)
        send("cancelled")
        return 130
    except UserFacingError as error:
        logger.exception("Processing failed: source=%s", args.source)
        send("failed", message=f"{error}\nLog: {args.log_file}", log_path=str(args.log_file))
        return 1
    except Exception:
        logger.exception("Unhandled worker error: source=%s", args.source)
        send("failed", message=f"Pemrosesan gagal. Lihat log: {args.log_file}", log_path=str(args.log_file))
        return 1


def _cancel_requested() -> bool:
    from videogen.infrastructure.ffmpeg import _CANCELLED

    return _CANCELLED.is_set()


if __name__ == "__main__":
    raise SystemExit(main())
