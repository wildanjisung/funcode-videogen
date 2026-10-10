import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import asdict
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from videogen.application.projects import SCHEMA_VERSION, file_sha256, render_project
from videogen.application.editor_context import editor_context
from videogen.domain.models import Word, MediaInfo
from videogen.domain.timeline import TimelineEdit, edited_transcript, nearest_boundary, project_cues
from videogen.domain.hook import HookStyle
from videogen.domain.subtitle_style import SubtitleStyle
from videogen.infrastructure.ffmpeg import FFmpegMediaProcessor
from videogen.infrastructure.fonts import SubtitleFont, default_font_path
from videogen.infrastructure.subtitles import SubtitleFiles
from videogen.infrastructure.mvp3_diagnostics import MVP3RunLog
from videogen.presentation.desktop import MainWindow
from videogen.presentation.hook_preview import HookPreview
from videogen.infrastructure.libopenshot_player import LibOpenShotPlayback


class MappingTests(unittest.TestCase):
    def test_split_preserves_word_identity_and_cues(self):
        words = [Word("one", .1, .8), Word("job", 1.2, 1.8)]
        edit = TimelineEdit.from_dict(None, 3)
        split = edit.split(.5)
        self.assertEqual(edit.map_words(words, 0), split.map_words(words, 0))
        self.assertEqual(edited_transcript(split.map_words(words, 0)), "one job")

    def test_removed_middle_clamps_partial_words_and_applies_offset_once(self):
        edit = TimelineEdit.from_dict({"schema_version": 1, "segments": [
            {"id": "a", "start": 0, "end": .5}, {"id": "b", "start": 1, "end": 2}]}, 2)
        mapped = edit.map_words([Word("word", 0, 1), Word("tail", 1.2, 1.5)], .2)
        self.assertEqual([(round(w.start, 3), round(w.end, 3)) for w in mapped], [(.2, .5), (.5, .7), (.9, 1.2)])
        self.assertTrue(mapped[0].partial and mapped[1].partial)
        self.assertEqual(edited_transcript(mapped), "word tail")
        self.assertEqual(edit.source_time(.5), 1)

    def test_order_overlap_and_invalid_numbers_rejected(self):
        for segments in ([{"id": "x", "start": 2, "end": 1}],
            [{"id": "x", "start": 0, "end": 1}, {"id": "y", "start": .5, "end": 2}],
            [{"id": "x", "start": 0, "end": float("nan")}],
            [{"id": "x", "start": False, "end": 1}]):
            with self.assertRaises(ValueError):
                TimelineEdit.from_dict({"schema_version": 1, "segments": segments}, 3)

    def test_vfr_boundaries_and_ties(self):
        boundaries = [0, .02, .08, .12]
        self.assertEqual(nearest_boundary(.03, boundaries), .02)
        self.assertEqual(nearest_boundary(.1, boundaries), .08)


class EditorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["mvp3-tests", "-platform", "offscreen"])
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=320x480:r=25:d=2",
            "-f", "lavfi", "-i", "color=blue:s=320x480:r=25:d=2", "-f", "lavfi", "-i", "sine=frequency=400:duration=4",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-threads", "1", "-c:a", "aac", "-y", str(cls.source)], check=True, capture_output=True)
        cls.info = FFmpegMediaProcessor().probe(cls.source)
        cls.font = SubtitleFont(default_font_path())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.folder = self.root / self._testMethodName
        self.folder.mkdir()
        project = {"schema_version": SCHEMA_VERSION, "project_id": self.folder.name, "source_path": str(self.source),
            "source_sha256": file_sha256(self.source), "duration": self.info.duration,
            "transcript_file": "transcript.txt", "subtitle_config": {}}
        self.request = {"hook": {"enabled": False}, "hook_style": asdict(HookStyle()),
            "subtitle_style": asdict(SubtitleStyle()), "timeline": None}
        for name, payload in (("project.json", project), ("media.json", asdict(self.info)),
            ("words.json", [asdict(Word("keep", .1, .4)), asdict(Word("discard", 1.5, 1.8)), asdict(Word("tail", 3.1, 3.4))]),
            ("draft.json", self.request)):
            (self.folder / name).write_text(json.dumps(payload))
        (self.folder / "transcript.txt").write_text("keep discard tail")

    def test_cut_render_transcript_duration_and_join_frames(self):
        self.request["timeline"] = {"schema_version": 1, "segments": [
            {"id": "first", "start": 0, "end": 1}, {"id": "last", "start": 3, "end": 4}]}
        context = editor_context(self.folder, self.request)
        self.assertEqual(context.transcript, "keep tail")
        self.assertEqual(len(context.cues), 2)
        revision = render_project(self.folder, self.request, FFmpegMediaProcessor(), SubtitleFiles(self.font),
            self.font, lambda *_: None, lambda: None).parent
        video = next(revision.glob("*.mp4"))
        info = FFmpegMediaProcessor().probe(video)
        self.assertAlmostEqual(info.duration, 2, delta=.04)
        self.assertEqual(next(revision.glob("*_subtitled.txt")).read_text().strip(), "keep tail")
        srt = next(revision.glob("*.srt")).read_text()
        self.assertNotIn("discard", srt)
        self.assertIn("00:00:01,100", srt)
        for timestamp, expected in ((.5, "red"), (1.5, "blue")):
            image = self.folder / f"{expected}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(video),
                "-frames:v", "1", "-threads", "1", "-update", "1", str(image)], check=True, capture_output=True)
            pixel = QImage(str(image)).pixelColor(10, 10)
            self.assertGreater(pixel.red() if expected == "red" else pixel.blue(), 200)

    def test_no_speech_segment_exports_empty_caption_files(self):
        self.request["timeline"] = {"schema_version": 1, "segments": [{"id": "silent", "start": 2, "end": 3}]}
        revision = render_project(self.folder, self.request, FFmpegMediaProcessor(), SubtitleFiles(self.font),
            self.font, lambda *_: None, lambda: None).parent
        self.assertEqual(next(revision.glob("*.srt")).read_text(), "")
        self.assertEqual(next(revision.glob("*_subtitled.txt")).read_text(), "")

    def test_vfr_tail_duration_and_frame_count_preserved(self):
        source = self.folder / "vfr.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(self.source), "-vf", "select=not(mod(n\\,3))",
            "-fps_mode", "vfr", "-c:v", "libx264", "-threads", "1", "-c:a", "copy", str(source)], check=True, capture_output=True)
        info = FFmpegMediaProcessor().probe(source)
        project = json.loads((self.folder / "project.json").read_text())
        project.update(source_path=str(source), source_sha256=file_sha256(source), duration=info.duration)
        (self.folder / "project.json").write_text(json.dumps(project))
        (self.folder / "media.json").write_text(json.dumps(asdict(info)))
        self.request["timeline"] = {"schema_version": 1, "segments": [
            {"id": "first", "start": 0, "end": .96}, {"id": "last", "start": 3, "end": 4}]}
        video = render_project(self.folder, self.request, FFmpegMediaProcessor(), SubtitleFiles(self.font),
            self.font, lambda *_: None, lambda: None)
        result = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=duration,nb_frames", "-of", "json", str(video)]))["streams"][0]
        self.assertAlmostEqual(float(result["duration"]), 1.96, places=4)
        self.assertEqual(int(result["nb_frames"]), 17)

    def test_desktop_cut_undo_redo_and_reopen(self):
        window = MainWindow()
        window._open_project_path(self.folder)
        window.preview_timer.stop()
        window._frame_boundaries = [i/25 for i in range(101)]
        window.snap_words.setChecked(False)
        window.preview_slider.setValue(1000)
        window._split_at_playhead()
        self.assertEqual(len(window._edit.segments), 2)
        window.timeline.selected = 1
        window._delete_segment()
        self.assertEqual(window._edit.duration, 1)
        window._undo_cut(-1)
        self.assertEqual(window._edit.duration, 4)
        window._undo_cut(1)
        self.assertEqual(window._edit.duration, 1)
        window.preview_timer.stop()
        window.close()
        second = MainWindow()
        second._open_project_path(self.folder)
        second.preview_timer.stop()
        self.assertEqual(second._edit.duration, 1)
        self.assertEqual(second.transcript.toPlainText(), "keep")
        second.close()

    def test_manual_evaluation_persisted_in_active_run(self):
        log = MVP3RunLog(self.folder / "run")
        log.evaluate("audio_audible", "passed_user_confirmed", result="User confirmed sound")
        payload = json.loads((log.root / "evaluation.json").read_text())
        self.assertEqual(payload["records"][0]["status"], "passed_user_confirmed")
        log.finish("completed")

    def test_evaluation_write_failure_records_error(self):
        log = MVP3RunLog(self.folder / "run")
        with patch("videogen.infrastructure.mvp3_diagnostics._atomic_json", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                log.evaluate("failure_probe", "pending")
        self.assertEqual(log.write_error, "disk unavailable")
        self.assertIn("evaluation_write_failed", (log.root / "events.jsonl").read_text())

    def test_native_frame_clock_with_encoded_frame_identity(self):
        import numpy as np
        source = self.folder / "counter.mp4"
        frames = []
        for index in range(75):
            frame = np.full((240, 160, 3), 80, dtype=np.uint8)
            for bit in range(8):
                frame[:30, bit*20:(bit+1)*20] = 255 if index & (1 << bit) else 0
            frames.append(frame.tobytes())
        subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "160x240",
            "-framerate", "25", "-i", "pipe:0", "-f", "lavfi", "-i", "sine=frequency=400:duration=3",
            "-c:v", "libx264", "-crf", "0", "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)],
            input=b"".join(frames), capture_output=True, check=True)
        surface = HookPreview()
        try:
            player = LibOpenShotPlayback(surface)
        except Exception as error:
            self.skipTest(f"Native binding unavailable: {error}")
        observations = []
        edit = TimelineEdit.from_dict({"schema_version": 1, "segments": [
            {"id": "a", "start": 0, "end": .48}, {"id": "b", "start": 1, "end": 3}]}, 3)
        try:
            player.open(source, edit)
            surface.frame_clock = player.position_seconds
            def observe(seconds):
                image = surface.last_native_frame
                index = sum((1 << bit) for bit in range(8) if image.pixelColor(bit*20+10, 10).red() > 127)
                if seconds < edit.duration:
                    expected = round(edit.source_time(seconds)*25)
                    observations.append((index, expected))
            surface.framePresented.connect(observe)
            player.play()
            loop = QEventLoop()
            QTimer.singleShot(1700, loop.quit)
            loop.exec()
            player.pause()
            if not observations:
                self.skipTest("No native frames; host audio-session access needs a desktop run")
            self.assertGreater(len(observations), 10)
            self.assertLessEqual(max(abs(a-b) for a,b in observations), 1)
        finally:
            player.close()


if __name__ == "__main__":
    unittest.main()
