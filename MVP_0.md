# MVP 0 — Video ke Subtitle Otomatis

Status: Scope implementasi pertama. Dokumen ini menjadi acuan sebelum MVP 1 pada rancangan produk dan arsitektur teknis.

Keputusan di bawah menjadi default implementasi. Detail teknis yang belum tercakup boleh ditetapkan selama coding dengan menjaga scope; perubahan dicatat singkat di dokumen ini. Implementasi belum dijalankan.

## 1. Tujuan

Tool desktop internal yang menerima satu video, mentranskripsi ucapan dari audionya, menempelkan subtitle ke video, lalu menyimpan hasil. Pengguna cukup memilih video dan menekan **Proses**.

```text
Video sumber → ekstraksi audio → transkripsi → render subtitle → video hasil
```

## 2. Perilaku MVP 0

1. Pengguna memilih satu video lokal.
2. Aplikasi mengekstrak audio dan mendeteksi bahasa ucapan otomatis, termasuk Bahasa Indonesia dan Inggris.
3. Transkripsi menghasilkan segmen teks dengan waktu mulai dan selesai.
4. Aplikasi membuat subtitle dengan satu gaya tetap: teks putih, outline gelap, posisi bawah, maksimal dua baris per cue.
5. Subtitle dirender permanen ke video.
6. Hasil disimpan ke folder yang dipilih; sumber asli tidak ditimpa.

Ukuran font dan margin dihitung relatif terhadap frame. Teks panjang dipecah menjadi beberapa cue menggunakan timestamp kata; tidak memadatkan seluruh kalimat panjang ke satu layar.

## 3. Input dan output

### Input awal

- Satu file MP4 atau MOV lokal dengan video SDR yang dapat didekode FFmpeg dan audio berucapan. MOV masuk scope karena bahan pengguna memakai format tersebut.
- Pilih track video pertama yang bukan cover/attached picture.
- Jika terdapat beberapa track audio, gunakan track audio pertama pada MVP 0.
- HDR/PQ/HLG dan Dolby Vision ditolak dengan pesan jelas pada tahap ini; tidak dikonversi diam-diam ke SDR.
- Deteksi dukungan berdasarkan hasil probe dan kemampuan decoder, bukan ekstensi saja. Format lain belum menjadi scope.
- Durasi dan ukuran tidak diberi batas produk arbitrer. File harus memiliki durasi valid dan folder hasil dapat ditulis; kapasitas disk diperiksa sebelum mulai dan kegagalan tulis tetap ditangani selama proses.

### Output

- Satu MP4 bersubtitle sebagai hasil utama.
- TXT transkrip dan SRT sebagai hasil pendamping, dari transkripsi yang sama.
- Semua hasil memiliki nama dasar yang sama, disimpan dalam folder hasil unik.

Contoh:

```text
<folder-hasil>/IMG_1703_subtitled_<id-unik>/
  IMG_1703_subtitled.mp4
  IMG_1703_subtitled.txt
  IMG_1703_subtitled.srt
```

Ketiga file disiapkan dalam direktori staging pada filesystem folder hasil. Setelah render dan pemeriksaan berhasil, direktori dipindahkan ke nama final yang belum ada. Status **selesai** hanya dikirim setelah ketiga file tersedia. Kegagalan tidak menerbitkan paket sebagian.

### Mengikuti kualitas input

