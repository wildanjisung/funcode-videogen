"""Loopback web application; heavy work always runs in the existing worker."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import psutil
from starlette.middleware.trustedhost import TrustedHostMiddleware

from videogen.application.ports import UserFacingError
from videogen.infrastructure.ffmpeg import FFmpegMediaProcessor
from videogen.infrastructure.fonts import default_font_path
from videogen.infrastructure.paths import app_directory, default_model_path
from videogen.web.jobs import JobManager
from videogen.web.schemas import DraftPatch, PreviewInput, RenderInput
from videogen.web.store import ProjectStore, WebError

STATIC = Path(__file__).parent / "static"


class ServerLease:
    """Prevent two local servers from owning the same workers/project directory."""
    def __init__(self, root: Path):
        self.path = root / ".server.lock"
        self.token = uuid4().hex

    def acquire(self):
        if self.path.exists():
            try:
                previous = json.loads(self.path.read_text(encoding="utf-8"))
                process = psutil.Process(previous["pid"])
                alive = process.is_running() and process.create_time() == previous["created_at"]
            except psutil.NoSuchProcess:
                alive = False
            except (OSError, ValueError, KeyError, psutil.AccessDenied) as error:
                raise RuntimeError(f"Lock server tidak dapat diperiksa: {self.path}") from error
            if alive:
                raise RuntimeError("Folder data sedang digunakan server Videogen lain.")
            self.path.unlink()
        with self.path.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "created_at": psutil.Process().create_time(), "token": self.token}, handle)

    def release(self):
        if self.path.exists() and json.loads(self.path.read_text(encoding="utf-8")).get("token") == self.token:
            self.path.unlink()


def setup_status() -> dict:
    model, font = default_model_path(), default_font_path()
    checks = {"ffmpeg": {"ready": False, "message": ""},
              "model": {"ready": (model / "model.bin").is_file() and (model / "config.json").is_file(), "path": str(model)},
              "font": {"ready": font.is_file() and os.access(font, os.R_OK), "path": str(font)}}
    try:
        FFmpegMediaProcessor.check_environment()
        checks["ffmpeg"].update(ready=True, message="FFmpeg, libass, libx264 tersedia")
    except (UserFacingError, OSError) as error:
        checks["ffmpeg"]["message"] = str(error)
    return {"ready": all(item["ready"] for item in checks.values()), "checks": checks}


def create_app(data_dir: Path | None = None, max_upload_bytes: int = 2 * 1024**3) -> FastAPI:
    store = ProjectStore(data_dir or app_directory("data") / "web")
    manager = JobManager(store)
    lease = ServerLease(store.root)

    @asynccontextmanager
    async def lifespan(_app):
        lease.acquire()
        try:
            manager.recover()
            yield
        finally:
            await asyncio.to_thread(manager.close)
            lease.release()

    app = FastAPI(title="Videogen local", lifespan=lifespan)
    app.state.store, app.state.manager = store, manager
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "Akses harus berasal dari halaman Videogen yang sama."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Akses lintas situs ditolak."}, status_code=403)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "same-origin", "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; font-src 'self'; frame-ancestors 'none'"})
        return response

    @app.exception_handler(WebError)
    async def web_error(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.exception_handler(UserFacingError)
    async def worker_error(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(ValueError)
    async def invalid_value(_request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.get("/api/status")
    def status():
        return {"setup": setup_status(), "active_job": manager.public(manager.active) if manager.active else None,
                "max_upload_bytes": max_upload_bytes, "data_dir": str(store.root)}

    @app.get("/api/projects")
    def projects():
        return store.listing()

    @app.get("/api/projects/{project_id}")
    def project(project_id: str):
        return store.detail(project_id)

    @app.post("/api/projects", status_code=202)
    async def upload(request: Request, filename: str = Query(min_length=1, max_length=500)):
        if request.headers.get("content-type", "").split(";", 1)[0] not in {"application/octet-stream", "video/mp4", "video/quicktime"}:
            raise WebError("Kirim file video sebagai body biner.", 415)
        length = request.headers.get("content-length")
        if length and int(length) > max_upload_bytes:
            raise WebError("Ukuran video melebihi batas unggahan.", 413)
        with store.lock:
            manager.ensure_idle()
            record = store.create(filename)
            job = manager.reserve("transcribe", record["id"], uploading=True)
        source = store.managed_path(record["id"], record["source"])
        temporary = source.with_suffix(source.suffix + ".part")
        size = 0
        try:
            with temporary.open("wb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > max_upload_bytes:
                        raise WebError("Ukuran video melebihi batas unggahan.", 413)
                    if manager.read(job["id"])["status"] == "cancelling":
                        raise WebError("Unggahan dibatalkan.", 409)
                    handle.write(chunk)
            if not size:
                raise WebError("File video kosong.")
            temporary.replace(source)
            store.update(record["id"], source_ready=True)
            return manager.launch(job["id"])
        except BaseException as error:
            temporary.unlink(missing_ok=True)
            manager.fail_upload(job["id"], str(error) or "Unggahan terputus. Pilih video kembali.")
            raise

    @app.post("/api/projects/{project_id}/transcribe", status_code=202)
    def retry_transcription(project_id: str):
        with store.lock:
            store.source(project_id)
            if store.record(project_id)["project"]:
                raise WebError("Proyek ini sudah memiliki transkrip.", 409)
            job = manager.reserve("transcribe", project_id)
            return manager.launch(job["id"])

    @app.put("/api/projects/{project_id}/draft")
    def draft(project_id: str, patch: DraftPatch):
        payload = patch.model_dump(exclude_unset=True)
        store.patch_draft(project_id, payload.pop("version"), payload)
        return store.detail(project_id)

    @app.post("/api/projects/{project_id}/previews", status_code=202)
    def preview(project_id: str, body: PreviewInput):
        with store.lock:
            snapshot = store.snapshot(project_id, body.version)
            job = manager.reserve("preview", project_id, body.version)
            output = store.folder(project_id) / "previews" / f"{job['id']}.png"
            snapshot.update(timestamp=body.timestamp, request_id=job["id"], output=str(output))
            return manager.launch(job["id"], snapshot)

    @app.post("/api/projects/{project_id}/renders", status_code=202)
    def render(project_id: str, body: RenderInput):
        with store.lock:
            snapshot = store.snapshot(project_id, body.version)
            checked = manager.read(body.preview_job_id)
            if (checked["operation"] != "preview" or checked["project_id"] != project_id
                    or checked["status"] != "completed" or checked["version"] != body.version
                    or not checked["result"]["layout"]["all_cues_valid"]):
                raise WebError("Perbarui preview hingga seluruh cue valid sebelum render.", 409)
            snapshot["validated_words_sha256"] = checked["result"]["layout"]["words_sha256"]
            job = manager.reserve("render", project_id, body.version)
            return manager.launch(job["id"], snapshot)

    @app.post("/api/projects/{project_id}/playback", status_code=202)
    def playback(project_id: str):
        with store.lock:
            store.source(project_id)
            job = manager.reserve("playback", project_id)
            return manager.launch(job["id"])

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        return manager.public(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return manager.cancel(job_id)

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str):
        folder = manager._path(job_id)
        path = folder / "worker.log"
        if not path.is_file():
            path = folder / "stderr.txt"
        if not path.is_file():
            raise WebError("Log belum tersedia.", 404)
        return FileResponse(path, media_type="text/plain", filename=f"videogen-{job_id[:8]}.log")

    @app.get("/api/projects/{project_id}/media")
    def media(project_id: str, proxy: bool = False):
        path = store.managed_path(project_id, "playback.mp4") if proxy else store.source(project_id)
        if not path.is_file():
            raise WebError("Video playback belum tersedia.", 404)
        return FileResponse(path, media_type="video/quicktime" if path.suffix == ".mov" else "video/mp4")

    @app.get("/api/previews/{job_id}")
    def preview_image(job_id: str):
        job = manager.read(job_id)
        if job["operation"] != "preview" or job["status"] != "completed":
            raise WebError("Preview belum tersedia.", 404)
        return FileResponse(store.managed_path(job["project_id"], f"previews/{job_id}.png"), media_type="image/png")

    @app.get("/api/projects/{project_id}/revisions/{revision_id}/{kind}")
    def artifact(project_id: str, revision_id: str, kind: str, download: bool = False):
        path = store.revision_file(project_id, revision_id, kind)
        filename = f"{Path(store.record(project_id)['name']).stem}_subtitled.{kind}"
        return FileResponse(path, filename=filename if download else None,
            media_type={"mp4": "video/mp4", "txt": "text/plain", "srt": "application/x-subrip"}[kind])

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.mount("/resources", StaticFiles(directory=Path(__file__).parents[1] / "presentation" / "resources"), name="resources")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Videogen web lokal")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--max-upload-mb", type=int, default=2048)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.max_upload_mb < 1:
        parser.error("Port atau batas unggahan tidak valid.")
    import uvicorn
    print(f"Buka http://127.0.0.1:{args.port} di browser.", flush=True)
    uvicorn.run(create_app(args.data_dir, args.max_upload_mb * 1024**2), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
