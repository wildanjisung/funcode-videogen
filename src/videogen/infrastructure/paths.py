"""Per-user paths, with the existing checkout caches retained when present."""
import os
import sys
from pathlib import Path


def app_directory(kind: str) -> Path:
    variables = {"data": "XDG_DATA_HOME", "cache": "XDG_CACHE_HOME", "config": "XDG_CONFIG_HOME", "state": "XDG_STATE_HOME"}
    if value := os.environ.get(variables[kind]):
        return Path(value).expanduser() / "videogen"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Videogen" / kind
    if sys.platform == "darwin":
        folder = {"cache": "Caches", "state": "Logs"}.get(kind, "Application Support")
        return Path.home() / "Library" / folder / "Videogen"
    folder = {"data": ".local/share", "state": ".local/state", "cache": ".cache", "config": ".config"}[kind]
    return Path.home() / folder / "videogen"


def cached_asset(variable: str, relative: str) -> Path:
    if value := os.environ.get(variable):
        return Path(value).expanduser().resolve()
    legacy = Path(__file__).parents[3] / ".cache" / relative
    return (legacy if legacy.exists() else app_directory("cache") / relative).resolve()


def default_model_path() -> Path:
    return cached_asset("VIDEOGEN_MODEL_PATH", "models/small")
