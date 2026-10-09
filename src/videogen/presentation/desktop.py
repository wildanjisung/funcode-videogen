import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videogen.infrastructure.logging_config import default_log_path


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Video ke Subtitle")
        self.resize(620, 280)
        self.source: Path | None = None
        self.output_dir = Path.home() / "Videos" / "Videogen"
        self.log_path = default_log_path()
        self.last_result_dir: Path | None = None
        self._line_buffer = ""
        self._stopping = False
        self._terminal: dict | None = None

        self.file_label = QLabel("Belum ada video dipilih")
        self.output_label = QLabel(f"Folder hasil: {self.output_dir}")
        self.status_label = QLabel("Pilih satu video MP4 atau MOV.")
        self.choose_button = QPushButton("Pilih video")
        self.folder_button = QPushButton("Pilih folder hasil")
        self.process_button = QPushButton("Proses")
        self.open_button = QPushButton("Buka folder hasil")
        self.process_button.setEnabled(False)
        self.open_button.setEnabled(False)

        layout = QVBoxLayout()
        for widget in (
            self.file_label,
            self.choose_button,
            self.output_label,
            self.folder_button,
            self.process_button,
            self.status_label,
            self.open_button,
        ):
            layout.addWidget(widget)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.worker = QProcess(self)
        self.worker.setProgram(sys.executable)
        self.worker.readyReadStandardOutput.connect(self._read_worker_output)
        self.worker.readyReadStandardError.connect(self._read_worker_error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.errorOccurred.connect(self._worker_error)

        self.choose_button.clicked.connect(self._choose_file)
        self.folder_button.clicked.connect(self._choose_output)
        self.process_button.clicked.connect(self._start)
        self.open_button.clicked.connect(self._open_output)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pilih video",
            str(Path.home()),
            "Video (*.mp4 *.MP4 *.mov *.MOV)",
        )
        if path:
            self.source = Path(path)
            self.file_label.setText(str(self.source))
            self.process_button.setEnabled(True)

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Pilih folder hasil", str(self.output_dir))
        if selected:
            self.output_dir = Path(selected)
            self.output_label.setText(f"Folder hasil: {self.output_dir}")

    def _start(self) -> None:
        if not self.source:
            return
        self._line_buffer = ""
        self._terminal = None
        self._stopping = False
        self._set_busy(True)
        self.status_label.setText("Memulai worker…")
        self.worker.setArguments(
            [
                "-m", "videogen.worker_main",
                "--source", str(self.source),
                "--output", str(self.output_dir),
                "--log-file", str(self.log_path),
            ]
        )
        self.worker.start()

    def _read_worker_output(self) -> None:
        chunk = bytes(self.worker.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._line_buffer += chunk
        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "stage":
                self.status_label.setText(event.get("message", "Sedang memproses…"))
            elif event.get("type") == "completed":
                self._terminal = event
            elif event.get("type") == "failed":
                self._terminal = event
            elif event.get("type") == "cancelled":
                self._terminal = event

    def _read_worker_error(self) -> None:
        chunk = bytes(self.worker.readAllStandardError()).decode("utf-8", errors="replace")
        if chunk:
            self._append_diagnostic("worker stderr", chunk)

    def _worker_finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self._read_worker_output()
        self._set_busy(False)
        terminal = self._terminal or {}
        if terminal.get("type") == "completed" and exit_code == 0:
            self.status_label.setText(f"Selesai: {Path(terminal['video']).name}")
            self.open_button.setEnabled(True)
            self.last_result_dir = Path(terminal["video"]).parent
        elif terminal.get("type") == "cancelled" or self._stopping:
            self.status_label.setText("Proses dibatalkan.")
        else:
            message = terminal.get("message", "Worker berhenti sebelum menghasilkan output.")
            if terminal.get("log_path") is None:
                message = f"{message}\nLog: {self.log_path}"
            self.status_label.setText(f"Gagal: {message}")
            QMessageBox.warning(self, "Pemrosesan gagal", message)
        if self._stopping:
            self.close()

    def _worker_error(self, _error: QProcess.ProcessError) -> None:
        self._append_diagnostic("QProcess error", str(_error))
        if self.worker.state() == QProcess.ProcessState.NotRunning:
            message = f"Worker tidak dapat dijalankan. Log: {self.log_path}"
            self.status_label.setText(message)
            self._set_busy(False)

    def _append_diagnostic(self, label: str, detail: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as log_file:
                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
                log_file.write(f"{timestamp} ERROR videogen.ui: {label}: {detail.rstrip()}\n")
        except OSError:
            pass

    def _set_busy(self, busy: bool) -> None:
        self.choose_button.setEnabled(not busy)
        self.folder_button.setEnabled(not busy)
        self.process_button.setEnabled(not busy and self.source is not None)

    def _open_output(self) -> None:
        if self.last_result_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_result_dir)))

    def closeEvent(self, event) -> None:
        if self.worker.state() == QProcess.ProcessState.NotRunning:
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            "Batalkan pemrosesan?",
            "Video sedang diproses. Tutup aplikasi dan batalkan pekerjaan ini?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        event.ignore()
        self._stopping = True
        self.status_label.setText("Menghentikan proses…")
        pid = int(self.worker.processId())
        if pid > 0 and sys.platform.startswith("linux"):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            QTimer.singleShot(5000, self._force_stop)
        else:
            self.worker.terminate()
            QTimer.singleShot(5000, self.worker.kill)

    def _force_stop(self) -> None:
        if self.worker.state() == QProcess.ProcessState.NotRunning:
            return
        pid = int(self.worker.processId())
        if pid > 0 and sys.platform.startswith("linux"):
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            self.worker.kill()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
