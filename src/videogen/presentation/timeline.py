"""Three navigable tracks with output-time ruler and source trim handles."""
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class EditorTimeline(QWidget):
    seekRequested = Signal(float)
    segmentSelected = Signal(int)
    objectSelected = Signal(str)
    boundaryCommitted = Signal(int, str, float)
    interactionStarted = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(152)
        self.edit, self.cues, self.hook_end, self.position = None, [], 0.0, 0.0
        self.zoom, self.scroll, self.selected = 1.0, 0.0, -1
        self._drag = None
        self._regions = []
        self.setMouseTracking(True)

    @property
    def visible_duration(self):
        return max(.001, (self.edit.duration if self.edit else 1.0) / self.zoom)

    def x(self, seconds):
        return 78 + (seconds-self.scroll) / self.visible_duration * max(1, self.width()-86)

    def seconds(self, x):
        return self.scroll + (x-78) / max(1, self.width()-86) * self.visible_duration

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#20252e"))
        painter.setPen(QColor("#dce3ed"))
        for name, y in (("Video", 48), ("Hook", 85), ("Subtitle", 123)):
            painter.drawText(8, y, name)
        self._regions = []
        if not self.edit:
            painter.end()
            return
        step = max(.1, self.visible_duration/8)
        for i in range(9):
            seconds = self.scroll + i*step
            painter.drawText(int(self.x(seconds)), 17, f"{seconds:.1f}s")
        painter.setClipRect(QRectF(78, 24, self.width()-86, 125))
        cursor = 0.0
        for index, segment in enumerate(self.edit.segments):
            end = cursor + segment.end-segment.start
            box = QRectF(self.x(cursor), 28, max(1, self.x(end)-self.x(cursor)-2), 30)
            self._bar(painter, box, "#3687c8" if index == self.selected else "#34546e", f"{index+1} · {segment.start:.2f}–{segment.end:.2f}")
            self._regions.append(("video", index, box))
            painter.fillRect(QRectF(box.left(), box.top(), 4, box.height()), QColor("#71ceff"))
            painter.fillRect(QRectF(box.right()-4, box.top(), 4, box.height()), QColor("#71ceff"))
            cursor = end
        if self.hook_end > 0:
            box = QRectF(self.x(0), 66, max(1, self.x(self.hook_end)-self.x(0)), 29)
            self._bar(painter, box, "#6f5cb2", "HOOK")
            self._regions.append(("hook", -1, box))
        for index, cue in enumerate(self.cues):
            if cue.end < self.scroll or cue.start > self.scroll+self.visible_duration:
                continue
            box = QRectF(self.x(cue.start), 104, max(2, self.x(cue.end)-self.x(cue.start)-1), 29)
            self._bar(painter, box, "#a27a20" if cue.start <= self.position < cue.end else "#45604e", cue.text)
            self._regions.append(("subtitle", index, box))
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(int(self.x(self.position)), 24, int(self.x(self.position)), 144)
        if self._drag:
            painter.setPen(QPen(QColor("#2689ff"), 2))
            painter.drawLine(int(self._drag[4]), 24, int(self._drag[4]), 64)
        painter.end()

    @staticmethod
    def _bar(painter, rect, color, text):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QColor("#ffffff"))
        painter.save()
        painter.setClipRect(rect.adjusted(5, 0, -5, 0), Qt.ClipOperation.IntersectClip)
        painter.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.edit or event.position().x() < 78:
            return
        self.interactionStarted.emit()
        for target, index, rect in self._regions:
            if rect.contains(event.position()):
                if target == "video":
                    self.selected = index
                    self.segmentSelected.emit(index)
                    side = "start" if abs(event.position().x()-rect.left()) <= 7 else "end" if abs(event.position().x()-rect.right()) <= 7 else None
                    if side:
                        segment = self.edit.segments[index]
                        self._drag = (index, side, event.position().x(), getattr(segment, side), event.position().x())
                        self.grabMouse()
                        self.update()
                        return
                else:
                    self.objectSelected.emit(target)
                break
        self.seekRequested.emit(max(0.0, min(self.edit.duration-.001, self.seconds(event.position().x()))))
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag:
            self._drag = (*self._drag[:4], event.position().x())
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag:
            index, side, origin, source, current = self._drag
            self._drag = None
            self.releaseMouse()
            self.boundaryCommitted.emit(index, side, source + self.seconds(current)-self.seconds(origin))
            self.update()