- Pertahankan rasio dan dimensi tampilan sumber; tidak ada resize, crop, atau upscale untuk target sosial media.
- Normalisasi metadata rotasi agar orientasi hasil sama dengan tampilan sumber.
- Pertahankan durasi, urutan isi, dan kecepatan pemutaran sumber.
- Pertahankan timestamp frame sumber; gunakan `fps_mode=passthrough` dengan timebase yang sesuai saat render. Tidak menambahkan `-r 30` atau filter FPS. Parameter rinci disesuaikan saat implementasi dengan hasil pemeriksaan timing.
- Encoding awal ditetapkan: `libx264`, CRF 18, preset medium, pixel format yuv420p, dan MP4 faststart.
- Audio AAC sumber disalin jika kompatibel; audio lain dikonversi ke AAC 192 kbps. Track audio yang dipakai untuk transkripsi sama dengan track output.
- Bila dimensi tidak cocok untuk encoding tersebut, tambahkan padding paling kecil yang diperlukan, bukan memperbesar isi video.
- Pertahankan informasi warna SDR jika sesuai dan sample aspect ratio/display aspect ratio sumber. Normalisasi rotasi dilakukan satu kali; metadata rotasi hasil tidak menyebabkan pemutar merotasi ulang.
- Audio transkripsi memakai WAV PCM 16-bit, mono, 16 kHz; ini berkas kerja, bukan pengganti audio output.
- Timestamp subtitle dikonversi ke timeline video dengan memperhitungkan offset awal audio/video. Jangan menggeser kedua stream ke nol secara terpisah sehingga sinkronisasi berubah.
- Jangan memakai penghentian berdasarkan stream terpendek secara otomatis; audio pendek tidak boleh memotong bagian akhir video.

Subtitle permanen memerlukan encoding ulang video. “Mengikuti kualitas input” berarti mempertahankan karakteristik tampilan sumber dan memakai pengaturan encoding berkualitas; tidak menjanjikan hasil identik atau tanpa kehilangan kualitas. Codec dan bitrate tidak harus sama dengan input, dan ukuran file hasil dapat berbeda.

Pengaturan encoding menjadi konfigurasi internal tetap pada tahap ini, tanpa menu preset pengguna.

## 4. Tampilan desktop

Satu jendela berisi:

- Tombol **Pilih video** dan nama berkas.
- Folder hasil, default `~/Videos/Videogen`, dapat diganti untuk proses tersebut. Penyimpanan preferensi belum diperlukan.
- Tombol **Proses**.
- Status tahap: ekstraksi audio, transkripsi, render, selesai, atau gagal.
- Tombol **Buka folder hasil** setelah selesai.

Satu video diproses pada satu waktu. Pemrosesan berlangsung di proses worker terpisah agar jendela tetap responsif. Preview hasil menggunakan pemutar video sistem melalui file hasil; pemutar tertanam belum diperlukan.

Saat proses aktif, pemilihan sumber/folder dan tombol proses dinonaktifkan. Menutup aplikasi meminta konfirmasi pembatalan; worker dan proses FFmpeg dihentikan, lalu file sementara dibersihkan. Tidak ada resume: pengguna menjalankan ulang proses jika terhenti.

Target pertama adalah Linux desktop pada mesin pengguna, dijalankan dari environment Python lokal. Packaging installer dan dukungan OS lain masuk tahap berikutnya.

## 5. Stack minimal

| Komponen | Pilihan |
| --- | --- |
| Aplikasi dan UI | Python + PySide6 |
| Transkripsi lokal | faster-whisper; PyAV dipin `>=11,<19` karena API decoder yang digunakan belum kompatibel dengan PyAV 19 |
| Analisis, ekstraksi, dan render | ffprobe + FFmpeg dengan libass |
| State sementara | Memori proses dan direktori kerja sementara |
| Output | File MP4, TXT, dan SRT di disk lokal |

Tidak diperlukan database pada MVP 0. Default transkripsi ditetapkan:

| Pengaturan | Nilai awal |
| --- | --- |
| Model | `small` multilingual, bukan `small.en` |
| Device / compute | CPU / `int8` |
| Paralelisme | Satu inference, maksimal empat thread CPU |
| Bahasa / task | Deteksi otomatis (`None`) / `transcribe` |
| Beam size | 5 |
| VAD | Aktif, pengaturan konservatif bawaan library |
| Timestamp kata | Aktif untuk pembagian cue; tidak ada animasi per kata |

Model multilingual `small` dan deteksi bahasa otomatis mendukung input Bahasa Indonesia maupun Inggris. Bahasa yang terdeteksi dan probabilitas deteksinya dicatat di log. Deteksi pada klip yang sangat pendek atau audio campuran dapat kurang akurat; kualitas bahasa lain belum dijanjikan. Pilihan CPU memberi default tanpa dependency CUDA; waktu proses belum diukur.

