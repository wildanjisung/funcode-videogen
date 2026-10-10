"""Small Qt6/PySide6 adapter for the locally installed libopenshot build."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from PySide6.QtCore import Slot
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget


class _FrameSurface(QWidget):
    """Each player owns a receiver; late callbacks from released players are ignored."""
    def __init__(self, target):
        super().__init__(target)
        self.target, self.active = target, False
        self.hide()

    @Slot(QImage)
    def present(self, image):
        if self.active:
            self.target.present(image)


class LibOpenShotUnavailable(RuntimeError):
    pass


def load_openshot():
    """Load bundled-in-venv native libraries before importing the SWIG module."""
    prefix = Path(sys.prefix)
    library_dir = prefix / "lib"
    module_dir = library_dir / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if not module_dir.is_dir():
        raise LibOpenShotUnavailable(f"Binding Python libopenshot tidak ditemukan: {module_dir}")
    for path in (library_dir, module_dir):
        if path.is_dir() and str(path) not in sys.path:
            sys.path.insert(0, str(path))
    # QtPlayer and the SWIG extension have non-system dependencies in .venv/lib.
    ctypes.CDLL(str(library_dir / "libopenshot-audio.so.10"), mode=ctypes.RTLD_GLOBAL)
    ctypes.CDLL(str(library_dir / "libopenshot.so.32"), mode=ctypes.RTLD_GLOBAL)
    try:
        import openshot
    except Exception as error:
        raise LibOpenShotUnavailable(f"Binding libopenshot gagal dimuat: {type(error).__name__}: {error}") from error
    return openshot


class LibOpenShotPlayback:
    """Owns reader, timeline, and player for one portrait/landscape source."""

    def __init__(self, surface) -> None:
        self.openshot = load_openshot()
        self.reader = None
        self.clip = None
        self.timeline = None
        self._started = False
        self._pending_seek_frame: int | None = None
        self.player = self.openshot.QtPlayer()
        self._surface = _FrameSurface(surface)
        self.player.SetQWidget(self._surface)

    def open(self, source: Path, edit=None) -> dict:
        self.stop()
        reader = self.openshot.FFmpegReader(str(source.resolve()))
        reader.Open()
        timeline = self.openshot.Timeline(reader.info)
        if edit is not None:
            timeline.info.duration = edit.duration
            timeline.info.video_length = round(edit.duration * reader.info.fps.num / reader.info.fps.den)
        clips, cursor = [], 0.0
        if edit is None:
            clip = self.openshot.Clip(reader)
            timeline.AddClip(clip)
            clips.append(clip)
        else:
            for segment in edit.segments:
                clip = self.openshot.Clip(reader)
                clip.Start(segment.start)
                clip.End(segment.end)
                clip.Position(cursor)
                timeline.AddClip(clip)
                clips.append(clip)
                cursor += segment.end-segment.start
        timeline.Open()
        self.player.Reader(timeline)
        self._surface.active = True
        self.reader, self.clip, self.timeline = reader, clips, timeline
        info = reader.info
        fps = float(info.fps.num) / float(info.fps.den)
        return {"width": int(info.width), "height": int(info.height), "fps": fps,
                "duration": edit.duration if edit else float(info.duration), "audio_channels": int(info.channels),
                "sample_rate": int(info.sample_rate)}

    def play(self) -> None:
        self.player.Play()
        self._started = True
        if self._pending_seek_frame is not None:
            self.player.Seek(self._pending_seek_frame, False)
            self._pending_seek_frame = None

    def pause(self) -> None:
        self.player.Pause()

    def seek_seconds(self, seconds: float) -> None:
        if self.timeline is None:
            return
        fps = self.timeline.info.fps
        frame = max(1, round(seconds * fps.num / fps.den) + 1)
        if not self._started:
            self._pending_seek_frame = frame
        else:
            self.player.Seek(frame, False)

    def position_seconds(self) -> float:
        if self.timeline is None:
            return 0.0
        fps = self.timeline.info.fps
        return max(0, int(self.player.Position())-1) * fps.den / fps.num

    def stop(self) -> None:
        self._surface.active = False
        if getattr(self, "player", None) is not None:
            self.player.Stop()
        if getattr(self, "timeline", None) is not None:
            self.timeline.Close()
        if getattr(self, "reader", None) is not None:
            self.reader.Close()
        self.timeline = self.clip = self.reader = None
        self._started = False
        self._pending_seek_frame = None

    def close(self):
        self.stop()
        self._surface.deleteLater()
