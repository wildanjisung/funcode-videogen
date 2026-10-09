# Videogen MVP 0

Desktop tool internal: pilih video, transkripsi audio lokal, render subtitle, simpan MP4, TXT, dan SRT.
Bahasa ucapan dideteksi otomatis; sudah mencakup input Bahasa Indonesia dan Inggris.

## Linux setup

Requires Python 3.11+, FFmpeg with `libass` and `libx264`, and enough free disk space for the transcription model and rendered video.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
mkdir -p .cache/models/small
.venv/bin/hf download Systran/faster-whisper-small --local-dir .cache/models/small
.venv/bin/videogen
```

The model download is a one-time setup. Video processing does not download a model. The UI processes one MP4 or MOV at a time and writes completed results to `~/Videos/Videogen` by default.

Set `VIDEOGEN_MODEL_PATH` to use a different local model directory. MVP 0 expects a multilingual faster-whisper model compatible with `small`.

Dependency compatibility: PyAV is constrained to `<19` because the current faster-whisper audio decoder still calls an API removed in PyAV 19. Reinstall dependencies with `.venv/bin/pip install -e .` after pulling project updates.

## Log aplikasi

Log diagnostik disimpan lokal di `${XDG_STATE_HOME:-~/.local/state}/videogen/videogen.log` (default Linux: `~/.local/state/videogen/videogen.log`). Jika pemrosesan gagal, lokasi log juga ditampilkan pada pesan error. Log mencatat tahap proses dan detail teknis termasuk traceback untuk membantu diagnosis; tiga file log lama disimpan saat log aktif mencapai 2 MB. Periksa log sebelum mencoba ulang atau saat melaporkan masalah. Log tidak berisi isi transkrip.

See [MVP 0 scope](MVP_0.md) and [technical architecture](ARSITEKTUR_TEKNIS.md).