Model disiapkan sekali saat setup dengan versi/revision tercatat. Pemrosesan menggunakan model lokal tanpa unduhan tersembunyi saat tombol **Proses** ditekan. Jika belum tersedia, tampilkan langkah setup yang diperlukan.

Pemeriksaan awal mencakup FFmpeg/ffprobe, encoder libx264, filter subtitle/libass, font, model lokal, dan izin folder hasil. Pin versi dependency kompatibel dalam lockfile saat implementasi.

### Gaya dan pembagian subtitle

- Font tetap: DejaVu Sans, disediakan sebagai resource aplikasi bersama lisensinya agar hasil tidak bergantung pada font pengguna.
- Untuk frame dengan dimensi tampilan `W × H`, ukuran awal font = `round(min(0.04 × H, 0.065 × W))` piksel; outline gelap = sekitar 6% ukuran font, minimal satu piksel.
- Warna teks putih; alignment tengah bawah; margin kiri/kanan 8% lebar dan margin bawah 6% tinggi frame.
- Gunakan dimensi tampilan setelah rotasi untuk ASS PlayRes dan layout.
- Bungkus pada batas kata, maksimal dua baris dengan lebar teks terukur. Pengukuran memakai file font dan ukuran yang sama dengan render; kesesuaiannya diperiksa saat implementasi.
- Bentuk cue dari timestamp kata, utamakan batas kalimat/jeda, lalu pecah ketika dua baris tidak cukup atau durasi melebihi enam detik.
- Waktu cue mengikuti kata pertama sampai kata terakhir; jangan membagi timing berdasarkan jumlah karakter. Gunakan gap ucapan jika tersedia untuk keterbacaan, tanpa menimpa cue berikutnya.
- Timestamp disimpan dalam milidetik; validasi urutan, `start < end`, tidak tumpang tindih, dan tidak melewati durasi video. Data yang invalid tidak diteruskan diam-diam ke renderer.
- Kata tunggal yang melebihi lebar frame dapat dibungkus pada batas karakter sebagai fallback. Perbaikan layout untuk kasus tersebut diputuskan saat implementasi berdasarkan contoh nyata.
- TXT mempertahankan urutan ucapan; SRT dan ASS memakai cue yang sama. Tidak ada peringkasan, terjemahan, atau koreksi oleh LLM.

VAD mengurangi pemrosesan area tanpa ucapan, tetapi tidak menjamin transkripsi selalu benar. Jika tidak ada segmen ucapan yang valid, proses berakhir dengan status **tidak ada ucapan**, bukan paket hasil palsu.

## 6. Clean architecture sederhana

```text
src/videogen/
  domain/
    models.py            # metadata video dan segmen transkrip
  application/
    ports.py             # kontrak media, transkripsi, dan render
    process_video.py     # satu use case utama
  infrastructure/
    ffmpeg.py            # probe, ekstraksi audio, dan render
    whisper.py           # adapter faster-whisper
    subtitle_files.py    # serialisasi TXT, SRT, dan ASS
  presentation/
    desktop.py           # jendela dan status
    worker.py            # entrypoint proses worker dan progres
  bootstrap.py           # menyusun dependency konkret
  __main__.py
```

- Domain berisi dataclass dan validasi sederhana, menggunakan Python standar.
- Use case menerima port `MediaProcessor`, `Transcriber`, dan `SubtitleWriter`; tidak mengimpor PySide6, faster-whisper, atau adapter FFmpeg.
- UI mengirim perintah ke worker dan menerima progres/hasil. UI tidak menjalankan inference atau render.
- Adapter menangani operasi teknis; bootstrap menyusun dependency.
- Worker membuat instance adapter sendiri; objek model AI tidak dikirim dari proses UI.
- Kebijakan pembagian cue berada pada application sebagai fungsi murni; serialisasi dan pengukuran font berada pada adapter. `SubtitleWriter` menerima spesifikasi gaya dan cue yang sudah disusun.

