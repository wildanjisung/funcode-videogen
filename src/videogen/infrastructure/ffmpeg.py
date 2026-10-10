import json
import logging
import os
import re
import shutil
import subprocess
import threading
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from videogen.application.ports import Cancelled, UnsupportedMedia, UserFacingError
from videogen.domain.models import Cue, MediaInfo

logger = logging.getLogger(__name__)


class FFmpegMediaProcessor:
    def __init__(
        self, font_directory: Path | None = None,
        font_path: Path | None = None, expected_font: str | None = None,
    ) -> None:
        self._font_directory = font_directory or Path(__file__).parents[1] / "presentation" / "resources"
        self._font_path = font_path
        self._expected_font = expected_font
        self.progress = None
        self._hook_font_path: Path | None = None
        self._hook_font_name: str | None = None

    def configure_subtitle_font(self, path: Path, postscript_name: str) -> None:
        self._font_path, self._expected_font = path, postscript_name

    def configure_hook_font(self, path: Path, postscript_name: str) -> None:
        self._hook_font_path = path
        self._hook_font_name = postscript_name

    def _copy_fonts(self, folder: Path) -> None:
        for index, source in enumerate((self._font_path, self._hook_font_path)):
            if source is not None:
                shutil.copy2(source, folder / f"{index}{source.suffix}")

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
        if self._font_path is not None:
            # Load only the validated file; other fonts in its source directory
            # must not change which face libass selects.
            with TemporaryDirectory(prefix=".fonts-", dir=ass.parent) as folder:
                self._copy_fonts(Path(folder))
                self._render(source, ass, output, info, Path(folder))
        else:
            self._render(source, ass, output, info, self._font_directory)

    def render_edit(self, source, ass, output, info, edit, boundaries):
        """Normalize both streams to video time, cut together, then burn output-time ASS."""
        count = len(edit.segments)
        if not count:
            raise UserFacingError("Timeline kosong.")
        last = edit.segments[-1]
        tail_frame = max(value for value in boundaries if value < last.end-1e-9)
        tail_duration = last.end-tail_frame
        with TemporaryDirectory(prefix=".fonts-edit-", dir=ass.parent) as folder:
            self._copy_fonts(Path(folder))
            filters = []
            video = f"[0:{info.video_stream_index}]setpts=PTS-{info.video_start:g}/TB"
            audio = f"[0:{info.audio_stream_index}]asetpts=PTS-{info.video_start:g}/TB"
            filters.append(video + (f",split={count}" if count > 1 else ",null") + "".join(f"[v{i}]" for i in range(count)))
            filters.append(audio + (f",asplit={count}" if count > 1 else ",anull") + "".join(f"[a{i}]" for i in range(count)))
            for i, segment in enumerate(edit.segments):
                length = segment.end-segment.start
                filters.append(f"[v{i}]trim=start={segment.start:.9f}:end={segment.end:.9f},setpts=PTS-STARTPTS[cv{i}]")
                filters.append(f"[a{i}]atrim=start={segment.start:.9f}:end={segment.end:.9f},"
                    f"asetpts=PTS-{segment.start:.9f}/TB,aresample=async=1:first_pts=0,apad,atrim=duration={length:.9f}[ca{i}]")
            inputs = "".join(f"[cv{i}][ca{i}]" for i in range(count))
            filters.append(f"{inputs}concat=n={count}:v=1:a=1[cutv][outa]")
            filters.append(f"[cutv]ass=filename='{self._filter_path(ass)}':fontsdir='{self._filter_path(Path(folder))}',"
                "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:black[outv]")
            progress_file = Path(folder)/"progress.txt"
            command = ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info", "-y", "-copyts",
                "-i", str(source), "-filter_complex", ";".join(filters), "-map", "[outv]", "-map", "[outa]",
                "-fps_mode", "passthrough", "-enc_time_base", "demux", "-c:v", "libx264", "-bf", "0",
                "-bsf:v", f"setts=duration={tail_duration:.9f}/TB", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-metadata:s:v:0", "rotate=0",
                "-movflags", "+faststart", "-progress", str(progress_file), str(output)]
            stderr = self._run(command, "Gagal merender potongan video.", progress_file, edit.duration, self.progress)
            self._verify_font_selection(stderr, require_selection="Dialogue:" in ass.read_text(encoding="utf-8-sig"))

    def extract_preview_mapped(self, source, ass, output_time, source_time, output, info):
        with TemporaryDirectory(prefix=".fonts-mapped-") as folder:
            self._copy_fonts(Path(folder))
            filt = (f"setpts=PTS-{info.video_start:g}/TB,trim=start={source_time:.9f},"
                f"setpts=PTS-STARTPTS+{output_time:.9f}/TB,"
                f"ass=filename='{self._filter_path(ass)}':fontsdir='{self._filter_path(Path(folder))}',"
                "pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:black")
            command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-y", "-copyts",
                "-i", str(source), "-map", f"0:{info.video_stream_index}", "-frames:v", "1", "-vf", filt,
                "-update", "1", str(output)]
            stderr = self._run(command, "Gagal membuat preview hasil potongan.")
            self._verify_font_selection(stderr, require_selection=False)

    def extract_preview(self, source: Path, ass: Path, timestamp: float, output: Path, info: MediaInfo) -> None:
        directory = self._font_directory
        if self._font_path is not None:
            with TemporaryDirectory(prefix=".fonts-preview-") as folder:
                self._copy_fonts(Path(folder))
                self._extract_preview(source, ass, timestamp, output, info, Path(folder))
        else:
            self._extract_preview(source, ass, timestamp, output, info, directory)

    def _extract_preview(self, source: Path, ass: Path, timestamp: float, output: Path,
                         info: MediaInfo, font_directory: Path) -> None:
        filt = f"ass=filename='{self._filter_path(ass)}':fontsdir='{self._filter_path(font_directory)}',pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:black"
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-y",
                   "-ss", f"{timestamp:.4f}", "-copyts", "-i", str(source), "-map", f"0:{info.video_stream_index}",
                   "-frames:v", "1", "-vf", filt, "-update", "1", str(output)]
        stderr = self._run(command, "Gagal membuat preview hook.")
        self._verify_font_selection(stderr, require_selection=False)

    def _render(self, source: Path, ass: Path, output: Path, info: MediaInfo, font_directory: Path) -> None:
        escaped_ass = self._filter_path(ass)
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info", "-y",
            "-i", str(source), "-map", f"0:{info.video_stream_index}", "-map", f"0:{info.audio_stream_index}",
            "-vf", f"ass=filename='{escaped_ass}':fontsdir='{self._filter_path(font_directory)}',pad=ceil(iw/2)*2:ceil(ih/2)*2:0:0:black",
            "-fps_mode", "passthrough", "-c:v", "libx264", "-preset", "medium",
            "-crf", "18", "-pix_fmt", "yuv420p", "-map_metadata", "0",
            "-metadata:s:v:0", "rotate=0", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(output),
        ]
        with TemporaryDirectory(prefix=".progress-", dir=ass.parent) as folder:
            progress_file = Path(folder)/"encoding.txt"
            command[1:1] = ["-progress", str(progress_file)]
            stderr = self._run(command, "Gagal merender video bersubtitle.", progress_file, info.duration, self.progress)
        self._verify_font_selection(stderr)

    def _verify_font_selection(self, stderr: str, require_selection: bool = True) -> None:
        selections = [line for line in stderr.splitlines() if "fontselect:" in line]
        for line in selections:
            logger.info("libass %s", line.strip())
        if self._expected_font is not None and (selections or require_selection):
            def normalized(value: str) -> str:
                return re.sub(r"[^a-z0-9]", "", value.lower())
            failed = not selections
            for line in selections:
                requested = line.split("fontselect:", 1)[-1].split(",", 1)[0].strip().lstrip("(")
                expected = self._hook_font_name if self._hook_font_name and requested == self._hook_font_name else self._expected_font
                if "->" not in line or normalized(line.rsplit(",", 1)[-1]) != normalized(expected):
                    failed = True
            if failed:
                raise UserFacingError("Font render berbeda dari font tervalidasi. Periksa log pemilihan font; hasil tidak diterbitkan.")

    @staticmethod
    def _filter_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,").replace("[", "\\[").replace("]", "\\]")

    @staticmethod
    def _run(command: list[str], message: str, progress_file: Path | None = None, duration: float = 0, progress=None) -> str:
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

        last_percent = -1
        position = 0
        buffer = ""
        def report():
            nonlocal last_percent, position, buffer
            if not progress_file or not progress or duration <= 0:
                return
            try:
                with progress_file.open() as source:
                    source.seek(position)
                    buffer += source.read()
                    position = source.tell()
            except OSError:
                return
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if line.startswith("out_time_us="):
                    try:
                        percent = min(99, max(0, int(float(line.split("=", 1)[1])/1_000_000/duration*100)))
                    except ValueError:
                        continue
                    if percent > last_percent:
                        last_percent = percent
                        progress("encoding", "Encoding", percent, "ffmpeg_output_time")

        def report_safe():
            try:
                report()
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                raise

        while True:
            report_safe()
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
        report_safe()
        if process.returncode:
            detail = (stderr or "").strip().splitlines()
            suffix = f" ({detail[-1][:300]})" if detail else ""
            raise UserFacingError(message + suffix)
        return stderr or ""


_CANCELLED = threading.Event()


def request_cancel(_signum: int, _frame: object) -> None:
    _CANCELLED.set()


def reset_cancel() -> None:
    _CANCELLED.clear()
