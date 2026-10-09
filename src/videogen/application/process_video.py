import logging
import os
import shutil
import uuid
from pathlib import Path

from videogen.application.ports import (
    CheckCancelled,
    DependencyUnavailable,
    EmptyTranscription,
    MediaProcessor,
    Progress,
    SubtitleWriter,
    Transcriber,
    UserFacingError,
)
from videogen.domain.models import ProcessResult, build_cues, max_line_characters, validate_words

logger = logging.getLogger(__name__)


class ProcessVideo:
    def __init__(
        self,
        media: MediaProcessor,
        transcriber: Transcriber,
        subtitles: SubtitleWriter,
        font_path: Path,
    ) -> None:
        self._media = media
        self._transcriber = transcriber
        self._subtitles = subtitles
        self._font_path = font_path

    def execute(
        self,
        source: Path,
        output_directory: Path,
        progress: Progress,
        check_cancelled: CheckCancelled,
    ) -> ProcessResult:
        source = source.expanduser().resolve()
        output_directory = output_directory.expanduser().resolve()
        if not source.is_file():
            raise UserFacingError("File video tidak ditemukan.")
        if source.suffix.lower() not in {".mp4", ".mov"}:
            raise UserFacingError("Pilih file MP4 atau MOV.")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise DependencyUnavailable("FFmpeg dan ffprobe perlu terpasang di sistem.")
        if not self._font_path.is_file():
            raise DependencyUnavailable(
                "Font Helvetica Neue belum tersedia. Atur VIDEOGEN_FONT_PATH ke file .ttf/.otf Helvetica Neue."
            )

        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise UserFacingError("Folder hasil tidak dapat dibuat atau tidak dapat diakses.") from error
        if not os.access(output_directory, os.W_OK):
            raise UserFacingError("Folder hasil tidak dapat ditulis.")

        info = self._media.probe(source)
        job_id = uuid.uuid4().hex[:10]
        stem = f"{source.stem}_subtitled"
        staging = output_directory / f".{stem}_{job_id}.tmp"
        final_directory = output_directory / f"{stem}_{job_id}"
        try:
            staging.mkdir()
        except OSError as error:
            raise UserFacingError("Folder kerja sementara tidak dapat dibuat.") from error

        try:
            audio = staging / "audio.wav"
            ass = staging / "captions.ass"
            video = staging / f"{stem}.mp4"
            transcript = staging / f"{stem}.txt"
            srt = staging / f"{stem}.srt"

            check_cancelled()
            progress("audio", "Mengekstrak audio")
            self._media.extract_audio(source, audio, info)

            check_cancelled()
            progress("transcription", "Mentranskripsi audio")
            # Keep the complete audio transcript. Video clipping happens only after
            # applying the audio/video offset inside build_cues.
            words = validate_words(self._transcriber.transcribe(audio))
            if not words:
                raise EmptyTranscription("Ucapan tidak terdeteksi pada video ini.")

            cues = build_cues(words, info.duration, info.subtitle_offset, min(24, max_line_characters(info)))
            cues = self._subtitles.prepare_cues(info, cues)
            if not cues:
                raise EmptyTranscription("Transkrip tidak menghasilkan subtitle yang valid.")

            logger.info(
                "Timestamp accuracy evaluation: job_id=%s status=pending "
                "target_ms=200 measured_word_onset_error_ms=unmeasured "
                "reason=independent_spoken_word_annotations_required "
                "audio_video_offset_seconds=%.6f cue_count=%d",
                job_id, info.subtitle_offset, len(cues),
            )
            # Record timing samples without logging transcript contents.
            for label, index in (("awal", 0), ("tengah", len(cues) // 2), ("akhir", len(cues) - 1)):
                cue = cues[index]
                word = cue.words[0]
                logger.info(
                    "Timestamp evaluation sample: job_id=%s sample=%s cue_index=%d "
                    "cue_start_video_seconds=%.6f cue_end_video_seconds=%.6f "
                    "first_word_start_video_seconds=%.6f first_word_end_video_seconds=%.6f "
                    "has_word_timing=%s",
                    job_id, label, index, cue.start, cue.end, word.start, word.end, word.has_word_timing,
                )

            self._subtitles.write_transcript(transcript, words)
            self._subtitles.write_srt(srt, cues)
            self._subtitles.write_ass(ass, info, cues)

            check_cancelled()
            progress("render", "Merender video bersubtitle")
            self._media.render(source, ass, video, info)

            check_cancelled()
            for artifact in (video, transcript, srt):
                if not artifact.is_file() or artifact.stat().st_size == 0:
                    raise UserFacingError(f"Output tidak lengkap: {artifact.name}")

            audio.unlink(missing_ok=True)
            ass.unlink(missing_ok=True)
            staging.rename(final_directory)
            progress("completed", "Selesai")
            return ProcessResult(
                video_path=final_directory / video.name,
                transcript_path=final_directory / transcript.name,
                srt_path=final_directory / srt.name,
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
