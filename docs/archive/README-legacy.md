# Arsip README sebelum UI web menjadi panduan utama

Snapshot dokumentasi per 27 Oktober 2026. Dokumen ini mempertahankan campuran panduan desktop dan web sebelumnya untuk riwayat; beberapa alur dan path di bawah sudah tidak menjadi panduan utama.

Untuk instalasi, penggunaan, dan laporan bug versi web terbaru, baca [README utama](../../README.md).

---

# Videogen

Tool lokal dengan UI web dan desktop: transkripsi audio, edit hook/subtitle, preview, lalu render MP4, TXT, dan SRT.
Bahasa ucapan dideteksi otomatis; sudah mencakup input Bahasa Indonesia dan Inggris.

## UI web lokal

UI web memakai worker Python yang sama dan tidak memerlukan Node.js, libopenshot, atau library overlay playback terpisah. Python 3.11–3.13, FFmpeg/ffprobe dengan libass/libx264, model lokal, serta font tetap diperlukan. Qt/PySide6 masih dipakai secara headless untuk pengukuran font.

Jika setup model dan font pada checkout ini sudah tersedia:

```bash
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/videogen-web --data-dir output/web
```

Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[web]"
.venv\Scripts\videogen-web.exe --data-dir output\web
```

Buka **http://127.0.0.1:8765**. Pilih video, tunggu transkripsi, tulis hook atau matikan hook, atur gaya, lalu pilih **Perbarui preview** dan **Render MP4**. Hasil tersedia sebagai MP4, TXT, dan SRT; setiap render menjadi revisi baru.

[Panduan lengkap Windows/macOS/Linux, alur penggunaan, lokasi data, dan batas verifikasi](../../WEB_UI.md).

Subtitle sekarang memakai frasa pendek (maksimal empat kata dan target 2,5 detik per cue), Helvetica Neue tebal, teks putih dengan stroke gelap tipis, dan kata aktif kuning. Setelah kata selesai, warnanya kembali putih; saat jeda seluruh frasa putih. Pusat subtitle berada pada 74% tinggi frame. Timestamp kata mengikuti offset audio/video. Jika model hanya memberikan timing segmen, segmen ditampilkan putih tanpa highlight kata palsu.

Font lokal default: `.cache/fonts/helvetica-neue/HelveticaNeueBold.otf`. Atur `VIDEOGEN_FONT_PATH` ke file Helvetica Neue Bold non-italic `.otf`/`.ttf` lain bila diperlukan. Sebelum transkripsi, aplikasi memeriksa keterbacaan file, format font, family, dan weight 700. Log render mencatat nama font yang benar-benar dipilih libass; substitusi font membuat proses gagal sebelum hasil diterbitkan.

Layout diukur menggunakan file font yang sama dengan render. Kata panjang dan fallback segmen dibungkus maksimal dua baris, lalu ukuran font dikurangi bila perlu hingga minimum 18 piksel. Teks yang masih tidak muat menghasilkan pesan gagal yang jelas. Kata dengan timing bertumpang tindih tetap berada pada satu cue agar interval ucapan tidak terpotong.

Font untuk preview lokal diunduh dari [Font.Download](https://font.download/font/helvetica-neue-5), yang mencantumkan penggunaan personal. File disimpan di cache, tidak disertakan dalam paket aplikasi. Untuk penggunaan komersial/distribusi, sediakan font dengan lisensi yang sesuai; [Neue Helvetica resmi](https://www.myfonts.com/collections/neue-helvetica-font-linotype). Metadata sumber unduhan ada di folder cache font.

Highlight dan style tertanam pada MP4. SRT tetap teks biasa dengan timing cue; TXT tetap transkrip lengkap. Spesifikasi MVP 0 di bawah merupakan dokumentasi tahap awal.

## Linux setup

Requires Python 3.11+, FFmpeg with `libass` and `libx264`, and enough free disk space for the transcription model and rendered video.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
mkdir -p .cache/models/small
.venv/bin/hf download Systran/faster-whisper-small --local-dir .cache/models/small
```

### Setup font

Jalankan dari root checkout. Sediakan Helvetica Neue **Bold**, bukan Regular atau Italic. Bila sudah memiliki file font:

```bash
export VIDEOGEN_FONT_PATH="/absolute/path/HelveticaNeueBold.otf"
.venv/bin/python -c 'from videogen.infrastructure.fonts import SubtitleFont, default_font_path; font = SubtitleFont(default_font_path()); print(font.raw.familyName(), font.raw.styleName(), font.postscript_name)'
.venv/bin/videogen
```

Untuk preview personal memakai sumber unduhan lokal yang sama:

```bash
mkdir -p .cache/fonts/helvetica-neue
curl -fL https://font.download/dl/font/helvetica-neue-5.zip -o .cache/fonts/helvetica-neue.zip
unzip -j -o .cache/fonts/helvetica-neue.zip HelveticaNeueBold.otf -d .cache/fonts/helvetica-neue
.venv/bin/python -c 'from videogen.infrastructure.fonts import SubtitleFont, default_font_path; font = SubtitleFont(default_font_path()); print(font.raw.familyName(), font.raw.styleName(), font.postscript_name)'
.venv/bin/videogen
```

Hasil pemeriksaan yang diharapkan: `Helvetica Neue Bold HelveticaNeue-Bold`. `VIDEOGEN_FONT_PATH` memiliki prioritas atas cache default; gunakan path absolut ketika menjalankan aplikasi dari environment instalasi lain. Unduhan dilakukan saat setup, bukan saat memproses video.

The model download is a one-time setup. Video processing does not download a model. The UI processes one MP4 or MOV at a time and writes completed results to `~/Videos/Videogen` by default.

Set `VIDEOGEN_MODEL_PATH` to use a different local model directory. MVP 0 expects a multilingual faster-whisper model compatible with `small`.

