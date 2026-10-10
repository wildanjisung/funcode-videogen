"""Visual selection and text input; exported pixels always come from ASS."""
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QPlainTextEdit, QWidget


class HookTextInput(QPlainTextEdit):
    finished = Signal(bool)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.finished.emit(True)
            event.accept()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.finished.emit(False)
            event.accept()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.finished.emit(False)


class HookPreview(QLabel):
    interactionPressed = Signal()
    interactionReleased = Signal()
    gestureStarted = Signal()
    gestureChanged = Signal(float, float, float, float)  # top, center, width, requested font/H
    gestureFinished = Signal(bool)
    textStarted = Signal()
    textChanged = Signal(str)
    textFinished = Signal(bool)
    framePresented = Signal(float)

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMouseTracking(True)
        self._editing = False
        self.native_active = True
        self.frame_clock = None
        self.frame_compositor = None
        self.last_native_frame = None
        self._native_pixmap = None
        self.last_native_time = 0.0
        self.target = "hook"
        self.source_size = None
        self._selected = True
        self._top, self._center, self._width, self._size = .15, .5, .84, .03
        self._block_fraction = .10
        self._validated = False
        self._drag = None
        self._pending_drag = None
        self.gesture_reason = None
        self.gesture_mode = None
        self._text_active = False
        self._text_value = ""
        self.input = HookTextInput(self)
        self.input.setPlaceholderText("Tulis hook · Ctrl+Enter selesai")
        self.input.hide()
        self.input.textChanged.connect(lambda: self.textChanged.emit(self.input.toPlainText()) if self._text_active else None)
        self.input.finished.connect(self.finish_text)

    @Slot(QImage)
    def present(self, image: QImage) -> None:
        """QtPlayer callback; QImage is copied before native frame release."""
        if not self.native_active:
            return
        self.last_native_frame = image.copy()
        self.last_native_time = self.frame_clock() if self.frame_clock else 0.0
        frame = self.frame_compositor(image, self.last_native_time) if self.frame_compositor else image.copy()
        self._native_pixmap = QPixmap.fromImage(frame)
        self.setPixmap(self._native_pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self.framePresented.emit(self.last_native_time)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.native_active and self._native_pixmap:
            self.setPixmap(self._native_pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def set_editor(self, active: bool) -> None:
        self.cancel_gesture()
        if not active:
            self.finish_text(True)
        self._editing = active
        self._selected = True
        self.unsetCursor()
        self.update()

    def set_layout(self, top: float, width: float, height_fraction: float | None = None,
                   validated: bool = False, *, center: float = .5, size: float = .03) -> None:
        self._top, self._center, self._width, self._size = top, center, width, size
        if height_fraction is not None:
            self._block_fraction = max(.001, height_fraction)
        self._validated = validated
        if self._text_active:
            self.position_input()
        self.update()

    def image_rect(self) -> QRectF:
        gesture = self._drag or self._pending_drag
        if gesture:
            return QRectF(gesture[-1])
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return QRectF()
        ratio = pixmap.devicePixelRatio()
        width, height = pixmap.width()/ratio, pixmap.height()/ratio
        content = self.contentsRect()
        x, y = content.x() + (content.width()-width)/2, content.y() + (content.height()-height)/2
        if self.source_size:
            source_w, source_h = self.source_size
            width *= source_w/(source_w+source_w%2)
            height *= source_h/(source_h+source_h%2)
        return QRectF(x, y, width, height)

    def selection_rect(self) -> QRectF:
        image = self.image_rect()
        box = QRectF(image.x() + image.width()*(self._center-self._width/2),
                      image.y() + image.height()*(self._top-(self._block_fraction/2 if self.target == "subtitle" else 0)), image.width()*self._width,
                      image.height()*self._block_fraction)
        if image.isEmpty():
            return box
        # Keep editing handles reachable even when the requested layout is outside
        # the video. This is a selection proxy; exported geometry stays unchanged.
        inset = min(10., image.width()/4, image.height()/4)
        area = image.adjusted(inset, inset, -inset, -inset)
        width = min(max(12., box.width()), area.width())
        height = min(max(12., box.height()), area.height())
        return QRectF(min(max(box.x(), area.left()), area.right()-width),
                      min(max(box.y(), area.top()), area.bottom()-height), width, height)

    def handles(self):
        box = self.selection_rect()
        return [("width", QRectF(box.left()-7, box.center().y()-9, 14, 18)),
                ("width", QRectF(box.right()-7, box.center().y()-9, 14, 18)),
                *[("size", QRectF(p.x()-8, p.y()-8, 16, 16))
                  for p in (box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight())]]

    def _hit(self, point):
        hits = [( (point.x()-rect.center().x())**2 + (point.y()-rect.center().y())**2, 0 if mode == "size" else 1, mode)
                for mode, rect in self.handles() if rect.contains(point)]
        if hits:
            return min(hits)[2]
        box = self.selection_rect()
        if box.adjusted(-8, -8, 8, 8).contains(point):
            return "move"
        return None

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._editing or not self._selected or self.image_rect().isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        image = self.image_rect()
        painter.setClipRect(image)
        # Blue during a gesture denotes the active object, not a valid preview.
        active_or_valid = self._drag is not None or self._pending_drag is not None or self._validated
        pen = QPen(QColor("#2689ff" if active_or_valid else "#ffc542"), 2)
        if not active_or_valid:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        box = self.selection_rect()
        painter.drawRect(box)
        painter.setBrush(pen.color())
        for _, rect in self.handles():
            painter.drawRoundedRect(rect, 2, 2)
        painter.setPen(QPen(QColor("#57d8e8"), 1, Qt.PenStyle.DashLine))
        if abs(self._center-.5) < .015:
            painter.drawLine(QPointF(image.center().x(), image.top()), QPointF(image.center().x(), image.bottom()))
        if abs(self._top+(0 if self.target == "subtitle" else self._block_fraction/2)-.5) < .015:
            painter.drawLine(QPointF(image.left(), image.center().y()), QPointF(image.right(), image.center().y()))
        painter.end()

    def mousePressEvent(self, event) -> None:
        point = event.position()
        image = self.image_rect()
        if self._editing and event.button() == Qt.MouseButton.LeftButton and image.contains(point):
            self.finish_text(False)
            if self.selection_rect().contains(point):
                self._selected = True
            mode = self._hit(point) if self._selected else None
            if mode:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self._pending_drag = (mode, QPointF(point), self._top, self._center, self._width, self._size, self._block_fraction, QRectF(image))
                self.interactionPressed.emit()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._editing and self.target == "hook" and self.selection_rect().contains(event.position()):
            self.cancel_gesture("double_click")
            self.start_text()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pending_drag:
            if not event.buttons() & Qt.MouseButton.LeftButton:
                self.cancel_gesture("button_lost")
            elif (event.position()-self._pending_drag[1]).manhattanLength() >= QApplication.startDragDistance():
                self._drag, self._pending_drag = self._pending_drag, None
                self.gesture_mode = self._drag[0]
                self.gesture_reason = None
                self.gestureStarted.emit()
                if self._drag:
                    self.grabMouse()
            else:
                event.accept()
                return
        if self._drag:
            if not event.buttons() & Qt.MouseButton.LeftButton:
                self.cancel_gesture("button_lost")
                event.accept()
                return
            mode, origin, top, center, width, size, block, image = self._drag
            point = event.position()
            if mode == "move":
                self._center = center+(point.x()-origin.x())/image.width()
                self._top = top+(point.y()-origin.y())/image.height()
            elif mode == "width":
                self._width = min(1, max(.01, 2*abs(point.x()-(image.x()+image.width()*center))/image.width()))
            else:
                # The resize gesture uses the reachable selection proxy, including
                # layouts whose real bounds are beyond the image.
                current_top, current_center = self._top, self._center
                current_width, current_block = self._width, self._block_fraction
                self._top, self._center, self._width, self._block_fraction = top, center, width, block
                pivot = self.selection_rect().center()
                self._top, self._center, self._width, self._block_fraction = current_top, current_center, current_width, current_block
                initial = max(1, (origin-pivot).manhattanLength())
                scale = max(.01, (point-pivot).manhattanLength()/initial)
                self._size = min(1, max(.0001, size*scale))
                self._block_fraction = max(.001, block*scale)
            self._validated = False
            self.gestureChanged.emit(self._top, self._center, self._width, self._size)
            self.update()
            event.accept()
            return
        if self._editing:
            mode = self._hit(event.position()) if self.image_rect().contains(event.position()) else None
            self.setCursor(Qt.CursorShape.SizeHorCursor if mode == "width" else Qt.CursorShape.SizeFDiagCursor if mode == "size" else Qt.CursorShape.SizeAllCursor if mode == "move" else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pending_drag and event.button() == Qt.MouseButton.LeftButton:
            self._pending_drag = None
            self.interactionReleased.emit()
            self.update()
            event.accept()
            return
        if self._drag and event.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            self.gesture_reason = "released"
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
            self.gestureFinished.emit(False)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def cancel_gesture(self, reason: str = "cancelled") -> bool:
        pending = self._pending_drag is not None
        self._pending_drag = None
        if self._drag:
            _, _, self._top, self._center, self._width, self._size, self._block_fraction, _ = self._drag
            self._drag = None
            self.gesture_reason = reason
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
            self.gestureChanged.emit(self._top, self._center, self._width, self._size)
            self.gestureFinished.emit(True)
            self.update()
            return True
        if pending:
            self.interactionReleased.emit()
            self.update()
        return pending

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.UngrabMouse and hasattr(self, "_drag"):
            self.cancel_gesture("capture_lost")
        return super().event(event)

    def start_text(self) -> None:
        if self._text_active:
            return
        self._text_active = True
        self.input.blockSignals(True)
        self.input.setPlainText(self._text_value)
        self.input.blockSignals(False)
        self.input.document().clearUndoRedoStacks()
        self.position_input()
        self.input.show()
        self.input.setFocus()
        self.textStarted.emit()

    def position_input(self) -> None:
        rect = self.selection_rect().intersected(self.image_rect())
        if not rect.isEmpty():
            rect.setHeight(min(max(rect.height(), 65), self.image_rect().bottom()-rect.top()))
            self.input.setGeometry(rect.toAlignedRect())

    def finish_text(self, cancelled: bool = False) -> bool:
        if not self._text_active:
            return False
        self._text_active = False
        self.input.hide()
        self.textFinished.emit(cancelled)
        return True

    def focusOutEvent(self, event) -> None:
        self.cancel_gesture("focus_lost")
        super().focusOutEvent(event)

    def resizeEvent(self, event) -> None:
        self.cancel_gesture("resize")
        super().resizeEvent(event)
        if self._text_active:
            self.position_input()
