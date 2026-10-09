from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from videogen.application.projects import create_preview, load_project, record_evaluation, render_project, transcribe_project
from videogen.domain.hook import HookLayoutError, HookSpec, layout_hook
from videogen.domain.models import Cue, MediaInfo, Word
from videogen.infrastructure.fonts import SubtitleFont, default_font_path
from videogen.infrastructure.hook_ass import append_hook_ass
from videogen.infrastructure.ffmpeg import FFmpegMediaProcessor
from videogen.infrastructure.subtitles import SubtitleFiles


def portrait() -> MediaInfo:
    return MediaInfo(0, 1, 720, 1280, 720, 1280, 8, 0, 0, "h264", "aac", "yuv420p", "bt709", "1:1")


class FakeMedia:
    def probe(self, _source: Path) -> MediaInfo:
        return portrait()

    def extract_audio(self, _source: Path, destination: Path, _info: MediaInfo) -> None:
        destination.write_bytes(b"audio")

    def render(self, _source: Path, _ass: Path, output: Path, _info: MediaInfo) -> None:
        output.write_bytes(b"rendered-video")


class FakeTranscriber:
    def transcribe(self, _audio: Path) -> list[Word]:
        return [Word("one", 0.1, 0.4), Word("job", 0.5, 0.9), Word("covers", 1, 1.4)]


