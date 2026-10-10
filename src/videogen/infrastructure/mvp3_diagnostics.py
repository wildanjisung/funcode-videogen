"""Persistent, per-run diagnostics for the MVP 3A editor prototype."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import threading
from time import monotonic
from uuid import uuid4


def _atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


class MVP3RunLog:
    """Append-only event archive; never includes hook/transcript contents."""

    SCHEMA_VERSION = 1

    def __init__(self, root: Path | None = None) -> None:
        state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        self._fallback_root = state / "videogen" / "mvp3a-runs"
        self.run_id = uuid4().hex
        self._root = root if root is not None else self._fallback_root / self.run_id
        self._lock = threading.RLock()
        self._sequence = 0
        self._started = monotonic()
        self._started_utc = datetime.now(timezone.utc).isoformat()
        try:
            self._write_manifest({"application": "videogen", "python": sys.version.split()[0],
                                  "platform": platform.platform(), "qt": self._qt_version(),
                                  "engine": "not_initialized"})
        except OSError as error:
            uid = getattr(os, "getuid", lambda: 0)()
            self._fallback_root = Path(tempfile.gettempdir()) / f"videogen-mvp3a-{uid}"
            self._root = self._fallback_root / self.run_id
            self._write_error = f"Initial state directory unavailable: {type(error).__name__}: {error}"
            self._write_manifest({"application": "videogen", "python": sys.version.split()[0],
                                  "platform": platform.platform(), "qt": self._qt_version(),
                                  "engine": "not_initialized", "initial_write_error": self._write_error})
        self.record("run_started", status="running")
        self._mark_previous_incomplete()

    @staticmethod
    def _qt_version() -> str | None:
        try:
            from PySide6 import QtCore
            return QtCore.qVersion()
        except Exception:
            return None

    @property
    def root(self) -> Path:
        return self._root

    @property
    def write_error(self) -> str | None:
        return getattr(self, "_write_error", None)

    def _write_manifest(self, details: dict) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / "manifest.json"
        current = {}
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        current.update({"schema_version": self.SCHEMA_VERSION, "run_id": self.run_id,
                        "started_utc": getattr(self, "_started_utc", datetime.now(timezone.utc).isoformat()),
                        **details})
        _atomic_json(path, current)

    def attach_project(self, project_dir: Path, project: dict | None = None) -> None:
        """Move the active archive into the project and remove its temporary copy."""
        project_dir = project_dir.expanduser().resolve()
        target = project_dir / "diagnostics" / "mvp3a" / self.run_id
        with self._lock:
            previous_project = getattr(self, "_project_dir", None)
            if previous_project is not None and previous_project != project_dir:
                previous_run = self.run_id
                self.finish("project_switched", next_project_id=project_dir.name)
                self.run_id = uuid4().hex
                self._sequence = 0
                self._started = monotonic()
                self._started_utc = datetime.now(timezone.utc).isoformat()
                self._root = self._fallback_root / self.run_id
                self._write_manifest({"application": "videogen", "python": sys.version.split()[0],
                                      "platform": platform.platform(), "qt": self._qt_version(),
                                      "engine": "libopenshot_pending_compatibility",
                                      "previous_run_id": previous_run})
                self.record("run_started", status="running", previous_run_id=previous_run)
                target = project_dir / "diagnostics" / "mvp3a" / self.run_id
            self._mark_previous_incomplete(target.parent)
            if self._root == target:
                return
            old_root = self._root
            target.mkdir(parents=True, exist_ok=True)
            for name in ("manifest.json", "events.jsonl", "evaluation.json"):
                source = old_root / name
                if source.is_file():
                    destination = target / name
                    if destination.exists() and name == "events.jsonl":
                        with source.open("rb") as src, destination.open("ab") as dst:
                            shutil.copyfileobj(src, dst)
                    else:
                        shutil.copy2(source, destination)
            self._root = target
            self._project_dir = project_dir
            source_path = None
            source_hash = None
            if project:
                raw_source = project.get("source_path")
                source_path = str(raw_source) if raw_source else None
                source_hash = project.get("source_sha256")
            media = {}
            try:
                media = json.loads((project_dir / "media.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            self._write_manifest({"project_id": project.get("project_id") if project else project_dir.name,
                                  "project_path": str(project_dir), "source_path": source_path,
                                  "source_sha256": source_hash or (_sha256(Path(source_path)) if source_path else None),
                                  "media": {key: media.get(key) for key in (
                                      "video_stream_index", "audio_stream_index", "width", "height", "display_width",
                                      "display_height", "duration", "video_start", "audio_start", "video_codec",
                                      "audio_codec", "pixel_format", "sample_aspect_ratio") if key in media},
                                  "engine": "libopenshot_pending_compatibility"})
            self.record("project_attached", status="completed", project_id=project_dir.name)
            if old_root != target:
                try:
                    shutil.rmtree(old_root)
                except OSError:
                    pass

    def update_engine(self, **details: object) -> None:
        """Persist observed native engine identity without claiming evaluation pass."""
        with self._lock:
            self._write_manifest({"engine": "libopenshot", **details})

    def evaluate(self, check_id, status, **details):
        """Append proof to the current archive, including manual user evaluations."""
        with self._lock:
            path = self.root / "evaluation.json"
            try:
                payload = json.loads(path.read_text())
            except (OSError, ValueError):
                payload = {"schema_version": 1, "run_id": self.run_id, "records": []}
            record = {"check_id": check_id, "status": status, "time_utc": datetime.now(timezone.utc).isoformat(), **details}
            payload.setdefault("records", []).append(record)
            try:
                _atomic_json(path, payload)
            except OSError as error:
                self._write_error = str(error)
                self.record("evaluation_write_failed", status="failed", error_message=str(error))
                raise
            self.record("evaluation_recorded", status=status, check_id=check_id, **details)

    def record(self, event: str, *, status: str = "info", **details: object) -> bool:
        safe = {key: value for key, value in details.items() if key not in {"text", "transcript", "hook_text", "api_key", "token"}}
        with self._lock:
            self._sequence += 1
            payload = {"schema_version": self.SCHEMA_VERSION, "sequence": self._sequence,
                       "run_id": self.run_id, "time_utc": datetime.now(timezone.utc).isoformat(),
                       "elapsed_seconds": round(monotonic() - self._started, 6), "event": event,
                       "status": status, **safe}
            try:
                self._root.mkdir(parents=True, exist_ok=True)
                with (self._root / "events.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
                    stream.flush()
                    if status in {"failed", "cancelled", "completed", "committed", "incomplete"} or event == "run_finished":
                        os.fsync(stream.fileno())
                return True
            except OSError as error:
                self._write_error = f"{type(error).__name__}: {error}"
                fallback = self._fallback_root / self.run_id
                try:
                    fallback.mkdir(parents=True, exist_ok=True)
                    with (fallback / "events.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({**payload, "event": "log_write_failure", "failed_event": event,
                                                 "write_error": self._write_error}, ensure_ascii=False, default=str) + "\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    self._root = fallback
                except OSError:
                    pass
                return False

    def finish(self, status: str = "completed", **details: object) -> None:
        self.record("run_finished", status=status, **details)
        try:
            self._write_manifest({"finished_utc": datetime.now(timezone.utc).isoformat(), "terminal_status": status,
                                  "event_count": self._sequence})
        except OSError as error:
            self._write_error = f"{type(error).__name__}: {error}"

    def _mark_previous_incomplete(self, root: Path | None = None) -> None:
        try:
            for manifest in (root or self._fallback_root).glob("*/manifest.json"):
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if data.get("run_id") == self.run_id:
                    continue
                if data.get("terminal_status") is None:
                    events = manifest.parent / "events.jsonl"
                    with events.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"schema_version": self.SCHEMA_VERSION, "time_utc": datetime.now(timezone.utc).isoformat(),
                                                 "run_id": data.get("run_id"), "event": "incomplete_run_detected",
                                                 "status": "incomplete"}, ensure_ascii=False) + "\n")
                    data["terminal_status"] = "incomplete"
                    data["finished_utc"] = datetime.now(timezone.utc).isoformat()
                    _atomic_json(manifest, data)
        except (OSError, ValueError, TypeError):
            return
