# Videogen web lokal

UI browser di atas worker Videogen yang sudah ada. Transkripsi tetap menggunakan faster-whisper lokal; preview dan render memakai FFmpeg/libass. Aplikasi dilayani dari satu proses Python, tanpa build frontend atau Node.js pada mesin pengguna.

## Instalasi

Gunakan Python **3.11–3.13**. Batas ini mengikuti PySide6-Essentials 6.8.2 yang dipakai untuk pengukuran font. Ketersediaan wheel dependency juga bergantung arsitektur mesin; panduan ini belum menjadi bukti pengujian native macOS atau Windows ARM.

### macOS

Sediakan Python 3.13 dan FFmpeg dengan filter ASS serta libx264. Contoh dengan Homebrew:

```bash
brew install python@3.13 ffmpeg-full
export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
python3.13 -m venv .venv
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/hf download Systran/faster-whisper-small --local-dir .cache/models/small
export VIDEOGEN_FONT_PATH="/absolute/path/HelveticaNeueBold.otf"
.venv/bin/videogen-web
```

`ffmpeg-full` bersifat keg-only; penambahan `PATH` di atas berlaku untuk terminal tempat server dijalankan. Formula tersebut mencantumkan libass dan x264. [Formula resmi Homebrew](https://formulae.brew.sh/formula/ffmpeg-full).

### Windows PowerShell

Sediakan Python 3.13, FFmpeg dan ffprobe dalam `PATH`, serta Visual C++ Runtime yang diperlukan CTranslate2. Paket FFmpeg dapat dipasang melalui WinGet:

```powershell
winget install --id Gyan.FFmpeg --exact
```

Buka terminal baru setelah pemasangan agar `PATH` terbaru terbaca, lalu dari root checkout:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[web]"
.venv\Scripts\hf.exe download Systran/faster-whisper-small --local-dir .cache\models\small
$env:VIDEOGEN_FONT_PATH = "C:\Fonts\HelveticaNeueBold.otf"
.venv\Scripts\videogen-web.exe
```

Rujukan paket: [manifest WinGet Gyan.FFmpeg](https://github.com/microsoft/winget-pkgs/tree/master/manifests/g/Gyan/FFmpeg). Persyaratan runtime dan arsitektur: [dokumentasi CTranslate2](https://opennmt.net/CTranslate2/installation).

### Linux

Sediakan FFmpeg/ffprobe dengan libass/libx264 melalui package manager distribusi. Lalu:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[web]'
.venv/bin/hf download Systran/faster-whisper-small --local-dir .cache/models/small
export VIDEOGEN_FONT_PATH="/absolute/path/HelveticaNeueBold.otf"
.venv/bin/videogen-web
```

Pilih interpreter 3.11–3.13 jika `python3` sistem lebih baru. Setup font dan sumber file yang sebelumnya digunakan dijelaskan pada [README](README.md#setup-font). Font tidak disertakan dalam distribusi aplikasi; gunakan file yang sesuai lisensi penggunaan Anda.

### Pemeriksaan awal

Buka **http://127.0.0.1:8765**. Jika FFmpeg, model, atau font belum ditemukan, halaman menunjukkan komponen yang perlu dilengkapi. Pemeriksaan awal font memastikan file tersedia/dapat dibaca; validasi family/weight dan font render tetap dilakukan worker sebelum menghasilkan output.

Pemeriksaan FFmpeg dapat dijalankan langsung:

```bash
ffmpeg -hide_banner -h filter=ass
ffmpeg -hide_banner -h encoder=libx264
ffprobe -version
```

Untuk lokasi lain, atur `VIDEOGEN_MODEL_PATH` dan `VIDEOGEN_FONT_PATH` sebelum menjalankan server. Unduhan model hanya saat setup; pemrosesan video tidak mengunduh model. Transkripsi saat ini memakai CPU/int8 dan tidak memerlukan CUDA.

## Penggunaan

1. Pilih atau letakkan satu MP4/MOV pada panel proyek. Batas bawaan 2 GiB; unggahan ditulis bertahap ke disk.
2. Tunggu transkripsi. Tahap kerja dan progress ditampilkan; **Batalkan** meminta penghentian worker beserta proses anaknya.
3. Tulis hook atau matikan **Tampilkan hook** untuk menghasilkan subtitle saja. Pilih mode pemenggalan manual jika newline harus dipertahankan. Hook maksimal 500 karakter dan tiga baris sesuai aturan worker.
4. Pilih **Hook** atau **Subtitle** untuk mengatur ukuran, lebar, posisi, perataan dan warna. Pengaturan subtitle berlaku untuk seluruh video; timestamp kata tidak diubah.
5. Pilih **Perbarui preview**. Frame yang tampil benar-benar dihasilkan FFmpeg; cue yang tidak muat ditandai dan menahan render.
6. Geser frame teks untuk mengubah posisi. Perubahan baru disimpan pada pointer release; Escape membatalkan drag. Tombol panah pada frame menggeser 0,1%, Shift+panah 1%. **Pusatkan objek** memulihkan posisi agar dapat ditemukan kembali. Ukuran/lebar diubah melalui inspector.
7. Pilih kata pada transkrip atau gunakan slider untuk memeriksa waktu lain. Mode **Video sumber** memutar sumber tanpa overlay. Jika codec tidak didukung browser, **Siapkan video untuk browser** membuat proxy H.264/AAC tanpa mengubah video asli.
8. Pilih **Render MP4**. UI menyimpan perubahan, memperbarui preview jika diperlukan, memeriksa seluruh cue, lalu merender otomatis. **Perbarui preview** tetap tersedia jika ingin memeriksa frame dahulu. Render menggunakan snapshot yang telah divalidasi dan timing kata tersimpan; tidak menjalankan Whisper ulang.
9. Putar hasil dan unduh MP4, TXT, atau SRT. Revisi sebelumnya tetap tersedia pada pilihan revisi.

Undo/Redo berlaku pada perubahan hook/gaya dalam sesi browser. Draft yang disimpan, transkrip, media, status job, preview dan revisi tersedia kembali setelah halaman/server dibuka ulang. Browser yang ditutup tidak otomatis membatalkan job; **Ctrl+C pada server** meminta penghentian worker aktif. Job yang terputus karena server berhenti mendadak ditandai `interrupted` pada startup berikutnya.

Satu pekerjaan aktif diperbolehkan pada satu waktu. Edit saat preview berlangsung menandai snapshot lama dan membatalkan kelanjutan render otomatis; klik **Render MP4** lagi untuk memproses perubahan terbaru. Konflik versi draft antartab ditolak dengan pesan untuk memuat ulang proyek.

Status di bawah toolbar menjelaskan langkah berikutnya. Tombol **Draft tersimpan** berarti tidak ada perubahan baru untuk disimpan. Kolom angka yang tidak valid ditandai dengan alasan dan tombol **Perbaiki nilai**. Hook kosong tetap dapat disimpan sebagai draft; untuk render, isi hook atau matikan tampilannya. Jika subtitle belum muat, **Perbaiki subtitle** membuka pengaturannya dan menuju waktu cue pertama yang bermasalah.

## Penyimpanan dan launcher

```bash
videogen-web --port 8765 --data-dir output/web --max-upload-mb 2048
```

Gunakan path launcher `.venv/bin/videogen-web` atau `.venv\Scripts\videogen-web.exe` bila virtualenv belum diaktifkan. Semua opsi bersifat opsional. `--max-upload-mb` menggunakan MiB.

Jika `--data-dir` tidak diisi:

| OS | Data web bawaan |
| --- | --- |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/videogen/web` |
| macOS | `~/Library/Application Support/Videogen/web` |
| Windows | `%LOCALAPPDATA%\Videogen\data\web` |

`XDG_DATA_HOME` yang diatur eksplisit memiliki prioritas pada semua OS. Konfigurasi, cache, dan log juga memakai direktori per OS. Cache model/font lama di `.cache/` checkout tetap dipakai bila tersedia. `VIDEOGEN_MODEL_PATH` dan `VIDEOGEN_FONT_PATH` memiliki prioritas atas cache.

Struktur data:

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

Proyek web baru memakai sumber yang dimiliki direktori data, sehingga menghapus atau memindahkan file unggahan asli dari folder lain tidak menghilangkan sumber proyek web. Format proyek worker dipertahankan. Memindahkan seluruh direktori data antarmesin belum didukung: source/font pada format worker masih memiliki absolute path. Proyek desktop yang sudah ada tidak otomatis diimpor ke daftar proyek web.

Server terikat ke `127.0.0.1`, melayani UI/API pada origin yang sama, dan menolak Host/Origin di luar akses lokal yang diizinkan. Ini launcher lokal untuk satu pengguna; deployment publik/multiuser memerlukan desain autentikasi dan penyimpanan terpisah. Menjalankan frontend di browser tidak memindahkan Whisper/FFmpeg ke browser.

## Batas UI awal

- Pengaturan hook/subtitle dan drag posisi tersedia; trim/split timeline, pemilihan/import font, serta pengelolaan preset belum memiliki UI web.
- Default preset yang sudah digunakan worker tetap menjadi titik awal proyek; perubahan gaya dari UI web tidak mengubah default global.
- PySide6 masih diperlukan untuk pengukuran font secara headless. Jalur web tidak mengimpor loader libopenshot Linux.
- Preview hasil berupa frame, sedangkan playback sumber tidak menampilkan overlay. Video dengan overlay bergerak tersedia setelah render.
- Tidak ada janji akurasi timing Whisper 200 ms hanya dari keberhasilan transkripsi/render.

## Verifikasi

Tes integrasi:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p test_web.py -v
```

PowerShell:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m unittest discover -s tests -p test_web.py -v
```

Tes web memakai FastAPI TestClient (`httpx` tersedia melalui dependency faster-whisper). Cakupan meliputi preview/render dengan worker FFmpeg asli, hash timing setelah preview, konflik versi, revisi tetap tersimpan, HTTP range, batas upload, penolakan path font dari browser, pembatalan proses anak, pemuatan ulang data, dan pemetaan path OS.

Untuk tes pengembang terhadap controller dan form HTML, gunakan Node.js 22.8+:

```bash
npm ci --prefix tests/web
npm test --prefix tests/web
```

Dependency jsdom ini hanya untuk tes DOM, bukan requirement menjalankan Videogen. Tes mencakup pengisian hook, koordinat desimal, alasan tombol diblokir, urutan simpan/preview/render, layout tidak valid, konflik draft, dan perubahan saat preview berlangsung. Tes DOM tidak menggantikan pemeriksaan visual browser.

Hasil eksekusi dan batas bukti runtime dicatat pada [verifikasi web](diagnostics/web/2026-10-27/VERIFICATION.md). Keberhasilan Linux dan tes pemetaan path belum membuktikan runtime native Windows/macOS ataupun interaksi visual browser.
