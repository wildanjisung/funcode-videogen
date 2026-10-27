import logging
import struct
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QRawFont

from videogen.application.ports import DependencyUnavailable, UserFacingError
from videogen.infrastructure.paths import cached_asset

logger = logging.getLogger(__name__)
_application: QGuiApplication | None = None
_loaded_fonts: dict[tuple[str, int, int], int] = {}


def default_font_path() -> Path:
    return cached_asset("VIDEOGEN_FONT_PATH", "fonts/helvetica-neue/HelveticaNeueBold.otf")


class SubtitleFont:
    """Validate and measure the same font file supplied to libass."""

    def __init__(self, path: Path, *, strict_subtitle: bool = True) -> None:
        global _application
        self.path = path.expanduser().resolve()
        try:
            with self.path.open("rb") as source:
                source.read(1)
        except OSError as error:
            raise DependencyUnavailable(
                "Font Helvetica Neue Bold tidak dapat dibaca. Atur VIDEOGEN_FONT_PATH "
                "ke file .ttf/.otf yang valid; lihat setup font pada README.md."
            ) from error
        if QGuiApplication.instance() is None:
            # The worker needs font metrics, but no display or event loop.
            _application = QGuiApplication(["videogen-fonts", "-platform", "offscreen"])
        self.raw = QRawFont(str(self.path), 18, QFont.HintingPreference.PreferNoHinting)
        if not self.raw.isValid():
            raise DependencyUnavailable("File font rusak atau bukan font TrueType/OpenType yang valid.")
        if strict_subtitle and (self.raw.familyName() != "Helvetica Neue" or self.raw.weight() != 700 or self.raw.style() != QFont.Style.StyleNormal):
            raise DependencyUnavailable(
                f"Font harus Helvetica Neue Bold non-italic; ditemukan "
                f"{self.raw.familyName()} {self.raw.styleName()} (weight {self.raw.weight()})."
            )
        self.postscript_name = self._postscript_name()
        if any(char in self.postscript_name for char in ",\n\r"):
            raise DependencyUnavailable("Nama PostScript font tidak kompatibel dengan ASS.")
        stat = self.path.stat()
        key = (str(self.path), stat.st_mtime_ns, stat.st_size)
        font_id = _loaded_fonts.get(key, -1)
        if font_id < 0:
            font_id = QFontDatabase.addApplicationFont(str(self.path))
            if font_id >= 0:
                _loaded_fonts[key] = font_id
        if font_id < 0:
            raise DependencyUnavailable("Font Helvetica Neue Bold tidak dapat dimuat untuk pengukuran teks.")
        self._metrics: dict[int, QFontMetricsF] = {}
        logger.info(
            "Subtitle font validated: path=%s family=%s style=%s weight=%s postscript=%s",
            self.path, self.raw.familyName(), self.raw.styleName(), self.raw.weight(), self.postscript_name,
        )

    def _postscript_name(self) -> str:
        data = bytes(self.raw.fontTable("name"))
        try:
            _, count, offset = struct.unpack_from(">HHH", data)
            for index in range(count):
                platform, _, _, name_id, length, location = struct.unpack_from(">HHHHHH", data, 6 + 12 * index)
                if name_id == 6:
                    value = data[offset + location:offset + location + length]
                    return value.decode("utf-16-be" if platform in (0, 3) else "mac_roman")
        except (struct.error, UnicodeError) as error:
            raise DependencyUnavailable("Metadata nama font tidak valid.") from error
        raise DependencyUnavailable("Font tidak memiliki nama PostScript untuk verifikasi render.")

    def metrics(self, size: int) -> QFontMetricsF:
        if size not in self._metrics:
            font = QFont(self.raw.familyName())
            font.setWeight(QFont.Weight(self.raw.weight()))
            font.setStyle(self.raw.style())
            font.setStyleName(self.raw.styleName())
            font.setPixelSize(size)
            font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
            selected = QRawFont.fromFont(font)
            if bytes(selected.fontTable("head")) != bytes(self.raw.fontTable("head")):
                raise DependencyUnavailable("Qt memilih font pengganti saat mengukur subtitle.")
            self._metrics[size] = QFontMetricsF(font)
        return self._metrics[size]

    def width(self, text: str, size: int) -> float:
        metrics = self.metrics(size)
        bounds = metrics.boundingRect(text)
        return max(metrics.horizontalAdvance(text), bounds.right()) - min(0.0, bounds.left())

    def validate_text(self, text: str) -> None:
        if any(not self.raw.supportsCharacter(ord(char)) for char in text if not char.isspace()):
            raise UserFacingError("Teks memiliki karakter yang tidak tersedia pada font yang dipilih.")
