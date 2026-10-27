# Videogen

Aplikasi web lokal untuk membuat subtitle dan hook dari video. Buka melalui browser; transkripsi, preview, dan render berjalan di komputer Anda menggunakan worker Python.

Alur utama: **pilih video → transkripsi → atur hook/subtitle → Render MP4 → unduh hasil**.

- Input: satu video MP4 atau MOV dengan track audio, maksimal 2 GiB secara bawaan.
- Ucapan dideteksi otomatis, termasuk Bahasa Indonesia dan Inggris; hasil tidak diterjemahkan.
- Output: MP4 dengan hook/subtitle tertanam, TXT transkrip, dan SRT teks biasa.
- UI tidak memerlukan Node.js atau libopenshot. PySide6 tetap dipakai secara headless untuk mengukur font.

## Daftar isi

- [Mulai cepat](#mulai-cepat)
- [Instalasi dari awal](#instalasi-dari-awal)
- [Setup font](#setup-font)
- [Menjalankan dan menghentikan aplikasi](#menjalankan-dan-menghentikan-aplikasi)
- [Cara menggunakan](#cara-menggunakan)
- [Troubleshooting](#troubleshooting)
- [Melaporkan bug](#melaporkan-bug)
- [Penyimpanan dan konfigurasi](#penyimpanan-dan-konfigurasi)
- [Batasan saat ini](#batasan-saat-ini)
- [Pengembangan dan verifikasi](#pengembangan-dan-verifikasi)
- [Dokumentasi historis](#dokumentasi-historis)

## Mulai cepat

Untuk checkout yang sudah memiliki virtualenv, FFmpeg, model, dan font:

macOS/Linux:

```bash
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/videogen-web --data-dir output/web
```

Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[web]"
.venv\Scripts\videogen-web.exe --data-dir output\web
```

Buka **[http://127.0.0.1:8765](http://127.0.0.1:8765)**. Jika belum pernah memasang aplikasi, ikuti langkah berikut dari awal.

## Instalasi dari awal

### Kebutuhan

| Komponen | Ketentuan |
| --- | --- |
| Python | **3.11–3.13**; contoh instalasi memakai 3.13 |
| Git | Untuk mengambil source repository |
| FFmpeg dan ffprobe | Tersedia di `PATH`, dengan filter ASS/libass dan encoder libx264 |
| Model | Model multilingual `Systran/faster-whisper-small`, diunduh satu kali saat setup |
| Font | File Helvetica Neue **Bold**, non-italic, `.otf` atau `.ttf` |
| Browser | Browser modern pada komputer yang menjalankan server |
| Penyimpanan | Ruang untuk model, salinan sumber video, preview, serta setiap revisi hasil |

Batas Python mengikuti dependency PySide6 yang digunakan proyek. Transkripsi memakai CPU/int8; CUDA tidak diperlukan. Internet dibutuhkan saat mengambil source, memasang dependency, dan mengunduh model. Pemrosesan video selanjutnya memakai model lokal.

### 1. Pasang Python, Git, dan FFmpeg

**macOS**

Jika Homebrew belum tersedia, pasang mengikuti [panduan resmi Homebrew](https://brew.sh/). Lalu:

```bash
brew install git python@3.13 ffmpeg-full
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
python3.13 --version
ffmpeg -version
ffprobe -version
```

`ffmpeg-full` mencantumkan libass dan x264, serta bersifat keg-only. Jalankan baris `export PATH` kembali saat membuka terminal baru untuk menjalankan Videogen, atau tambahkan ke konfigurasi shell Anda. [Formula resmi](https://formulae.brew.sh/formula/ffmpeg-full).

**Windows PowerShell**

Pasang Python 3.13 dari [Python.org](https://www.python.org/downloads/); aktifkan Python launcher saat installer menawarkan pilihan tersebut. Dengan WinGet yang tersedia di Windows, pasang Git dan FFmpeg:

```powershell
winget install --id Git.Git --exact
winget install --id Gyan.FFmpeg --exact
```

Buka **PowerShell baru**, lalu pastikan perintah dikenali:

```powershell
py -3.13 --version
git --version
ffmpeg -version
ffprobe -version
```

CTranslate2 juga membutuhkan Visual C++ Runtime. Jika muncul error DLL saat transkripsi, pasang runtime yang sesuai arsitektur mesin. [Persyaratan resmi CTranslate2](https://opennmt.net/CTranslate2/installation).

**Linux**

Contoh untuk Ubuntu 24.04 atau Debian dengan Python sistem 3.11–3.13:

```bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip ffmpeg
python3 --version
ffmpeg -version
ffprobe -version
```

Untuk distribusi lain, gunakan package manager distribusi tersebut. Pastikan Python berada pada rentang yang didukung dan build FFmpeg menyediakan libass/libx264. Jika Python sistem lebih baru dari 3.13, pasang interpreter 3.13 secara terpisah dan gunakan `python3.13` pada langkah pembuatan virtualenv.

### 2. Ambil source

Perintah yang sama dapat dijalankan dari Terminal atau PowerShell:

```bash
git clone https://github.com/wildanjisung/funcode-videogen.git
cd funcode-videogen
```

Jika repository meminta autentikasi, gunakan akun yang memiliki akses. Semua perintah setelah ini dijalankan dari folder `funcode-videogen`, yaitu folder yang memuat `pyproject.toml`.

### 3. Buat virtualenv dan pasang aplikasi

macOS:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[web]'
```

Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[web]'
```

Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[web]"
```

Tidak perlu mengaktifkan virtualenv: perintah di atas dan di bawah memakai interpreter/launcher dari `.venv` secara langsung.

### 4. Unduh model transkripsi

macOS/Linux:

```bash
.venv/bin/hf download Systran/faster-whisper-small --local-dir .cache/models/small
```

Windows PowerShell:

```powershell
.venv\Scripts\hf.exe download Systran/faster-whisper-small --local-dir .cache\models\small
```

Tunggu unduhan selesai. Direktori model harus memuat setidaknya `model.bin`, `config.json`, `tokenizer.json`, dan `vocabulary.txt`. Unduhan ini tidak perlu diulang pada setiap video.

### 5. Sediakan font

Ikuti [Setup font](#setup-font), kemudian lanjutkan ke langkah 6.

## Setup font

Sediakan file **Helvetica Neue Bold non-italic** yang sesuai lisensi penggunaan Anda. Font tidak disertakan dalam repository/paket aplikasi. Contoh sumber lisensi: [Neue Helvetica](https://www.myfonts.com/collections/neue-helvetica-font-linotype).

Tentukan path absolut file pada terminal yang akan menjalankan server:

macOS/Linux:

```bash
export VIDEOGEN_FONT_PATH="/absolute/path/HelveticaNeueBold.otf"
.venv/bin/python -c 'from videogen.infrastructure.fonts import SubtitleFont, default_font_path; font = SubtitleFont(default_font_path()); print(font.raw.familyName(), font.raw.styleName(), font.postscript_name)'
```

Windows PowerShell:

```powershell
$env:VIDEOGEN_FONT_PATH = "C:\Fonts\HelveticaNeueBold.otf"
.venv\Scripts\python.exe -c "from videogen.infrastructure.fonts import SubtitleFont, default_font_path; font = SubtitleFont(default_font_path()); print(font.raw.familyName(), font.raw.styleName(), font.postscript_name)"
```

Ganti path contoh dengan file font Anda. Hasil yang diharapkan:

```text
Helvetica Neue Bold HelveticaNeue-Bold
```

Font Regular atau Italic akan ditolak. Variabel environment di atas berlaku pada sesi terminal saat ini; atur kembali pada terminal baru sebelum menjalankan server. Alternatifnya, simpan file pada `.cache/fonts/helvetica-neue/HelveticaNeueBold.otf` di checkout agar ditemukan otomatis.

`VIDEOGEN_FONT_PATH` memiliki prioritas atas cache. Worker memeriksa family, weight 700, dan kesesuaian font render; substitusi font tidak diterbitkan sebagai hasil sukses.

## Menjalankan dan menghentikan aplikasi

### 6. Jalankan server dan buka UI

macOS/Linux:

```bash
.venv/bin/videogen-web --data-dir output/web
```

Windows PowerShell:

```powershell
.venv\Scripts\videogen-web.exe --data-dir output\web
```

Terminal akan menampilkan pesan seperti:

```text
Buka http://127.0.0.1:8765 di browser.
Uvicorn running on http://127.0.0.1:8765
```

Biarkan terminal tetap terbuka. Buka **[http://127.0.0.1:8765](http://127.0.0.1:8765)** di browser pada komputer yang sama. Pada setup lengkap, panel **Pilih video** dapat digunakan. Jika komponen belum ditemukan, halaman menyebut FFmpeg, model, atau font yang perlu dilengkapi.

Untuk memeriksa status langsung, buka [status lokal](http://127.0.0.1:8765/api/status). Setup yang siap memiliki `setup.ready: true`. Pemeriksaan awal font hanya memastikan file terbaca; validasi isi/font dilakukan worker saat proses berjalan.

**Instalasi dinyatakan berhasil sampai output** setelah video uji dapat diunggah, ditranskripsikan, dipreview, dan dirender; unduhan MP4, TXT, serta SRT dapat dibuka. Ikuti [Cara menggunakan](#cara-menggunakan) untuk melakukan pemeriksaan tersebut.

Tekan **Ctrl+C di terminal server** untuk menghentikan aplikasi. Penutupan server meminta penghentian worker aktif beserta proses anaknya. Menutup tab browser saja tidak membatalkan pekerjaan.

### Menjalankan kembali

Masuk ke folder repository, atur kembali `PATH` FFmpeg dan path font bila menggunakan environment variable, lalu jalankan launcher yang sama. Tidak perlu membuat virtualenv, mengunduh model, atau memasang ulang dependency setiap kali membuka aplikasi.

Opsi lain, contoh macOS/Linux:

```bash
.venv/bin/videogen-web --port 8766 --data-dir output/web --max-upload-mb 2048
```

Buka `http://127.0.0.1:8766` jika port diganti. `--max-upload-mb` memakai MiB. Dua server tidak boleh menggunakan direktori data yang sama secara bersamaan.

## Cara menggunakan

### 1. Pilih video dan tunggu transkripsi

Pilih atau letakkan satu file MP4/MOV pada panel proyek. Proses menyalin sumber ke direktori data web, mengekstrak audio, lalu membuat transkrip dengan timing kata.

Progress ditampilkan per tahap. **Batalkan** meminta penghentian pekerjaan. Jika transkripsi gagal setelah unggahan selesai, buka proyek tersebut dan pilih **Buat transkrip** untuk mencoba ulang. Untuk kegagalan upload, pilih file kembali.

### 2. Tulis hook dan atur subtitle

Pada panel **Hook**, tulis judul pembuka. Matikan **Tampilkan hook** bila hanya ingin subtitle. Hook dibatasi 500 karakter dan tiga baris; mode manual mengikuti newline tanpa baris kosong. Atur durasi atau pilih **Sepanjang video**.

Pilih **Hook** atau **Subtitle** untuk mengatur ukuran, lebar, posisi, perataan, warna, dan latar. Gaya subtitle berlaku untuk seluruh video; timestamp kata tidak diubah. Bawaan subtitle memakai Helvetica Neue Bold, teks putih, stroke gelap tipis, serta highlight kuning pada kata aktif. Frasa dikelompokkan menjadi cue pendek, dengan target maksimal empat kata/2,5 detik; kelompok kata bertumpang tindih dipertahankan agar interval ucapan tidak terpotong.

**Simpan draft** menyimpan perubahan tanpa merender. Label **Draft tersimpan** berarti tidak ada perubahan baru untuk disimpan. Hook kosong boleh disimpan sebagai draft, tetapi perlu diisi atau dinonaktifkan sebelum preview/render.

### 3. Periksa preview dan posisi

**Perbarui preview** membuat frame hasil melalui FFmpeg. Pilih kata pada transkrip, gunakan slider waktu atau **Cue berikutnya** untuk memeriksa waktu lain.

Pada preview, geser frame teks untuk mengubah posisi; perubahan diterapkan setelah drag dilepas. Escape membatalkan drag. Tombol panah menggeser 0,1%; Shift+panah 1%. **Pusatkan objek** memulihkan posisi. Ukuran dan lebar diubah melalui angka pada inspector. Undo/Redo berlaku pada perubahan dalam sesi browser.

**Video sumber** memutar video tanpa overlay. Jika browser tidak mendukung codec sumber, pilih **Siapkan video untuk browser** untuk membuat proxy H.264/AAC. Video asli tidak diubah.

### 4. Render dan unduh hasil

Klik **Render MP4**. UI otomatis:

1. Menyimpan perubahan draft.
2. Memperbarui preview bila snapshot belum sesuai.
3. Memeriksa seluruh cue.
4. Merender video jika semuanya valid.

Jika Anda mengedit saat preview sedang diperiksa, kelanjutan render otomatis dibatalkan agar tidak memakai hook lama. Klik **Render MP4** lagi untuk memproses versi terbaru.

Bila cue tidak muat, UI menampilkan alasan dan waktu cue pertama. Pilih **Perbaiki subtitle**, kecilkan font atau perbesar lebar, lalu render kembali. Kolom angka yang tidak valid ditandai beserta tindakan **Perbaiki nilai**. Status di bawah toolbar menjelaskan langkah berikutnya.

Setelah selesai, putar hasil dan unduh:

| File | Isi |
| --- | --- |
| MP4 | Video dengan style, hook, dan highlight subtitle tertanam |
| TXT | Transkrip teks |
| SRT | Subtitle teks biasa dengan timing cue; tanpa style/highlight |

Setiap render membuat revisi baru; hasil sebelumnya tetap tersedia pada pilihan revisi. Render ulang menggunakan timing tersimpan tanpa menjalankan Whisper lagi. Proyek dan draft tersimpan dapat dibuka kembali dari daftar proyek.

## Troubleshooting

| Gejala | Pemeriksaan dan tindakan |
| --- | --- |
| `python` atau `py -3.13` tidak ditemukan | Pasang Python 3.11–3.13 dan buka terminal baru. Gunakan interpreter yang dipakai membuat `.venv`. |
| Instalasi menolak Python 3.14+ | Buat `.venv` dengan Python 3.13, bukan interpreter terbaru di sistem. |
| `videogen-web` tidak ditemukan | Jalankan path lengkap `.venv/bin/videogen-web` atau `.venv\Scripts\videogen-web.exe`; pastikan instalasi memakai `'.[web]'`. |
| Browser tidak dapat membuka localhost | Pastikan terminal server masih berjalan, baca error startup, dan cocokkan port browser dengan `--port`. |
| Port sudah digunakan | Buka server yang sudah berjalan atau gunakan `--port 8766`. Jika ingin server terpisah, gunakan direktori data berbeda. |
| Folder data sedang digunakan server lain | Hentikan server pemilik folder melalui terminalnya; jangan menghapus lock saat server tersebut masih berjalan. |
| FFmpeg belum siap | Periksa `ffmpeg -version`, `ffprobe -version`, `ffmpeg -hide_banner -h filter=ass`, dan `ffmpeg -hide_banner -h encoder=libx264`. Build harus menyediakan filter ASS dan encoder libx264. |
| Model belum tersedia | Pastikan unduhan selesai dan file model berada pada `.cache/models/small`, atau atur `VIDEOGEN_MODEL_PATH` ke direktori model yang lengkap. |
| Font belum tersedia atau ditolak | Periksa [Setup font](#setup-font); gunakan Bold non-italic dengan family/weight yang sesuai, lalu jalankan server dari terminal yang memiliki environment tersebut. |
| Error DLL Windows saat memuat transkripsi | Periksa Visual C++ Runtime dan kesesuaian arsitektur Python/dependency. Sertakan nama DLL pada laporan bug. |
| Save abu-abu dengan label Draft tersimpan | Tidak ada perubahan baru untuk disimpan; ini status normal. |
| Render belum dapat dijalankan | Baca status di bawah toolbar: periksa hook kosong, angka invalid, cue tidak muat, atau pekerjaan yang masih aktif. Gunakan tindakan perbaikan yang ditampilkan. |
| Preview masih menampilkan gaya lama | Pilih Perbarui preview, atau klik Render MP4 untuk memeriksa snapshot terbaru otomatis. |
| Draft berubah di tab lain | Salin teks yang belum tersimpan, lalu muat ulang proyek agar versi draft sesuai. |
| Video sumber tidak dapat diputar | Gunakan Siapkan video untuk browser; bedakan playback sumber tanpa overlay dengan MP4 hasil render. |
| Pemrosesan gagal | Pilih Unduh log pekerjaan. Jika log belum dibuat, periksa error pada terminal dan berkas `stderr.txt` job. |

Jika belum terselesaikan, buat laporan berikut.

## Melaporkan bug

Laporkan melalui [Issues repository](https://github.com/wildanjisung/funcode-videogen/issues) atau kirim ke pengelola jika Anda tidak memiliki akses. Gunakan satu laporan untuk satu masalah.

### Informasi yang dilampirkan

- OS dan arsitektur, versi Python, browser, serta commit source.
- Langkah dari membuka proyek sampai masalah muncul, hasil yang diharapkan, dan hasil aktual.
- Pesan error/status lengkap dan waktu kejadian. Untuk tombol disabled, sertakan status di bawah toolbar dan kolom yang ditandai.
- ID job/proyek/revisi bila tersedia dari URL, log, atau nama folder data.
- Karakteristik video: MP4/MOV, durasi, resolusi, codec, serta apakah terjadi pada semua video atau hanya satu contoh.
- Log pekerjaan melalui **Unduh log pekerjaan**, screenshot yang relevan, dan error Console browser bila ada.

Lokasi log untuk launcher `--data-dir output/web`:

```text
output/web/jobs/<job-id>/worker.log
output/web/jobs/<job-id>/stderr.txt
output/web/jobs/<job-id>/events.jsonl
output/web/jobs/<job-id>/state.json
```

Jika memakai `--data-dir` lain, gunakan direktori tersebut. Cari request/job terkait dari waktu file; tidak semua file ada pada kegagalan yang terjadi sebelum worker dimulai. Untuk bug UI tanpa log worker, buka Developer tools → Console, ulangi langkahnya, lalu salin error yang muncul.

Perintah untuk mengambil versi, macOS/Linux:

```bash
git rev-parse --short HEAD
.venv/bin/python --version
.venv/bin/python -m pip show videogen-mvp0 fastapi PySide6-Essentials faster-whisper av
ffmpeg -version
ffprobe -version
```

Windows PowerShell:

```powershell
git rev-parse --short HEAD
.venv\Scripts\python.exe --version
.venv\Scripts\python.exe -m pip show videogen-mvp0 fastapi PySide6-Essentials faster-whisper av
ffmpeg -version
ffprobe -version
```

Cukup lampirkan bagian versi yang relevan. Tinjau log/screenshot sebelum dibagikan: hapus token dan informasi pribadi; video asli atau transkrip sensitif tidak perlu disertakan untuk laporan awal. Gunakan sampel singkat yang boleh dibagikan jika diperlukan untuk reproduksi.

### Template laporan

```text
Judul: [UI/Transkripsi/Preview/Render/Instalasi] Ringkasan masalah

OS dan arsitektur:
Python:
Browser dan versi:
Commit (git rev-parse --short HEAD):
Versi dependency/FFmpeg yang relevan:

Tahap saat masalah terjadi:
Waktu kejadian:
ID proyek/job/revisi (jika ada):
Video: format, durasi, resolusi, codec (jika diketahui)

Langkah reproduksi:
1.
2.
3.

Hasil yang diharapkan:
Hasil aktual:
Pesan error/status UI:
Terjadi selalu atau sesekali:
Terjadi pada video lain juga:

Lampiran: log pekerjaan, screenshot, atau error Console yang relevan
Percobaan troubleshooting dan hasilnya:
```

## Penyimpanan dan konfigurasi

Perintah mulai cepat memakai **`output/web` di checkout** agar lokasi data mudah ditemukan. Jika `--data-dir` dihilangkan, lokasi bawaan mengikuti OS:

| OS | Direktori data web |
| --- | --- |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/videogen/web` |
| macOS | `~/Library/Application Support/Videogen/web` |
| Windows | `%LOCALAPPDATA%\Videogen\data\web` |

`XDG_DATA_HOME` yang ditetapkan eksplisit memiliki prioritas pada semua OS. Model dan font dapat diarahkan melalui `VIDEOGEN_MODEL_PATH` dan `VIDEOGEN_FONT_PATH`. Cache `.cache/` checkout yang sudah tersedia tetap dikenali.

```text
<data-dir>/
  projects/<project-id>/
    record.json
    media/source.mp4 atau source.mov
    processed/<worker-project>/
      project.json, media.json, words.json, transcript.txt, draft.json
      revisions/<revision-id>/
    previews/<job-id>.png dan <job-id>.layout.json
    playback.mp4                 # hanya jika proxy diminta
  jobs/<job-id>/
    state.json, request.json, events.jsonl, worker.log, stderr.txt
```

Sumber yang sudah diunggah disalin ke data web. Memindahkan file asli dari folder lain tidak menghilangkan salinan tersebut. Untuk backup, hentikan server dan salin direktori data lengkap; mempertahankan lokasi/path yang sama diperlukan saat pemulihan karena format worker masih menyimpan absolute path sumber/font. Model dan font di luar direktori data perlu dicadangkan terpisah.

## Batasan saat ini

- UI web menyediakan hook/subtitle dan drag posisi; trim/split timeline, import/pemilihan font, serta pengelolaan preset belum memiliki UI web.
- Satu pekerjaan aktif dalam satu waktu. Pekerjaan terputus karena server berhenti mendadak ditandai `interrupted` saat startup berikutnya.
- Preview hasil berupa frame; playback sumber tidak menampilkan overlay. Playback dengan overlay tersedia pada hasil render.
- Subtitle memakai ukuran tetap; cue yang tidak muat perlu diperbaiki pengguna. Hook dapat memakai ukuran otomatis jika dipilih.
- Proyek desktop lama tidak otomatis diimpor. Pemindahan data/proyek antarmesin belum didukung secara otomatis.
- Server lokal satu pengguna terikat ke `127.0.0.1`. Hosting publik/multiuser memerlukan desain akses dan penyimpanan tersendiri.
- Pengujian runtime yang tersedia berasal dari Linux. Native Windows/macOS serta pemeriksaan visual browser belum menjadi klaim kelulusan lintas platform.
- Keberhasilan render tidak membuktikan akurasi onset kata Whisper 200 ms; hal itu membutuhkan evaluasi independen.

## Pengembangan dan verifikasi

Implementasi UI: [src/videogen/web](src/videogen/web). Worker: [worker_main.py](src/videogen/worker_main.py).

Tes Python, macOS/Linux:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

Windows PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Suite lengkap juga memuat tes desktop/libopenshot lama; untuk gate web yang tidak membutuhkan engine desktop tersebut, tambahkan `-p test_web.py` pada perintah discovery.

Tes DOM pengembang memerlukan Node.js **22.8+**; Node tidak diperlukan untuk menjalankan aplikasi:

```bash
npm ci --prefix tests/web
npm test --prefix tests/web
```

Catatan bukti: [verifikasi web](diagnostics/web/2026-10-27/VERIFICATION.md) dan [perbaikan UX simpan/render](diagnostics/web/2026-10-27/UX_FIX.md). Tes API/DOM tidak menggantikan uji visual browser atau uji native OS lain.

## Dokumentasi historis

README ini adalah panduan utama versi **UI web**. Dokumen berikut disimpan sebagai riwayat pengembangan dan dapat memuat perilaku desktop atau keputusan sebelum migrasi:

- [Arsip README lama](docs/archive/README-legacy.md).
- [MVP 0](MVP_0.md), [MVP 1](MVP_1.md), [MVP 2](MVP_2.md), dan [MVP 3](MVP_3.md).
- [Arsitektur awal](ARSITEKTUR_TEKNIS.md) dan [rancangan editor awal](RANCANGAN_VIDEO_EDITOR.md).
- [Evaluasi OpenCut](EVALUASI_OPENCUT.md).
