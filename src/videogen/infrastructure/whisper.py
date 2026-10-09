import logging
from pathlib import Path

from videogen.application.ports import DependencyUnavailable, UserFacingError
from videogen.domain.models import Word

logger = logging.getLogger(__name__)


class FasterWhisperTranscriber:
    def __init__(self, model_path: Path, cpu_threads: int = 4) -> None:
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                str(model_path),
                device="cpu",
                compute_type="int8",
                cpu_threads=cpu_threads,
                num_workers=1,
                local_files_only=True,
            )
        except ImportError as error:
            logger.exception("faster-whisper import failed")
            raise DependencyUnavailable("faster-whisper belum terpasang. Pasang dependency aplikasi.") from error
        except Exception as error:
            logger.exception("Could not load transcription model at %s", model_path)
            raise DependencyUnavailable(
                "Model transkripsi lokal belum tersedia atau tidak dapat dimuat. Jalankan langkah setup model pada README.md terlebih dahulu."
            ) from error

    def transcribe(self, audio: Path) -> list[Word]:
        try:
            segments, info = self._model.transcribe(
                str(audio),
                language=None,
                task="transcribe",
                beam_size=5,
                vad_filter=True,
                word_timestamps=True,
                condition_on_previous_text=False,
            )
            logger.info(
                "Detected audio language: %s (probability %.3f)",
                info.language,
                info.language_probability,
            )
            words: list[Word] = []
            for segment in segments:
                if segment.words:
                    words.extend(
                        Word(word.word, float(word.start), float(word.end))
                        for word in segment.words
                    )
                else:
                    words.append(Word(segment.text, float(segment.start), float(segment.end)))
            return words
        except Exception as error:
            logger.exception("Transcription failed for audio file %s", audio)
            raise UserFacingError("Transkripsi gagal. Pastikan audio dapat dibaca dan coba lagi.") from error
