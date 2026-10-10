"""libass bitmap compositor; uses the same ASS/font files as FFmpeg.

ABI reference: https://github.com/libass/libass/blob/master/libass/ass.h
"""
import ctypes as C
from ctypes.util import find_library

from PySide6.QtGui import QColor, QImage, QPainter


class ASSImage(C.Structure):
    pass


ASSImage._fields_ = [("w", C.c_int), ("h", C.c_int), ("stride", C.c_int),
    ("bitmap", C.c_void_p), ("color", C.c_uint32), ("dst_x", C.c_int),
    ("dst_y", C.c_int), ("next", C.POINTER(ASSImage)), ("type", C.c_int)]


class ASSOverlay:
    def __init__(self, ass, fonts, width, height):
        library = find_library("ass")
        if not library:
            raise RuntimeError("Library libass tidak tersedia untuk overlay playback.")
        self.api = C.CDLL(library)
        signatures = {
            "ass_library_init": ([], C.c_void_p),
            "ass_library_done": ([C.c_void_p], None),
            "ass_renderer_init": ([C.c_void_p], C.c_void_p),
            "ass_renderer_done": ([C.c_void_p], None),
            "ass_add_font": ([C.c_void_p, C.c_char_p, C.c_char_p, C.c_int], None),
            "ass_set_fonts": ([C.c_void_p, C.c_char_p, C.c_char_p, C.c_int, C.c_char_p, C.c_int], None),
            "ass_set_frame_size": ([C.c_void_p, C.c_int, C.c_int], None),
            "ass_set_storage_size": ([C.c_void_p, C.c_int, C.c_int], None),
            "ass_read_file": ([C.c_void_p, C.c_char_p, C.c_char_p], C.c_void_p),
            "ass_free_track": ([C.c_void_p], None),
            "ass_render_frame": ([C.c_void_p, C.c_void_p, C.c_longlong, C.POINTER(C.c_int)], C.POINTER(ASSImage)),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.library = self.renderer = self.track = None
        self.width, self.height = width, height
        self._cache = None
        try:
            self.library = self.api.ass_library_init()
            if not self.library:
                raise RuntimeError("Inisialisasi libass gagal.")
            for path in set(fonts):
                payload = path.read_bytes()
                self.api.ass_add_font(self.library, path.name.encode(), payload, len(payload))
            self.renderer = self.api.ass_renderer_init(self.library)
            if not self.renderer:
                raise RuntimeError("Renderer libass gagal.")
            self.api.ass_set_frame_size(self.renderer, width, height)
            self.api.ass_set_storage_size(self.renderer, width, height)
            # Only the validated memory fonts may satisfy font selection.
            self.api.ass_set_fonts(self.renderer, None, None, 0, None, 1)
            self.track = self.api.ass_read_file(self.library, str(ass).encode(), b"UTF-8")
            if not self.track:
                raise RuntimeError("Track ASS tidak dapat dibaca.")
        except Exception:
            self.close()
            raise

    def layer(self, seconds):
        changed = C.c_int()
        pointer = self.api.ass_render_frame(self.renderer, self.track, round(seconds * 1000), C.byref(changed))
        if self._cache is not None and not changed.value:
            return self._cache
        image = QImage(self.width, self.height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        try:
            while pointer:
                item = pointer.contents
                if item.w > 0 and item.h > 0 and item.bitmap:
                    # Last row has only w allocated bytes, not necessarily stride.
                    data = C.string_at(item.bitmap, item.stride * (item.h - 1) + item.w)
                    data += bytes(item.stride - item.w)
                    alpha = QImage(data, item.w, item.h, item.stride, QImage.Format.Format_Alpha8).copy()
                    glyph = QImage(item.w, item.h, QImage.Format.Format_ARGB32_Premultiplied)
                    color = item.color
                    glyph.fill(QColor((color >> 24) & 255, (color >> 16) & 255, (color >> 8) & 255))
                    glyph.setAlphaChannel(alpha)
                    painter.setOpacity((255 - (color & 255)) / 255)
                    painter.drawImage(item.dst_x, item.dst_y, glyph)
                pointer = item.next
        finally:
            painter.end()
        self._cache = image
        return image

    def compose(self, image, seconds):
        result = image.copy()
        painter = QPainter(result)
        try:
            painter.drawImage(result.rect(), self.layer(seconds))
        finally:
            painter.end()
        return result

    def close(self):
        if self.track:
            self.api.ass_free_track(self.track)
            self.track = None
        if self.renderer:
            self.api.ass_renderer_done(self.renderer)
            self.renderer = None
        if self.library:
            self.api.ass_library_done(self.library)
            self.library = None
