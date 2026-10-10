"""A reproducible local proof run; evidence and tolerances are saved before judging."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import traceback

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from videogen.application.editor_context import editor_context
from videogen.application.projects import file_sha256
from videogen.application.ports import Cancelled
from videogen.infrastructure.ass_overlay import ASSOverlay
from videogen.infrastructure.ffmpeg import FFmpegMediaProcessor
from videogen.infrastructure.libopenshot_player import LibOpenShotPlayback
from videogen.infrastructure.mvp3_diagnostics import MVP3RunLog
from videogen.presentation.hook_preview import HookPreview


TOLERANCES = {"schema_version": 1, "overlay_mean_error_8bit": 2.0,
    "overlay_fraction_error_above_16": .005, "seek_error_frames": 1,
    "pause_error_frames": 0, "clock_error_seconds": .1, "clock_sample_seconds": 3.0}


def progress(percent, stage):
    print(json.dumps({"type": "progress", "percent": percent, "stage": stage}), flush=True)


def pixels(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4)[:, :, :3].copy()


def wait(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def run(project, request, output, native=True):
    report = MVP3RunLog(output)
    report._write_manifest({"criteria": TOLERANCES, "request_snapshot": {
        "edit_revision": request.get("edit_revision"), "timeline": request.get("timeline")},
        "project_path": str(project), "qt_platform": "offscreen"})
    player, overlay = None, None
    failures = 0
    try:
        progress(5, "Memvalidasi snapshot")
        context = editor_context(project, request)
        ass = output / "captions.ass"
        context.write_ass(ass)
        report._write_manifest({"source_info": context.source_info.__dict__, "output_duration": context.info.duration,
            "source_sha256": file_sha256(context.source), "ass_sha256": file_sha256(ass),
            "subtitle_font_sha256": file_sha256(context.subtitle_font.path), "hook_font_sha256": file_sha256(context.hook_font.path)})
        overlay = ASSOverlay(ass, [context.subtitle_font.path, context.hook_font.path], context.info.display_width, context.info.display_height)
        with tempfile.TemporaryDirectory(prefix="videogen-diagnostic-fonts-") as temp:
            fonts = Path(temp)
            for index, font in enumerate({context.subtitle_font.path, context.hook_font.path}):
                (fonts / f"{index}{font.suffix}").write_bytes(font.read_bytes())
            times = sorted({min(context.info.duration-.01, .1), *(min(context.info.duration-.01, (cue.start+cue.end)/2)
                for cue in context.cues[::max(1, len(context.cues)//3)][:3])})
            for index, timestamp in enumerate(times):
                progress(10 + round(45*index/max(1, len(times))), "Membandingkan overlay dengan FFmpeg")
                black = QImage(context.info.display_width, context.info.display_height, QImage.Format.Format_ARGB32)
                black.fill(QColor("black"))
                composed = overlay.compose(black, timestamp)
                actual = output / f"overlay-{index}-libass.png"
                expected = output / f"overlay-{index}-ffmpeg.png"
                composed.save(str(actual))
                escaped = FFmpegMediaProcessor._filter_path
                filt = f"setpts=PTS+{timestamp:.9f}/TB,ass=filename='{escaped(ass)}':fontsdir='{escaped(fonts)}'"
                command = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"color=c=black:s={black.width()}x{black.height()}:r=1000", "-vf", filt,
                    "-frames:v", "1", "-threads", "1", "-update", "1", "-y", str(expected)]
                subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
                reference = QImage(str(expected))
                difference = np.abs(pixels(composed).astype(np.int16) - pixels(reference).astype(np.int16))
                mean = float(difference.mean())
                fraction = float((difference.max(axis=2) > 16).mean())
                status = "passed" if mean <= TOLERANCES["overlay_mean_error_8bit"] and fraction <= TOLERANCES["overlay_fraction_error_above_16"] else "failed"
                failures += status == "failed"
                report.evaluate(f"overlay_parity_{index}", status, timestamp=timestamp,
                    measured={"mean_error_8bit": mean, "fraction_error_above_16": fraction},
                    evidence=[str(actual), str(expected)], limitation="Black-frame ASS raster parity; source color/HDR and live frame-clock correlation are separate checks.")
        if native:
            progress(65, "Memeriksa playback / pause / seek")
            surface = HookPreview()
            surface.resize(480, 640)
            frames = []
            surface.framePresented.connect(frames.append)
            player = LibOpenShotPlayback(surface)
            metadata = player.open(context.source, context.edit)
            report.update_engine(version=player.openshot.GetVersion().ToString(), metadata=metadata)
            surface.frame_clock = player.position_seconds
            surface.frame_compositor = overlay.compose
            player.seek_seconds(0)
            started = time.monotonic()
            player.play()
            sample = min(TOLERANCES["clock_sample_seconds"], max(.1, context.info.duration-.2))
            wait(round(sample*1000))
            wall = time.monotonic()-started
            position = player.position_seconds()
            player.pause()
            wait(300)
            paused = player.position_seconds()
            fps = metadata["fps"]
            engine_error = str(player.player.GetError()) if hasattr(player.player, "GetError") else "unknown"
            if not frames:
                report.evaluate("native_runtime", "blocked", measured={"frames": 0, "engine_error": engine_error},
                    limitation="No frame callbacks; desktop/audio-session access must be checked before attributing failure to video code.")
            else:
                report.evaluate("native_frame_delivery", "passed", measured={"frames": len(frames), "position_seconds": position})
                status = "passed" if abs(paused-position) <= 1e-9 else "failed"
                failures += status == "failed"
                report.evaluate("native_pause", status, measured={"before": position, "after": paused})
                # Exclude first-frame startup latency from a second steady interval.
                player.seek_seconds(0)
                player.play()
                wait(300)
                start_pos, start_wall = player.position_seconds(), time.monotonic()
                steady_sample = min(sample, max(.1, context.info.duration-start_pos-.1))
                wait(round(steady_sample*1000))
                elapsed = time.monotonic()-start_wall
                delta = player.position_seconds()-start_pos
                player.pause()
                status = ("passed" if abs(delta-elapsed) <= TOLERANCES["clock_error_seconds"] else "failed") if steady_sample >= .5 else "not_run"
                failures += status == "failed"
                report.evaluate("native_clock_rate", status, measured={"wall_seconds": elapsed, "playhead_delta_seconds": delta},
                    limitation="Clock rate alone does not establish physical audio-video synchronization.")
                target = min(context.info.duration-.05, context.info.duration/2)
                player.seek_seconds(target)
                wait(600)
                actual = player.position_seconds()
                status = "passed" if abs(actual-target) <= 1/fps + .001 else "failed"
                failures += status == "failed"
                report.evaluate("native_seek", status, measured={"requested": target, "actual": actual, "fps": fps})
            report.evaluate("frame_clock_correlation", "pending", limitation="QtPlayer delivers QImage without frame PTS; callback samples player.Position. Need source-frame identity evidence on a visible desktop.")
            report.evaluate("physical_audio_video_sync", "pending", limitation="Requires synchronized captured sound/image; device initialization and clock rate do not prove this.")
        for check_id, limitation in (
            ("whisper_word_onset_200ms", "Requires labeled audible word onsets; transcript timestamp validity does not prove onset accuracy."),
            ("visible_desktop_usability", "Requires user evaluation of dragging, canvas size, and styling on visible desktop."),
            ("long_video_hdr_rotation", "Performance and source display parity need representative long/HDR/rotated sources."),
            ("clean_host_native_rebuild", "Current local native installation works; a fresh-machine rebuild has not been validated."),
            ("complete_cancel_crash_recovery", "Full cancellation and crash-recovery matrix has not been exercised."),
        ):
            report.evaluate(check_id, "pending", limitation=limitation)
        progress(100, "Diagnostik selesai")
        report.finish("failed" if failures else "completed", failed_checks=failures)
        return 1 if failures else 0
    except Cancelled:
        report.finish("cancelled")
        return 2
    except Exception as error:
        report.evaluate("diagnostic_run", "failed", error_message=str(error), traceback=traceback.format_exc())
        report.finish("failed")
        return 1
    finally:
        if player:
            player.close()
        if overlay:
            overlay.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-native", action="store_true")
    args = parser.parse_args()
    if os.name == "posix":
        os.setsid()
    def cancel(*_args):
        raise Cancelled("Diagnostik dibatalkan.")
    signal.signal(signal.SIGTERM, cancel)
    app = QApplication.instance() or QApplication(["videogen-diagnostics", "-platform", "offscreen"])
    return run(args.project, json.loads(args.request.read_text()), args.output, native=not args.no_native)


if __name__ == "__main__":
    raise SystemExit(main())