class MVP2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qt_app = QApplication.instance() or QApplication(["videogen-tests", "-platform", "offscreen"])
        cls.font = SubtitleFont(default_font_path())
        cls.writer = SubtitleFiles(cls.font)

    def test_hook_auto_and_manual_layout_stay_inside_bounds(self) -> None:
        info = portrait()
        auto = layout_hook(HookSpec("One job covers two years. But that's not the real cost."), info, self.font)
        self.assertIsNotNone(auto)
        assert auto is not None
        self.assertLessEqual(len(auto.lines), 3)
        self.assertGreaterEqual(auto.font_size, max(18, int(info.display_height * .022)))
        for line in auto.lines:
            self.assertLessEqual(line.width, info.display_width * .84 + 1)
            self.assertGreaterEqual(line.y, info.display_height * .12)
            self.assertLessEqual(line.y + line.height, info.display_height)
        manual = layout_hook(HookSpec("ONE JOB COVERS\nTWO YEARS", manual=True), info, self.font)
        self.assertEqual([line.text for line in manual.lines], ["ONE JOB COVERS", "TWO YEARS"])

    def test_hook_rejects_invalid_manual_rows_and_oversized_paste(self) -> None:
        with self.assertRaises(HookLayoutError):
            layout_hook(HookSpec("ONE\n\nTWO", manual=True), portrait(), self.font)
        with self.assertRaises(HookLayoutError):
            layout_hook(HookSpec("x" * 501), portrait(), self.font)

    def test_ass_has_rounded_panel_drawings_and_escaped_plain_text(self) -> None:
        info = portrait()
        with tempfile.TemporaryDirectory() as directory:
            ass = Path(directory) / "captions.ass"
            self.writer.write_ass(ass, info, [Cue("WIN ONE JOB", 0, 2, (Word("WIN", 0, .5),),
                ((0, "", "WIN"),), 40)])
            layout = append_hook_ass(ass, info, HookSpec("ONE {JOB}"), self.font)
            content = ass.read_text(encoding="utf-8-sig")
        self.assertIsNotNone(layout)
        self.assertIn("Style: Hook,Helvetica Neue", content)
        self.assertIn("\\p1", content)
        self.assertIn("ONE \\{JOB\\}", content)
        self.assertLess(content.index("Style: Hook"), content.index("[Events]"))

    def test_project_transcribe_render_reopen_and_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clip.mp4"
            source.write_bytes(b"source-media")
            project_dir = transcribe_project(source, root / "out", FakeMedia(), FakeTranscriber(), self.writer,
                self.font, lambda *_: None, lambda: None)
            project, words, info = load_project(project_dir)
            self.assertEqual(len(words), 3)
            self.assertEqual(info.subtitle_offset, 0)
            self.assertEqual((project_dir / "transcript.txt").read_text().strip(), "one job covers")
            record_evaluation(project_dir, "", {"check_id": "user_observation", "result": "Revisi catatan"})
            video = render_project(project_dir, {"hook": {"text": "ONE JOB"}}, FakeMedia(), self.writer,
                                   self.font, lambda *_: None, lambda: None)
            self.assertTrue(video.is_file())
            self.assertEqual((video.parent / "hook.txt").read_text().strip(), "ONE JOB")
            diagnostics = [json.loads(line) for line in (project_dir / "diagnostics.jsonl").read_text().splitlines()]
            self.assertTrue(any(row.get("check_id") == "visual_reference" and row["status"] == "pending" for row in diagnostics))
            self.assertTrue(any(row.get("check_id") == "user_observation" and row["status"] == "pending" for row in diagnostics))
            self.assertNotIn("one job covers", (project_dir / "diagnostics.jsonl").read_text())

    def test_source_hash_mismatch_stops_project_load(self) -> None:
        from videogen.application.ports import UserFacingError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clip.mov"
            source.write_bytes(b"initial")
            project = transcribe_project(source, root / "out", FakeMedia(), FakeTranscriber(), self.writer,
                self.font, lambda *_: None, lambda: None)
            source.write_bytes(b"changed")
            with self.assertRaises(UserFacingError):
                load_project(project)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
    def test_ffmpeg_render_and_timestamped_preview_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "synthetic.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=720x1280:r=24:d=3",
                "-f", "lavfi", "-i", "sine=frequency=1000:duration=3", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)], check=True)
            media = FFmpegMediaProcessor(font_path=self.font.path, expected_font=self.font.postscript_name)
            project = transcribe_project(source, root / "out", media, FakeTranscriber(), self.writer,
                self.font, lambda *_: None, lambda: None)
            request = root / "render-request.json"
            request.write_text(json.dumps({"hook": {"text": "A TEST HOOK", "duration": 2}}), encoding="utf-8")
            env = os.environ.copy()
            env["VIDEOGEN_MODEL_PATH"] = str(root / "model-intentionally-unavailable")
            rendered = subprocess.run([sys.executable, "-m", "videogen.worker_main", "--operation", "render",
                "--project", str(project), "--request", str(request), "--log-file", str(root / "worker.log")],
                capture_output=True, text=True, env=env, check=True)
            terminal = next(event for event in (json.loads(line) for line in rendered.stdout.splitlines())
                            if event.get("type") == "completed")
            self.assertEqual(terminal["operation"], "render")
            video = Path(terminal["video"])
            self.assertGreater(video.stat().st_size, 1000)
            preview = root / "preview-active.png"
            create_preview(project, {"hook": {"text": "A TEST HOOK", "duration": 2},
                "timestamp": 0.5, "output": str(preview)}, media, self.writer, self.font, preview, lambda: None)
            self.assertGreater(preview.stat().st_size, 1000)
            after_hook = root / "preview-after-hook.png"
            create_preview(project, {"hook": {"text": "A TEST HOOK", "duration": 1},
                "timestamp": 2.5, "output": str(after_hook)}, media, self.writer, self.font, after_hook, lambda: None)
            no_hook = root / "preview-no-hook.png"
            create_preview(project, {"hook": {"enabled": False}, "timestamp": 2.5,
                "output": str(no_hook)}, media, self.writer, self.font, no_hook, lambda: None)
            self.assertEqual(QImage(str(after_hook)), QImage(str(no_hook)))
            active_no_hook = root / "preview-active-no-hook.png"
            create_preview(project, {"hook": {"enabled": False}, "timestamp": 0.5,
                "output": str(active_no_hook)}, media, self.writer, self.font, active_no_hook, lambda: None)
            self.assertNotEqual(QImage(str(preview)), QImage(str(active_no_hook)))


if __name__ == "__main__":
    unittest.main()