Satu use case cukup: `ProcessVideo(source, output_directory)`. Tidak ada repository, model revision, atau orchestrator generik pada tahap ini. Struktur ini memberi tempat untuk menambahkan preset dan riwayat nanti tanpa memindahkan aturan pemrosesan ke UI.

### Protokol worker

- UI menjalankan entrypoint Python worker melalui QProcess secara asynchronous; tidak memanggil `waitForFinished` pada thread UI.
- Worker menerima satu request berisi path sumber dan folder hasil. Gunakan argumen terpisah atau JSON, tanpa interpolasi command shell.
- Progres dikirim sebagai JSON per baris di stdout: `ready`, `stage`, `completed`, `failed`, atau `cancelled`. `failed` menyertakan pesan pengguna dan lokasi log.
- Worker menulis log diagnostik ke `${XDG_STATE_HOME:-~/.local/state}/videogen/videogen.log` (default Linux: `~/.local/state/videogen/videogen.log`). Catat waktu, tahap, file sumber/hasil, dependency/error, serta traceback exception. UI menangkap stderr worker dan menambahkannya ke log yang sama; detail teknis tidak masuk ke protokol progres.
- Rotasi log: maksimum 2 MB per file dan tiga file lama. Jangan log isi transkrip atau token/rahasia. Jika direktori log tidak dapat ditulis, laporkan keterbatasan itu melalui stderr dan tampilkan path yang seharusnya.
- Tahap hanya menampilkan aktivitas yang benar-benar sedang berjalan. Persentase ditampilkan jika didukung pengukuran, bukan estimasi yang dibuat-buat.
- `completed` memuat path ketiga file; `failed` memuat tahap, kode error, dan pesan pengguna.
- Exit worker tanpa pesan terminal dianggap gagal, kecuali pembatalan memang diminta.
- Pada Linux, worker dan subprocess media ditempatkan dalam process group khusus. Pembatalan meminta penghentian, menunggu maksimal lima detik secara asynchronous, lalu menghentikan paksa group jika masih aktif.
- Bersihkan staging setelah group berhenti. Jika aplikasi crash dan staging tertinggal, jangan menganggapnya sebagai hasil selesai; cleanup aman ditetapkan saat implementasi.

## 7. Kegagalan yang perlu ditangani

- File rusak/tidak didukung: berhenti sebelum transkripsi dengan pesan yang jelas.
- Tidak ada audio atau ucapan: laporkan bahwa subtitle tidak dapat dibuat; jangan menghasilkan transkrip palsu.
- Model, FFmpeg, libass, atau font tidak tersedia: laporkan dependency yang belum siap.
- Disk tidak cukup atau folder tidak dapat ditulis: hentikan proses dan jelaskan penyebabnya.
- Transkripsi/render gagal: tampilkan tahap gagal, ringkasan error, dan lokasi log; rincian exception tersedia pada log. Jangan menampilkan file sebagian sebagai hasil selesai.

FFmpeg dijalankan melalui daftar argumen dengan `shell=False`. Teks disimpan ke file subtitle dan di-escape sesuai format. Render ditulis ke file sementara lalu dipindahkan ke nama final setelah berhasil. File sumber tidak pernah dihapus.

Sumber dibaca langsung dan harus tetap tersedia sampai selesai; tidak membuat salinan penuh sumber pada MVP 0. Kegagalan akibat sumber berubah atau hilang dilaporkan. Path dengan spasi, Unicode, dan karakter khusus perlu ditangani oleh adapter.

## 8. Kriteria selesai

1. Video MP4/MOV berucapan menghasilkan MP4 bersubtitle, TXT, dan SRT melalui satu tombol proses.
2. Rasio, orientasi, dimensi tampilan, durasi, dan isi mengikuti sumber, dengan pengecualian padding minimum jika dibutuhkan encoder.
3. Subtitle mengikuti ucapan dan audio hasil tetap sinkron.
4. Teks terbaca pada video landscape maupun portrait tanpa keluar frame.
5. Jendela tetap responsif selama proses.
6. File sumber dan hasil sebelumnya tidak ditimpa.
7. Kegagalan memiliki pesan yang jelas dan output sebagian tidak ditandai selesai.
8. Ketiga output memiliki nama dasar sama dan status selesai hanya muncul setelah paket final tersedia.
9. Pembatalan tidak meninggalkan worker/FFmpeg aktif atau menerbitkan paket sebagian.

