"""Managed web projects; browser input never becomes a filesystem path."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path, PureWindowsPath
import re
import threading
from uuid import uuid4

from videogen.application.projects import atomic_json, normalize_draft, save_draft
from videogen.domain.hook import HookStyle
from videogen.domain.subtitle_style import SubtitleStyle


class WebError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identity(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise WebError("ID tidak dikenal.", 404)
    return value


class ProjectStore:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.projects = self.root / "projects"
        self.jobs = self.root / "jobs"
        self.lock = threading.RLock()
        self.projects.mkdir(parents=True, exist_ok=True)
        self.jobs.mkdir(parents=True, exist_ok=True)

    def folder(self, project_id: str) -> Path:
        path = self.projects / identity(project_id)
        if not (path / "record.json").is_file() or path.is_symlink():
            raise WebError("Proyek tidak ditemukan.", 404)
        return path

    def record(self, project_id: str) -> dict:
        try:
            return json.loads((self.folder(project_id) / "record.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise WebError("Catatan proyek tidak dapat dibaca.", 409) from error

    def update(self, project_id: str, **values) -> dict:
        with self.lock:
            record = dict(self.record(project_id), **values, updated_at=now())
            atomic_json(self.folder(project_id) / "record.json", record)
            return record

    def create(self, filename: str) -> dict:
        # Both POSIX and Windows separators are handled on every server OS.
        filename = PureWindowsPath(filename).name
        name = Path(filename).name.strip()
        suffix = Path(name).suffix.lower()
        if suffix not in {".mp4", ".mov"} or len(name) > 180 or any(ord(c) < 32 for c in name):
            raise WebError("Pilih file MP4 atau MOV dengan nama maksimal 180 karakter.")
        project_id = uuid4().hex
        folder = self.projects / project_id
        (folder / "media").mkdir(parents=True)
        record = {"id": project_id, "name": name, "created_at": now(), "updated_at": now(),
                  "source": f"media/source{suffix}", "source_ready": False,
                  "project": None, "draft_version": 0, "last_job_id": None}
        atomic_json(folder / "record.json", record)
        return record

    def managed_path(self, project_id: str, relative: str) -> Path:
        folder = self.folder(project_id).resolve()
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder):
            raise WebError("File proyek berada di luar folder terkelola.", 409)
        return path

    def source(self, project_id: str) -> Path:
        record = self.record(project_id)
        if not record["source_ready"]:
            raise WebError("Unggahan video belum selesai.", 409)
        source = self.managed_path(project_id, record["source"])
        if not source.is_file():
            raise WebError("Video sumber hilang.", 409)
        return source

    def processed(self, project_id: str) -> Path:
        record = self.record(project_id)
        if not record["project"]:
            raise WebError("Transkripsikan video terlebih dahulu.", 409)
        path = self.managed_path(project_id, record["project"])
        if not (path / "project.json").is_file():
            raise WebError("Data proyek tidak lengkap.", 409)
        return path

    def draft(self, project_id: str) -> dict:
        path = self.processed(project_id)
        try:
            return normalize_draft(path, json.loads((path / "draft.json").read_text(encoding="utf-8")))
        except (OSError, ValueError) as error:
            raise WebError("Draft tidak dapat dibaca.", 409) from error

    def patch_draft(self, project_id: str, version: int, patch: dict) -> dict:
        with self.lock:
            record = self.record(project_id)
            if record["draft_version"] != version:
                raise WebError("Draft berubah di tab lain. Muat ulang proyek sebelum mengedit.", 409)
            draft = self.draft(project_id)
            for key in ("hook", "hook_style", "subtitle_style"):
                if key in patch:
                    draft[key] = dict(draft.get(key) or {}, **patch[key])
            draft["hook_style"] = dict(vars(HookStyle.from_dict(draft.get("hook_style"))))
            draft["subtitle_style"] = dict(vars(SubtitleStyle.from_dict(draft.get("subtitle_style"))))
            save_draft(self.processed(project_id), draft)
            self.update(project_id, draft_version=version + 1)
            return draft

    def snapshot(self, project_id: str, version: int) -> dict:
        if self.record(project_id)["draft_version"] != version:
            raise WebError("Draft sudah berubah. Simpan lalu perbarui preview.", 409)
        return self.draft(project_id)

    def summary(self, project_id: str) -> dict:
        record = self.record(project_id)
        return {key: record[key] for key in ("id", "name", "created_at", "updated_at", "source_ready", "draft_version", "last_job_id")} | {
            "ready": bool(record["project"]), "playback_ready": (self.folder(project_id) / "playback.mp4").is_file()}

    def listing(self) -> list[dict]:
        result = []
        for folder in self.projects.iterdir():
            if re.fullmatch(r"[a-f0-9]{32}", folder.name):
                try:
                    result.append(self.summary(folder.name))
                except (WebError, KeyError, ValueError):
                    continue
        return sorted(result, key=lambda value: value["updated_at"], reverse=True)

    def detail(self, project_id: str) -> dict:
        with self.lock:
            result = self.summary(project_id)
            if not result["ready"]:
                return result
            folder = self.processed(project_id)
            result.update(draft=self.draft(project_id),
                media=json.loads((folder / "media.json").read_text(encoding="utf-8")),
                words=json.loads((folder / "words.json").read_text(encoding="utf-8")),
                transcript=(folder / "transcript.txt").read_text(encoding="utf-8"))
            revisions = folder / "revisions"
            result["revisions"] = []
            if revisions.is_dir():
                for path in sorted(revisions.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                    if re.fullmatch(r"[a-f0-9]{12}", path.name) and (path / "render.json").is_file():
                        result["revisions"].append({"id": path.name, "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
            return result

    def revision_file(self, project_id: str, revision_id: str, kind: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", revision_id) or kind not in {"mp4", "txt", "srt"}:
            raise WebError("Hasil tidak ditemukan.", 404)
        folder = self.processed(project_id) / "revisions" / revision_id
        path = folder / f"source_subtitled.{kind}"
        if not path.is_file() or not path.resolve().is_relative_to(self.folder(project_id).resolve()):
            raise WebError("Hasil tidak ditemukan.", 404)
        return path