## Workflow Hook Text (MVP 2)

UI terdiri dari tiga tahap: **Video → Hook → Hasil**. Pada tahap Hook, editor dan preview terlihat bersama; transkrip lengkap dan Pengaturan hook dibuka saat diperlukan. Tahap Hasil menyediakan Buka video, Buka folder hasil, Edit lagi, dan menu Lainnya untuk log serta evaluasi.

Jalankan `.venv/bin/videogen`, pilih video, lalu **Buat transkrip**. Proyek dibuat di folder hasil dan menyimpan transkrip serta timing kata. Salin transkrip atau **Salin prompt untuk ChatGPT** untuk dipakai di ChatGPT; paste/tulis judul pada Hook title. Atur pemenggalan, durasi, dan posisi, periksa preview FFmpeg, lalu pilih **Render video**. Render ulang memakai timing proyek tersimpan tanpa menjalankan Whisper.

### Editor WYSIWYG hook dan subtitle

Pada tahap Hook, pilih tab **Gaya** atau **Edit hook / subtitle**. Pilih target **Hook** atau **Subtitle · Seluruh video**. Tarik area teks/frame untuk posisi, tarik sisi untuk lebar, dan sudut untuk ukuran font. Klik biasa hanya memilih; drag dimulai setelah ambang gerakan. Selama drag, frame biru dan status Sedang menggeser tampil tanpa progress. Setelah dilepas, frame kuning putus-putus dan progress menunggu preview terbaru. Biru saat drag berarti objek aktif; Terapkan tetap menunggu preview valid. Escape saat drag memulihkan posisi awal, tanpa menutup sesi editor. **Pusatkan** mengembalikan posisi objek aktif jika keluar layar. Klik dua kali hook untuk mengetik; Ctrl+Enter selesai dan Escape membatalkan pengetikan.

Frame/gaya subtitle berlaku pada semua cue dari awal sampai akhir. Posisi pusat tetap saat jumlah baris berubah. Pengaturan frame tidak mengubah timestamp kata. Subtitle muncul sesuai ucapan; **Ke subtitle berikutnya** memudahkan memeriksa cue. Toolbar menyediakan font/face asli, ukuran, perataan, warna, dan Undo/Redo. Subtitle memiliki warna kata aktif serta stroke; hook memiliki latar. Angka presisi berada di **Pengaturan lanjutan**, tertutup secara default.

Ukuran tetap menjadi bawaan; posisi bebas tanpa safe zone. Bagian yang keluar video boleh terpotong sesuai preview/output. Hook maksimal tiga baris, subtitle dua baris. Cue yang tidak muat ditampilkan sebagai preview sementara dengan alasan dan tombol menuju cue bermasalah; Terapkan/render menunggu seluruh cue valid. Tidak ada pengecilan otomatis pada subtitle. Hook dapat memakai mode otomatis jika sengaja dipilih pengguna.

**Terapkan** menyimpan hook dan gaya subtitle bersama; **Batal** memulihkan sesi. Undo/Redo mencakup kedua objek. Preset/default dibedakan berdasarkan target. Penyimpanan preset tetap berlaku setelah Batal sesi. Proyek lama dinormalisasi ke kebijakan baru saat dibuka; video hasil sebelumnya tetap tersimpan. Preset di `${XDG_CONFIG_HOME:-~/.config}/videogen/hook-presets.json`; font impor di `${XDG_CACHE_HOME:-~/.cache}/videogen/fonts`. Font tervalidasi dipakai oleh preview dan render tanpa substitusi diam-diam.

Progress proses menunjukkan nama tahap: transkripsi berdasarkan waktu segmen, encoding berdasarkan waktu output FFmpeg, indikator bergerak untuk tahap yang belum terukur. 100% hanya setelah hasil berhasil disimpan. Progress preview terpisah. Halaman Hasil menyediakan tombol langsung **Buka folder hasil** menuju folder revisi video yang ditampilkan.

Gunakan **Buka proyek** untuk melanjutkan draft. Diagnostik dan pemeriksaan yang masih menunggu bukti disimpan dalam `diagnostics.jsonl`/`evaluation.json` di folder proyek. Reels serta akurasi onset kata sekitar 200 ms belum otomatis diverifikasi; catat bukti atau keluhan lewat **Catat evaluasi / keluhan**.

Dependency compatibility: PyAV is constrained to `<19` because the current faster-whisper audio decoder still calls an API removed in PyAV 19. Reinstall dependencies with `.venv/bin/pip install -e .` after pulling project updates.

## Log aplikasi

Log diagnostik disimpan lokal di `${XDG_STATE_HOME:-~/.local/state}/videogen/videogen.log` (default Linux: `~/.local/state/videogen/videogen.log`). Jika pemrosesan gagal, lokasi log juga ditampilkan pada pesan error. Log mencatat tahap proses dan detail teknis termasuk traceback untuk membantu diagnosis; tiga file log lama disimpan saat log aktif mencapai 2 MB. Periksa log sebelum mencoba ulang atau saat melaporkan masalah. Log tidak berisi isi transkrip.

Setiap job mencatat `Timestamp accuracy evaluation` dengan status `pending`, target 200 ms, dan hasil pengukuran onset kata `unmeasured`. Sampel cue awal/tengah/akhir mencatat indeks dan timestamp video tanpa isi transkrip. Status ini menjadi bahan evaluasi akurasi Whisper; keberhasilan render atau korelasi audio tidak otomatis mengubahnya menjadi lulus.

See [MVP 1 — subtitle dengan highlight kata aktif](../../MVP_1.md), [MVP 0 scope](../../MVP_0.md), and [technical architecture](../../ARSITEKTUR_TEKNIS.md).

test push
