import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from videogen.presentation.desktop import MainWindow


class DesktopFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["desktop-tests", "-platform", "offscreen"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = MainWindow()

    def tearDown(self):
        self.window.preview_timer.stop()
        self.window.draft_timer.stop()
        self.window.close()
        self.window.deleteLater()
        self.temp.cleanup()

    def ready_project(self):
        w = self.window
        w.project_dir = Path(self.temp.name)
        w._video_duration = 50
        w._set_project_controls(True)
        w._load_draft({"instruction": "Fokus biaya", "hook": {"text": "ONE JOB", "duration": 5}})
        w.preview_timer.stop()
        w.draft_timer.stop()
        w._show_stage(1)

    def test_initial_stage_and_primary_action(self):
        w = self.window
        self.assertEqual(w.pages.currentIndex(), 0)
        self.assertFalse(w.transcribe_button.isEnabled())
        self.assertTrue(w.choose_button.property("primary"))
        self.assertFalse(w.render_button.isEnabled())

    def test_draft_survives_result_and_edit_navigation(self):
        self.ready_project()
        w = self.window
        w.status_label.setText("Petunjuk proses")
        self.assertTrue(w._save_draft())
        self.assertEqual(w.status_label.text(), "Petunjuk proses")
        self.assertEqual(w.save_status.text(), "Draft tersimpan")
        video = Path(self.temp.name) / "revision" / "clip.mp4"
        video.parent.mkdir()
        video.write_bytes(b"video")
        w._terminal = {"type": "completed", "operation": "render", "video": str(video), "revision": str(video.parent)}
        with patch.object(w, "_read_worker_output"):
            w._worker_finished(0, QProcess.ExitStatus.NormalExit)
        self.assertEqual(w.pages.currentIndex(), 2)
        self.assertEqual(w.last_video, video)
        w.edit_button.click()
        self.assertEqual(w.pages.currentIndex(), 1)
        self.assertEqual(w.hook_text.toPlainText(), "ONE JOB")
        self.assertEqual(w.instruction.text(), "Fokus biaya")
        w._return_to_video()
        self.assertEqual(w.pages.currentIndex(), 0)
        self.assertEqual(w.hook_text.toPlainText(), "ONE JOB")

    def test_edit_invalidates_preview_immediately_and_shows_reason(self):
        self.ready_project()
        w = self.window
        w._preview_valid = True
        w._refresh_render_button()
        self.assertTrue(w.render_button.isEnabled())
        request_id = w._preview_request
        w.hook_text.setPlainText("ANOTHER JOB")
        self.assertGreater(w._preview_request, request_id)
        self.assertFalse(w.render_button.isEnabled())
        self.assertIn("memperbarui", w.render_reason.text())
        w.preview_slider.setValue(500)
        self.assertEqual(w.time_label.text(), "00:25 / 00:50")

    def test_editor_preview_render_fit_without_page_scroll(self):
        self.ready_project()
        w = self.window
        w.show()
        for width, height in ((1040, 720), (800, 600)):
            w.resize(width, height)
            self.app.processEvents()
            for widget in (w.hook_text, w.preview_label, w.render_button):
                top = widget.mapTo(w.centralWidget(), widget.rect().topLeft())
                self.assertGreaterEqual(top.x(), 0)
                self.assertGreaterEqual(top.y(), 0)
                self.assertLessEqual(top.x() + widget.width(), w.centralWidget().width())
                self.assertLessEqual(top.y() + widget.height(), w.centralWidget().height())
