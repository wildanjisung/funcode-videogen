"""One active worker, durable status, cooperative cancellation and tree cleanup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

import psutil

from videogen.application.projects import atomic_json
from videogen.web.store import ProjectStore, WebError, identity, now

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


def terminate_tree(process: psutil.Process) -> None:
    """Only called with a process owned by this manager (or verified recovery)."""
    try:
        children = process.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(children, timeout=1)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        if process.is_running():
            process.kill()
        psutil.wait_procs([process, *children], timeout=2)
    except psutil.NoSuchProcess:
        pass


class JobManager:
    cancel_grace = 5

    def __init__(self, store: ProjectStore):
        self.store = store
        self.lock = store.lock
        self.active: str | None = None
        self.thread: threading.Thread | None = None
        self.process: subprocess.Popen | None = None
        self.timer: threading.Timer | None = None
        self.closing = False

    def recover(self) -> None:
        for path in self.store.jobs.glob("*/state.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["status"] in TERMINAL:
                    continue
                if pid := job.get("worker_pid"):
                    try:
                        process = psutil.Process(pid)
                        command = process.cmdline()
                        if (process.create_time() == job.get("worker_created_at")
                                and str(path.parent / "cancel") in command
                                and "videogen.worker_main" in command):
                            terminate_tree(process)
                    except psutil.NoSuchProcess:
                        pass
                job.update(status="interrupted", message="Server berhenti sebelum pekerjaan selesai. Jalankan ulang pekerjaan.", finished_at=now())
                atomic_json(path, job)
            except (OSError, ValueError, KeyError, psutil.AccessDenied):
                continue

    def _path(self, job_id: str) -> Path:
        folder = self.store.jobs / identity(job_id)
        if folder.is_symlink() or not (folder / "state.json").is_file():
            raise WebError("Pekerjaan tidak ditemukan.", 404)
        return folder

    def read(self, job_id: str) -> dict:
        with self.lock:
            return json.loads((self._path(job_id) / "state.json").read_text(encoding="utf-8"))

    def public(self, job_id: str) -> dict:
        job = self.read(job_id)
        return {key: job.get(key) for key in ("id", "project_id", "operation", "status", "stage", "message", "percent", "version", "result", "created_at", "finished_at")}

    def _update(self, job_id: str, **values) -> dict:
        with self.lock:
            job = dict(self.read(job_id), **values)
            atomic_json(self._path(job_id) / "state.json", job)
            return job

    def ensure_idle(self) -> None:
        if self.closing:
            raise WebError("Server sedang berhenti.", 503)
        if self.active:
            raise WebError("Masih ada pekerjaan aktif. Tunggu atau batalkan dahulu.", 409)

    def reserve(self, operation: str, project_id: str, version: int | None = None, *, uploading=False) -> dict:
        with self.lock:
            self.ensure_idle()
            job_id = uuid4().hex
            folder = self.store.jobs / job_id
            folder.mkdir()
            job = {"id": job_id, "project_id": project_id, "operation": operation,
                   "status": "uploading" if uploading else "running", "stage": "upload" if uploading else "starting",
                   "message": "Mengunggah video" if uploading else "Memulai pekerjaan", "percent": None,
                   "version": version, "result": None, "created_at": now(), "finished_at": None}
            atomic_json(folder / "state.json", job)
            self.active = job_id
            self.store.update(project_id, last_job_id=job_id)
            return job

    def fail_upload(self, job_id: str, message: str) -> None:
        with self.lock:
            status = "cancelled" if self.read(job_id)["status"] == "cancelling" else "failed"
            self._update(job_id, status=status, message=message, finished_at=now())
            if self.active == job_id:
                if self.timer:
                    self.timer.cancel()
                    self.timer = None
                self.active = None

    def launch(self, job_id: str, request: dict | None = None) -> dict:
        with self.lock:
            job = self.read(job_id)
            if job["status"] == "cancelling":
                self._update(job_id, status="cancelled", finished_at=now())
                if self.timer:
                    self.timer.cancel()
                    self.timer = None
                self.active = None
                return self.public(job_id)
            if request is not None:
                atomic_json(self._path(job_id) / "request.json", request)
            self._update(job_id, status="running", stage="starting", message="Memulai pekerjaan")
            self.thread = threading.Thread(target=self._run, args=(job_id,), name=f"videogen-{job_id[:8]}", daemon=True)
            self.thread.start()
            return self.public(job_id)

    def _command(self, job: dict) -> list[str]:
        folder = self._path(job["id"])
        command = [sys.executable, "-u", "-m", "videogen.worker_main", "--operation", job["operation"],
                   "--log-file", str(folder / "worker.log"), "--cancel-file", str(folder / "cancel")]
        if job["operation"] in {"transcribe", "playback"}:
            output = self.store.folder(job["project_id"]) / ("processed" if job["operation"] == "transcribe" else "playback.mp4")
            command += ["--source", str(self.store.source(job["project_id"])), "--output", str(output)]
        else:
            command += ["--project", str(self.store.processed(job["project_id"])), "--request", str(folder / "request.json")]
        return command

    def _result(self, job: dict, event: dict) -> dict:
        project_id, job_id = job["project_id"], job["id"]
        folder = self.store.folder(project_id).resolve()
        if job["operation"] == "transcribe":
            project = Path(event["project"]).resolve()
            if not project.is_relative_to(folder) or not (project / "project.json").is_file():
                raise WebError("Worker menghasilkan lokasi proyek yang tidak valid.")
            self.store.update(project_id, project=str(project.relative_to(folder)))
            return {"project_id": project_id}
        if job["operation"] == "preview":
            image = self.store.folder(project_id) / "previews" / f"{job_id}.png"
            layout = json.loads(image.with_suffix(".layout.json").read_text(encoding="utf-8"))
            if not image.is_file():
                raise WebError("File preview tidak tersedia.")
            return {"image_url": f"/api/previews/{job_id}", "layout": layout}
        if job["operation"] == "render":
            video = Path(event["video"]).resolve()
            if not video.is_relative_to(folder) or not video.is_file():
                raise WebError("Worker menghasilkan lokasi hasil yang tidak valid.")
            return {"revision_id": video.parent.name}
        return {"video_url": f"/api/projects/{project_id}/media?proxy=true"}

    def _run(self, job_id: str) -> None:
        terminal = None
        folder = self._path(job_id)
        try:
            job = self.read(job_id)
            environment = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            with (folder / "stderr.txt").open("w", encoding="utf-8") as stderr, (folder / "events.jsonl").open("w", encoding="utf-8") as events:
                with self.lock:
                    if (folder / "cancel").exists():
                        self._update(job_id, status="cancelled", message="Pekerjaan dibatalkan.", finished_at=now())
                        return
                    process = subprocess.Popen(self._command(job), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                        stderr=stderr, text=True, encoding="utf-8", errors="replace", env=environment,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                    self.process = process
                    try:
                        created = psutil.Process(process.pid).create_time()
                    except psutil.NoSuchProcess:
                        created = None
                    self._update(job_id, worker_pid=process.pid, worker_created_at=created)
                try:
                    assert process.stdout is not None
                    for line in process.stdout:
                        events.write(line)
                        events.flush()
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if event.get("type") == "stage":
                            self._update(job_id, stage=event.get("stage"), message=event.get("message", ""), percent=event.get("percent"))
                        elif event.get("type") in {"completed", "failed", "cancelled"}:
                            terminal = event
                    code = process.wait()
                finally:
                    process.stdout.close()
                    if process.poll() is None:
                        terminate_tree(psutil.Process(process.pid))
                        process.wait()
                if terminal and terminal["type"] == "completed" and code == 0:
                    result = self._result(job, terminal)
                    self._update(job_id, status="completed", message="Selesai", percent=100, result=result, finished_at=now())
                elif (folder / "cancel").exists() or (terminal and terminal["type"] == "cancelled"):
                    self._update(job_id, status="cancelled", message="Pekerjaan dibatalkan.", finished_at=now())
                else:
                    message = (terminal or {}).get("message") or "Worker berhenti sebelum selesai. Periksa log pekerjaan."
                    self._update(job_id, status="failed", message=message, finished_at=now())
        except Exception as error:
            self._update(job_id, status="failed", message=str(error), finished_at=now())
        finally:
            with self.lock:
                if self.timer:
                    self.timer.cancel()
                    self.timer = None
                self.process = None
                if self.active == job_id:
                    self.active = None

    def _force_cancel(self, job_id: str) -> None:
        with self.lock:
            if self.active == job_id and self.process and self.process.poll() is None:
                try:
                    terminate_tree(psutil.Process(self.process.pid))
                except psutil.NoSuchProcess:
                    pass

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self.read(job_id)
            if job["status"] in TERMINAL:
                return self.public(job_id)
            (self._path(job_id) / "cancel").touch()
            self._update(job_id, status="cancelling", message="Menghentikan pekerjaan…")
            if self.active == job_id and self.timer is None:
                self.timer = threading.Timer(self.cancel_grace, self._force_cancel, args=(job_id,))
                self.timer.daemon = True
                self.timer.start()
            return self.public(job_id)

    def close(self) -> None:
        with self.lock:
            self.closing = True
            job_id = self.active
            if job_id:
                self.cancel(job_id)
            thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=9)
            if thread.is_alive() and job_id:
                self._force_cancel(job_id)
                thread.join(timeout=4)
