import json
import os
import shutil
import subprocess
import threading
from fractions import Fraction
from pathlib import Path

from videogen.application.ports import Cancelled, UnsupportedMedia, UserFacingError
from videogen.domain.models import Cue, MediaInfo


class FFmpegMediaProcessor:
    @staticmethod
    def check_environment() -> None:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise UserFacingError("FFmpeg dan ffprobe perlu terpasang di sistem.")
        checks = (
            ("filter=ass", "Subtitle libass tidak tersedia pada build FFmpeg."),
            ("encoder=libx264", "Encoder H.264 libx264 tidak tersedia pada build FFmpeg."),
        )
        for target, message in checks:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-h", target],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 or "Unknown" in result.stdout:
                raise UserFacingError(message)

    def probe(self, source: Path) -> MediaInfo:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_streams", "-show_format",
                "-of", "json", str(source),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise UnsupportedMedia("Video tidak dapat dibaca oleh FFmpeg.")
        try:
            payload = json.loads(result.stdout)
            streams = payload["streams"]
            videos = [
                item for item in streams
                if item.get("codec_type") == "video" and not item.get("disposition", {}).get("attached_pic")
            ]
            audios = [item for item in streams if item.get("codec_type") == "audio"]
            if not videos or not audios:
                raise ValueError("video/audio stream missing")
            video, audio = videos[0], audios[0]
            color_transfer = video.get("color_transfer", "unknown")
            side_data = " ".join(
                str(item.get("side_data_type", "")) for item in video.get("side_data_list", [])
            ).lower()
            if color_transfer in {"smpte2084", "arib-std-b67"} or "dovi" in side_data:
                raise UnsupportedMedia("Video HDR belum didukung. Gunakan salinan SDR.")

            width, height = int(video["width"]), int(video["height"])
            rotation = self._rotation(video)
            display_width, display_height = (
                (height, width) if abs(rotation) in {90, 270} else (width, height)
            )
            sar = self._fraction(video.get("sample_aspect_ratio", "1:1"))
            display_width = max(1, round(display_width * sar))
            duration = float(video.get("duration") or payload["format"]["duration"])
            if width <= 0 or height <= 0 or duration <= 0:
                raise ValueError("invalid media dimensions or duration")

            return MediaInfo(
                video_stream_index=int(video["index"]),
                audio_stream_index=int(audio["index"]),
                width=width,
                height=height,
                display_width=display_width,
                display_height=display_height,
                duration=duration,
                video_start=float(video.get("start_time", payload["format"].get("start_time", 0))),
                audio_start=float(audio.get("start_time", payload["format"].get("start_time", 0))),
                video_codec=video.get("codec_name", "unknown"),
                audio_codec=audio.get("codec_name", "unknown"),
                pixel_format=video.get("pix_fmt", "unknown"),
                color_transfer=color_transfer,
                sample_aspect_ratio=video.get("sample_aspect_ratio", "1:1"),
            )
        except UnsupportedMedia:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise UnsupportedMedia("Video perlu memiliki track video, audio, durasi, dan dimensi valid.") from error

    @staticmethod
    def _rotation(video: dict) -> int:
        for side_data in video.get("side_data_list", []):
            if "rotation" in side_data:
                return round(float(side_data["rotation"])) % 360
        return round(float(video.get("tags", {}).get("rotate", 0))) % 360

    @staticmethod
    def _fraction(value: str) -> float:
        try:
            return float(Fraction(value.replace(":", "/")))
        except (ValueError, ZeroDivisionError):
            return 1.0

    def extract_audio(self, source: Path, destination: Path, info: MediaInfo) -> None:
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", f"0:{info.audio_stream_index}", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(destination),
        ]
        self._run(command, "Gagal mengekstrak audio.")

    def render(self, source: Path, ass: Path, output: Path, info: MediaInfo) -> None:
        font_directory = Path(__file__).parents[1] / "presentation" / "resources"
        escaped_ass = self._filter_path(ass)
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", f"0:{info.video_stream_index}", "-map", f"0:{info.audio_stream_index}",
            "-vf", f"ass=filename='{escaped_ass}':fontsdir='{self._filter_path(font_directory)}',pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:black",
            "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "medium",
            "-crf", "18", "-pix_fmt", "yuv420p", "-map_metadata", "0",
            "-metadata:s:v:0", "rotate=0", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(output),
        ]
        self._run(command, "Gagal merender video bersubtitle.")
    @staticmethod
    def _filter_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")

    @staticmethod
    def _run(command: list[str], message: str) -> None:
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=False,
                creationflags=flags,
            )
        except FileNotFoundError as error:
            raise UserFacingError("FFmpeg tidak ditemukan. Periksa instalasi FFmpeg.") from error

        while True:
            if _CANCELLED.is_set():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise Cancelled("Proses dibatalkan.")
            try:
                _, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            detail = (stderr or "").strip().splitlines()
            suffix = f" ({detail[-1][:300]})" if detail else ""
            raise UserFacingError(message + suffix)


_CANCELLED = threading.Event()


def request_cancel(_signum: int, _frame: object) -> None:
    _CANCELLED.set()


def reset_cancel() -> None:
    _CANCELLED.clear()
