"""Local style snapshots and explicit global preset operations."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

from videogen.application.ports import UserFacingError
from videogen.application.projects import atomic_json, file_sha256
from videogen.domain.hook import HookStyle
from videogen.domain.subtitle_style import SubtitleStyle
from videogen.infrastructure.fonts import SubtitleFont, default_font_path


def font_reference(font: SubtitleFont) -> dict:
    return {"path": str(font.path), "family": font.raw.familyName(), "style": font.raw.styleName(),
            "postscript_name": font.postscript_name, "sha256": file_sha256(font.path),
            "weight": int(font.raw.weight()), "italic": bool(font.raw.style().value)}


def resolve_style_font(style: HookStyle, fallback: SubtitleFont) -> SubtitleFont:
    style.validate()
    if style.font is None:
        return fallback
    try:
        ref = style.font
        path = Path(ref["path"])
        if file_sha256(path) != ref["sha256"]:
            raise ValueError("hash")
        font = SubtitleFont(path, strict_subtitle=False)
        if font.postscript_name != ref["postscript_name"] or font.raw.familyName() != ref["family"]:
            raise ValueError("identity")
        return font
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise UserFacingError("Font gaya hilang atau tidak cocok. Impor kembali atau pilih font lain melalui editor.") from error


class HookPresets:
    def __init__(self) -> None:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        self.path = root / "videogen" / "hook-presets.json"
        self.data = {"schema_version": 3, "default_id": None, "subtitle_default_id": None, "presets": []}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data["schema_version"] not in (1, 2, 3) or not isinstance(data["presets"], list):
                    raise ValueError("schema")
                ids, names = set(), set()
                for item in data["presets"]:
                    item.setdefault("target", "hook")
                    if item["target"] not in ("hook", "subtitle"):
                        raise ValueError("target")
                    model = SubtitleStyle if item["target"] == "subtitle" else HookStyle
                    item["style"] = asdict(model.from_dict(item["style"]))
                    if (not isinstance(item["id"], str) or not item["id"] or item["id"] in ids
                            or not isinstance(item["name"], str) or not item["name"].strip() or len(item["name"]) > 80
                            or item["name"].casefold() in names or type(item["version"]) is not int or item["version"] < 1):
                        raise ValueError("preset")
                    ids.add(item["id"]); names.add(item["name"].casefold())
                if data.get("default_id") is not None and data["default_id"] not in ids:
                    raise ValueError("default")
                for target, key in (("hook", "default_id"), ("subtitle", "subtitle_default_id")):
                    if data.get(key) and not any(p["id"] == data[key] and p["target"] == target for p in data["presets"]):
                        raise ValueError("default target")
                self.data = data
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise UserFacingError("Konfigurasi preset rusak atau versinya tidak didukung; file tidak ditimpa.") from error

    def _commit(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = dict(data, schema_version=3)
        atomic_json(self.path, data)
        self.data = data

    def default_style(self, target: str = "hook") -> dict:
        for item in self.data["presets"]:
            if item["target"] == target and item["id"] == self.data.get("subtitle_default_id" if target == "subtitle" else "default_id"):
                return dict(item["style"], preset_id=item["id"], preset_version=item["version"])
        return asdict(SubtitleStyle() if target == "subtitle" else HookStyle())

    def save(self, name: str, style: dict, update_id: str | None = None, target: str = "hook") -> dict:
        name = name.strip()
        if not name or len(name) > 80:
            raise UserFacingError("Nama preset wajib diisi, maksimal 80 karakter.")
        validated = (SubtitleStyle if target == "subtitle" else HookStyle).from_dict(style)
        actual_font = resolve_style_font(validated, SubtitleFont(default_font_path()))
        data = json.loads(json.dumps(self.data))
        for item in data["presets"]:
            if item["name"].casefold() == name.casefold() and item["id"] != update_id:
                raise UserFacingError("Nama preset sudah digunakan. Pilih nama lain atau pilih preset tersebut lalu Perbarui preset.")
        old = next((p for p in data["presets"] if p["id"] == update_id), None)
        if update_id and (old is None or old.get("target") != target):
            raise UserFacingError("Preset asal tidak tersedia. Simpan sebagai preset baru.")
        item = {"id": update_id or uuid4().hex, "name": name, "target": target, "version": old["version"] + 1 if old else 1,
                "style": dict(asdict(validated), font=font_reference(actual_font), preset_id=None, preset_version=None)}
        data["presets"] = [p for p in data["presets"] if p["id"] != item["id"]] + [item]
        self._commit(data)
        return item

    def set_default(self, preset_id: str | None, target: str = "hook") -> None:
        if preset_id is not None and not any(p["id"] == preset_id and p["target"] == target for p in self.data["presets"]):
            raise UserFacingError("Preset tidak tersedia.")
        self._commit(dict(self.data, **{("subtitle_default_id" if target == "subtitle" else "default_id"): preset_id}))

    def delete(self, preset_id: str) -> None:
        self._commit(dict(self.data, presets=[p for p in self.data["presets"] if p["id"] != preset_id],
                          default_id=None if self.data.get("default_id") == preset_id else self.data.get("default_id"),
                          subtitle_default_id=None if self.data.get("subtitle_default_id") == preset_id else self.data.get("subtitle_default_id")))

    def import_font(self, path: Path) -> dict:
        if path.suffix.lower() not in {".ttf", ".otf"}:
            raise UserFacingError("Pilih font .ttf atau .otf.")
        font = SubtitleFont(path, strict_subtitle=False)
        if any(c in font.raw.familyName() for c in ',\n\r'):
            raise UserFacingError("Nama keluarga font tidak kompatibel dengan ASS.")
        digest = file_sha256(path)
        cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "videogen" / "fonts"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / (digest + path.suffix.lower())
        if not target.exists() or file_sha256(target) != digest:
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copyfile(path, temporary)
            if file_sha256(temporary) != digest:
                temporary.unlink(missing_ok=True)
                raise UserFacingError("File font berubah saat diimpor; pilih kembali file yang stabil.")
            os.replace(temporary, target)
        return font_reference(SubtitleFont(target, strict_subtitle=False))
