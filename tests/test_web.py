"""API/worker integration and lifecycle regressions for the local web UI."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import psutil
from fastapi.testclient import TestClient

from videogen.application.projects import save_draft, transcribe_project
from videogen.domain.models import Word
from videogen.infrastructure.ffmpeg import FFmpegMediaProcessor, reset_cancel
from videogen.infrastructure.fonts import SubtitleFont, default_font_path
from videogen.infrastructure.paths import app_directory
from videogen.infrastructure.subtitles import SubtitleFiles
from videogen.web.jobs import TERMINAL
from videogen.web.server import create_app


class KnownWords:
    def transcribe(self, _audio):
        return [Word("one", .1, .4), Word("short", .5, .8), Word("story", .9, 1.3)]


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.source = Path(cls.fixture.name) / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x480:r=24:d=2",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=2", "-c:v", "libx264", "-threads", "1",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(cls.source)], check=True)
        cls.font = SubtitleFont(default_font_path())

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def setUp(self):
        reset_cancel()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "config"),
            "VIDEOGEN_MODEL_PATH": str(self.root / "model-intentionally-absent")})
        self.environment.start()
        self.app = create_app(self.root / "data", max_upload_bytes=32)
        self.store = self.app.state.store
        self.manager = self.app.state.manager
        self.client_context = TestClient(self.app, base_url="http://127.0.0.1")
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.environment.stop()
        self.temporary.cleanup()

    def seed(self):
        record = self.store.create("Example clip.mp4")
        project_id = record["id"]
        source = self.store.managed_path(project_id, record["source"])
        shutil.copyfile(self.source, source)
        self.store.update(project_id, source_ready=True)
        media = FFmpegMediaProcessor(font_path=self.font.path, expected_font=self.font.postscript_name)
        folder = transcribe_project(source, self.store.folder(project_id) / "processed", media,
            KnownWords(), SubtitleFiles(self.font), self.font, lambda *_: None, lambda: None)
        draft = json.loads((folder / "draft.json").read_text())
        draft["hook"]["text"] = "ONE STORY"
        save_draft(folder, draft)
        self.store.update(project_id, project=str(folder.relative_to(self.store.folder(project_id))))
        return project_id

    def wait_job(self, job, status="completed", timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = self.client.get(f"/api/jobs/{job['id']}").json()
            if result["status"] in TERMINAL and self.manager.active is None:
                self.assertEqual(result["status"], status, result)
                return result
            time.sleep(.05)
        self.fail(f"Worker did not finish: {result}")

    def preview(self, project_id, version=0):
        response = self.client.post(f"/api/projects/{project_id}/previews", json={"version": version, "timestamp": .55})
        self.assertEqual(response.status_code, 202, response.text)
        return self.wait_job(response.json())

    def test_api_guards_limits_and_static_assets(self):
        self.assertIn('id="preview"', self.client.get('/').text)
        self.assertEqual(self.client.get('/static/app.js').status_code, 200)
        self.assertEqual(self.client.get('/api/projects', headers={"Host": "attacker.invalid"}).status_code, 400)
        self.assertEqual(self.client.post('/api/projects?filename=clip.mp4', content=b"a", headers={"Origin": "https://attacker.invalid", "Content-Type": "application/octet-stream"}).status_code, 403)
        self.assertEqual(self.client.post('/api/projects?filename=clip.mp4', content=b"x" * 33, headers={"Content-Type": "application/octet-stream"}).status_code, 413)
        self.assertEqual(self.client.post('/api/projects?filename=clip.mp4', json={"path": "/etc/passwd"}).status_code, 415)
        response = self.client.post('/api/projects?filename=clip.mp4', content=iter([b"x" * 20, b"y" * 20]), headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIsNone(self.manager.active)
        self.assertFalse(list(self.store.projects.rglob('*.part')))
        response = self.client.post('/api/projects?filename=clip.mp4', content=b"", headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.manager.active)
        self.assertEqual(self.client.get('/api/jobs/not-an-id').status_code, 404)

    def test_real_worker_preview_render_stale_draft_and_revisions(self):
        project_id = self.seed()
        words = (self.store.processed(project_id) / "words.json").read_bytes()
        preview = self.preview(project_id)
        image = self.client.get(preview['result']['image_url'])
        self.assertEqual(image.status_code, 200)
        self.assertTrue(image.content.startswith(b'\x89PNG'))
        self.assertTrue(preview['result']['layout']['all_cues_valid'])
        media = self.client.get(f'/api/projects/{project_id}/media', headers={"Range": "bytes=0-15"})
        self.assertEqual(media.status_code, 206)
        self.assertEqual(len(media.content), 16)
        body = {"version": 0, "preview_job_id": preview['id']}
        rendered = self.wait_job(self.client.post(f'/api/projects/{project_id}/renders', json=body).json())
        revision = rendered['result']['revision_id']
        base = f'/api/projects/{project_id}/revisions/{revision}'
        first = self.client.get(base + '/mp4?download=true')
        self.assertEqual(first.status_code, 200)
        self.assertGreater(len(first.content), 1000)
        self.assertIn('Example%20clip_subtitled.mp4', first.headers['content-disposition'])
        self.assertIn('one', self.client.get(base + '/srt').text)
        self.assertEqual(self.client.get(base + '/txt').text.strip(), 'one short story')
        self.assertEqual(self.client.get(base + '/log').status_code, 404)
        self.assertEqual(self.client.put(f'/api/projects/{project_id}/draft', json={"version": 0, "hook_style": {"font": {"path": "/etc/passwd"}}}).status_code, 422)
        changed = self.client.put(f'/api/projects/{project_id}/draft', json={"version": 0, "hook": {"text": "A NEW STORY"}})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()['draft_version'], 1)
        self.assertEqual(self.client.put(f'/api/projects/{project_id}/draft', json={"version": 0}).status_code, 409)
        self.assertEqual(self.client.post(f'/api/projects/{project_id}/renders', json=dict(body, version=1)).status_code, 409)
        self.assertEqual(self.client.post(f'/api/projects/{project_id}/previews', json={"version": 0}).status_code, 409)
        latest = self.preview(project_id, 1)
        rendered2 = self.wait_job(self.client.post(f'/api/projects/{project_id}/renders', json={"version": 1, "preview_job_id": latest['id']}).json())
        self.assertNotEqual(rendered2['result']['revision_id'], revision)
        self.assertEqual(self.client.get(base + '/mp4').content, first.content)
        self.assertEqual((self.store.processed(project_id) / 'words.json').read_bytes(), words)
        self.assertEqual(len(self.client.get(f'/api/projects/{project_id}').json()['revisions']), 2)

    def test_invalid_subtitle_layout_cannot_render(self):
        project_id = self.seed()
        response = self.client.put(f'/api/projects/{project_id}/draft', json={"version": 0, "subtitle_style": {"size_fraction": .5}})
        self.assertEqual(response.status_code, 200)
        preview = self.preview(project_id, 1)
        self.assertFalse(preview['result']['layout']['all_cues_valid'])
        self.assertEqual(self.client.post(f'/api/projects/{project_id}/renders', json={"version": 1, "preview_job_id": preview['id']}).status_code, 409)

    def test_worker_rejects_changed_word_timings_after_preview(self):
        project_id = self.seed()
        preview = self.preview(project_id)
        path = self.store.processed(project_id) / 'words.json'
        words = json.loads(path.read_text())
        words[0]['start'] = .12
        path.write_text(json.dumps(words), encoding='utf-8')
        response = self.client.post(f'/api/projects/{project_id}/renders', json={"version": 0, "preview_job_id": preview['id']})
        job = self.wait_job(response.json(), 'failed')
        self.assertIn('sejak preview', job['message'])
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}/log').status_code, 200)

    def test_browser_playback_proxy_and_persistent_reload(self):
        project_id = self.seed()
        job = self.wait_job(self.client.post(f'/api/projects/{project_id}/playback').json())
        response = self.client.get(job['result']['video_url'], headers={'Range': 'bytes=0-31'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 32)
        self.client_context.__exit__(None, None, None)
        self.app = create_app(self.root / 'data')
        self.client_context = TestClient(self.app, base_url='http://127.0.0.1')
        self.client = self.client_context.__enter__()
        self.assertTrue(self.client.get(f'/api/projects/{project_id}').json()['playback_ready'])
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}').json()['status'], 'completed')

    def test_cancel_kills_descendant_and_busy_job_is_rejected(self):
        record = self.store.create('cancel.mp4')
        source = self.store.managed_path(record['id'], record['source'])
        source.write_bytes(b'fake source for lifecycle-only worker')
        self.store.update(record['id'], source_ready=True)
        script = self.root / 'slow_worker.py'
        child_file = self.root / 'child.pid'
        script.write_text('import subprocess, sys, time\nfrom pathlib import Path\n'
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
            'Path(sys.argv[1]).write_text(str(child.pid))\n'
            'print(\'{"type":"stage","stage":"testing","message":"started"}\', flush=True)\n'
            'time.sleep(60)\n', encoding='utf-8')
        self.manager.cancel_grace = .15
        with patch.object(self.manager, '_command', return_value=[sys.executable, '-u', str(script), str(child_file)]):
            response = self.client.post(f'/api/projects/{record["id"]}/transcribe')
            self.assertEqual(response.status_code, 202)
            job = response.json()
            deadline = time.monotonic() + 4
            while not child_file.exists() and time.monotonic() < deadline:
                time.sleep(.03)
            self.assertTrue(child_file.exists())
            child = psutil.Process(int(child_file.read_text()))
            self.assertEqual(self.client.post(f'/api/projects/{record["id"]}/transcribe').status_code, 409)
            self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/cancel').status_code, 200)
            self.wait_job(job, 'cancelled')
            self.assertFalse(child.is_running() and child.status() != psutil.STATUS_ZOMBIE)
            self.assertIsNone(self.manager.active)

    def test_server_data_directory_cannot_have_two_owners(self):
        with self.assertRaisesRegex(RuntimeError, 'server Videogen lain'):
            with TestClient(create_app(self.root / 'data'), base_url='http://127.0.0.1'):
                pass

    def test_cancelled_upload_releases_timer_for_next_job(self):
        record = self.store.create('cancel-upload.mp4')
        first = self.manager.reserve('transcribe', record['id'], uploading=True)
        self.manager.cancel(first['id'])
        self.assertIsNotNone(self.manager.timer)
        self.manager.fail_upload(first['id'], 'Upload dibatalkan')
        self.assertEqual(self.manager.read(first['id'])['status'], 'cancelled')
        self.assertIsNone(self.manager.active)
        self.assertIsNone(self.manager.timer)
        second = self.manager.reserve('transcribe', record['id'], uploading=True)
        self.manager.cancel(second['id'])
        self.assertIsNotNone(self.manager.timer)
        self.manager.fail_upload(second['id'], 'Upload dibatalkan')
        self.assertIsNone(self.manager.timer)

    def test_platform_paths_and_windows_filename(self):
        self.assertEqual(self.store.create(r'C:\videos\safe.MOV')['name'], 'safe.MOV')
        with patch.dict(os.environ, {'LOCALAPPDATA': str(self.root)}, clear=True), patch('sys.platform', 'win32'):
            self.assertEqual(app_directory('data'), self.root / 'Videogen' / 'data')
        with patch.dict(os.environ, {}, clear=True), patch('sys.platform', 'darwin'), patch('pathlib.Path.home', return_value=self.root):
            self.assertEqual(app_directory('cache'), self.root / 'Library' / 'Caches' / 'Videogen')


if __name__ == '__main__':
    unittest.main()