Pemeriksaan pertama memakai video pengguna di `assets/video/IMG_1703.MOV`. Setelah render nanti, metadata dibandingkan dengan input; target perbedaan durasi maksimal 100 ms atau dua interval frame, mana yang lebih besar. Sinkronisasi subtitle dinilai pada ucapan awal, tengah, dan akhir; target selisih awal cue terhadap ucapan maksimal sekitar 300 ms pada sampel jelas. Angka ini target penerimaan, belum hasil pengukuran.

Kriteria ini menjadi pemeriksaan saat implementasi tersedia; belum ada kode atau pengujian pada tahap rancangan.

## 9. Urutan implementasi

1. Implementasikan use case dan adapter hingga satu video nyata menghasilkan subtitle tertanam.
2. Tambahkan jendela desktop dan proses worker.
3. Periksa video pengguna, portrait/landscape, orientasi metadata, timing, serta kegagalan input dan pembatalan.

MVP 1 kemudian menambahkan preset yang bisa diganti, hook/caption, multi rasio, koreksi teks, riwayat, dan checkpoint sesuai kebutuhan pengguna.

## 10. Bahan pengguna dan bukti inspeksi

Inspeksi metadata dilakukan pada 9 Oktober 2026, tanpa transkripsi, render, atau pemutaran video.

| Properti | Hasil ffprobe |
| --- | --- |
| Sumber | `assets/video/IMG_1703.MOV` |
| Ukuran berkas | 22.821.952 byte |
| Durasi | 50,368345 detik |
| Video | H.264, yuv420p, 720 × 1280 |
| Frame rate nominal | 30/1 |
| Frame rate rata-rata | 38100/1283, sekitar 29,70 fps |
| Audio | AAC, 44.100 Hz, stereo |
| Awal audio/video | 0 detik |
| Rotasi | Tidak ada metadata rotasi pada hasil probe |
| Transfer warna | bt709; metadata yang dibaca tidak menunjukkan HDR |

Perbedaan FPS nominal/rata-rata belum membuktikan pola timing setiap frame. Pemeriksaan frame dan hasil render dilakukan saat implementasi diizinkan. Isi ucapan dan kualitas rekaman belum diperiksa.

Mesin yang diinspeksi menyediakan delapan CPU bagi proses dan sekitar 15,4 GiB RAM total. Ini mendukung pemilihan default konservatif CPU empat thread; belum merupakan bukti performa model. Binary FFmpeg dan ffprobe tersedia, tetapi kemampuan filter/encoder belum diuji.

## 11. Detail yang boleh ditetapkan selama implementasi

- Versi Python/dependency yang kompatibel, revision model, dan penyediaan resource font.
- Parameter timebase dan pemetaan offset sesuai hasil pemeriksaan media.
- Penyesuaian kecil ukuran font, gap cue, dan pemenggalan teks berdasarkan keterbacaan video contoh.
- Estimasi kebutuhan disk, timeout proses yang masuk akal, dan pembersihan staging tertinggal.
- Detail IPC/process group, logging diagnostik lokal, penanganan error, serta pemeriksaan batas dependensi.

Catat keputusan yang memengaruhi hasil di dokumen ini. Detail tersebut tidak menambah fitur MVP; preset, database, batch, hook, resize sosmed, dan resume tetap berada setelah MVP 0.

## 12. Referensi teknis

- [faster-whisper: CPU int8, word timestamps, dan VAD](https://github.com/SYSTRAN/faster-whisper).
- [FFmpeg: frame timing, fps_mode, dan timestamp](https://ffmpeg.org/ffmpeg.html).
- [Python subprocess: argumen proses dan process session](https://docs.python.org/3/library/subprocess.html).
- [Qt QProcess: proses asynchronous dan sinyal progres proses](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html).
