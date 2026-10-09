# Rancangan Pemrosesan Video Otomatis untuk Sosial Media

Tanggal: 9 Oktober 2026  
Status: Rancangan aplikasi desktop internal berbasis Python; belum diimplementasikan.

**Urutan pembangunan:** mulai dari [MVP_0.md](MVP_0.md), yaitu video → transkripsi audio → subtitle tertanam → output dengan ukuran mengikuti sumber. Fitur lengkap pada dokumen ini menjadi arah MVP 1 dan tahap berikutnya.

Rancangan stack dan batas clean architecture: [ARSITEKTUR_TEKNIS.md](ARSITEKTUR_TEKNIS.md).

## 1. Tujuan produk

Mengubah video mentah menjadi paket konten siap unggah melalui satu proses otomatis. Pengguna memasukkan video, memilih tujuan sosial media, lalu menerima video dengan subtitle dan ukuran yang sesuai, transkrip, serta teks hook.

Aplikasi berupa tool desktop internal untuk penggunaan pribadi. Pengguna memilih berkas dari komputer dan menyimpan hasil ke folder lokal.

Tujuan akhirnya adalah produktivitas: mengurangi waktu persiapan konten, pekerjaan berulang, dan jumlah tindakan manual per video. Pengguna dapat langsung mengunduh hasil dengan pengaturan default, lalu melakukan koreksi singkat hanya jika diperlukan.

## 2. Alur utama

1. Pilih video yang belum diedit dari komputer.
2. Pilih preset bawaan atau pribadi. Preset default sudah terpilih dan dapat diganti sebelum proses.
3. Klik **Proses video**.
4. Sistem membaca media, mentranskripsi ucapan, menyusun subtitle, membuat pilihan hook dan caption, menyesuaikan komposisi, lalu merender output.
5. Buka halaman hasil: preview video, transkrip, pilihan hook, dan file unduhan.
6. Simpan atau buka folder paket siap unggah. Koreksi teks atau pilih hook lain jika diperlukan, kemudian render ulang bagian yang terpengaruh.

Untuk MVP, durasi dan urutan isi video dipertahankan. Hook ditambahkan sebagai teks pembuka; pemilihan cuplikan, penghapusan jeda, atau perubahan urutan cerita merupakan opsi pengembangan terpisah.

## 3. Paket output

| Output | Isi |
| --- | --- |
| Video MP4 | Video berukuran sesuai preset, subtitle tertanam, dan teks hook pembuka |
| Transkrip TXT | Ucapan dalam bentuk teks yang dapat disalin atau diunduh |
| Subtitle SRT | Segmen teks beserta waktu mulai dan selesai |
| Hook | Tiga alternatif teks pembuka berdasarkan isi video; satu dipilih otomatis untuk render awal |
| Caption | Draf deskripsi posting yang dapat disalin |
| Paket ZIP | Seluruh hasil, dengan nama file yang membedakan setiap rasio |

Transkrip merepresentasikan ucapan sumber. Subtitle dapat dipecah menjadi baris pendek untuk keterbacaan. Hook dan caption adalah teks yang dihasilkan dari isi video, sehingga ditampilkan terpisah dari transkrip.

Contoh hasil satu unggahan:

```text
hasil-video/
  video-vertikal-9x16.mp4
  video-persegi-1x1.mp4
  transkrip.txt
  subtitle.srt
  hook.txt
  caption.txt
```

## 4. Fitur inti MVP

### A. Transkripsi dan subtitle otomatis

- Transkripsi otomatis dengan deteksi bahasa sumber, minimal Bahasa Indonesia dan Inggris pada MVP 0.
- Segmen subtitle memiliki timestamp agar sinkron dengan ucapan.
- Tanda baca dan pemenggalan kalimat dirapikan tanpa menambahkan informasi baru.
- Subtitle menggunakan preset kontras, pembungkusan teks otomatis, dan maksimal dua baris secara default.
- Pengguna dapat mengoreksi transkrip/subtitle pada halaman hasil tanpa membuka timeline.
- Jika sistem menyediakan indikator keyakinan, tandai bagian yang perlu diperiksa. Jangan menampilkan skor yang tidak berasal dari proses transkripsi.
- Jika tidak ada ucapan yang terbaca, tampilkan status tersebut; jangan membuat transkrip atau hook seolah-olah ada ucapan.

### B. Hook sosial media

- Buat tiga alternatif hook dari transkrip: pertanyaan, manfaat utama, dan pernyataan menarik yang didukung isi video.
- Pilih satu hook default agar proses awal selesai tanpa tindakan tambahan.
- Tampilkan hook sebagai teks pembuka selama beberapa detik; usulan awal tiga detik dan dapat diatur dalam preset.
- Batasi panjang hook agar muat pada frame; tempatkan terpisah dari subtitle.
- Hindari angka, janji, atau klaim yang tidak didukung isi video.
- Pengguna dapat mengganti hook, menulis sendiri, atau menonaktifkannya.
- Hook merupakan usulan kreatif; kualitasnya tidak dijanjikan sebagai peningkatan engagement atau viralitas.

### C. Ukuran dan komposisi otomatis

Ukuran berikut merupakan target output produk. Persyaratan unggah setiap platform perlu dikelola melalui preset yang dapat diperbarui.

| Preset | Rasio | Target resolusi | Tujuan penggunaan |
| --- | --- | --- | --- |
| Vertikal | 9:16 | 1080 × 1920 | Konten vertikal untuk Reels, TikTok, Shorts, dan Stories |
| Portrait | 4:5 | 1080 × 1350 | Konten feed portrait |
| Persegi | 1:1 | 1080 × 1080 | Konten feed persegi |
| Landscape | 16:9 | 1920 × 1080 | Konten landscape |

- Satu video dapat menghasilkan beberapa rasio dalam satu job.
- Default memakai **fit dengan latar blur** ketika rasio sumber berbeda, sehingga seluruh frame sumber tetap terlihat.
- Jika rasio sumber sama dengan output, video langsung disesuaikan ukurannya tanpa latar tambahan.
- Subtitle dan hook dihitung ulang posisi serta pembungkusannya untuk setiap rasio.
- Gunakan margin aman untuk teks; preview menyediakan panduan area yang berpotensi tertutup UI platform.
- Resolusi besar tidak dianggap menambah detail sumber. Simpan informasi resolusi sumber dan beri tahu jika output diperbesar.
- Crop otomatis mengikuti subjek dapat ditambahkan pada tahap berikutnya, dengan fallback fit jika subjek tidak jelas atau terdapat banyak subjek.

Panduan safe area bersifat perkiraan dan perlu diperbarui. Dokumentasi TikTok untuk iklan menyebut safe zone bergantung pada dimensi, panjang caption, dan format tambahan; panduan iklan tidak diperlakukan sebagai jaminan untuk seluruh konten organik. [Referensi TikTok](https://ads.tiktok.com/resources/help/article/tiktok-auction-in-feed-ads)

### D. Pemrosesan dan unduhan

- Progres per tahap: impor, analisis, transkripsi, penyusunan teks, render, dan selesai.
- Pengguna dapat berpindah tampilan selama proses berjalan. Jika aplikasi ditutup, checkpoint memungkinkan proses dilanjutkan saat aplikasi dibuka kembali.
- Job gagal menyimpan hasil tahap sebelumnya agar retry tidak mengulang pekerjaan yang sudah berhasil.
- Setiap varian memiliki status sendiri. Varian yang sudah selesai tetap dapat diunduh jika varian lain gagal.
- Sediakan tombol buka file, buka folder hasil, salin teks, dan simpan paket ZIP.
- Simpan preset terakhir untuk mengurangi pengaturan berulang.

## 5. Rancangan antarmuka desktop dan preset

### Tampilan utama

- Pilih atau tarik video dari komputer ke jendela aplikasi.
- Dropdown preset dengan preset default yang sudah terpilih.
- Ringkasan rasio, gaya subtitle, hook, dan folder hasil.
- Tombol **Proses video** dan progres per tahap.
- Daftar riwayat untuk membuka hasil atau melanjutkan proses terhenti.

### Tampilan hasil

- Preview video hasil dan pilihan varian rasio.
- Tiga alternatif hook dengan penanda yang digunakan.
- Koreksi transkrip/subtitle sederhana dan caption siap salin.
- Tombol **Terapkan koreksi**, **Buka folder hasil**, dan **Simpan ZIP**.
- Hasil lama tetap tersedia sampai versi hasil koreksi selesai.

### Preset bawaan

Nama berikut adalah usulan awal. Seluruh preset mendukung pergantian sebelum pemrosesan.

| Preset | Output default | Gaya dan perilaku |
| --- | --- | --- |
| Sosmed Vertikal | 9:16 | Subtitle kontras dua baris, hook pembuka, fit dengan latar blur |
| Minimal | 9:16 | Subtitle sederhana, hook dinonaktifkan, fit dengan latar blur |
| Edukasi | 16:9 | Subtitle kontras, hook pembuka, seluruh frame sumber terlihat |
| Multi Format | 9:16 + 1:1 + 4:5 | Satu transkripsi, beberapa hasil render dengan teks disesuaikan |

**Sosmed Vertikal** menjadi usulan preset default pertama. Pengguna dapat menetapkan preset lain sebagai default.

Preset memuat rasio/resolusi, bahasa transkripsi, font dan warna subtitle, batas baris, margin teks, hook aktif/nonaktif dan durasinya, komposisi video, serta pilihan artefak output. Folder hasil dan konfigurasi provider/model dikelola melalui pengaturan aplikasi.

- Preset bawaan dapat dipilih dan diduplikasi untuk penyesuaian.
- Preset pribadi dapat diubah, diganti nama, diduplikasi, dihapus, dan dijadikan default.
- Tombol **Kembalikan pengaturan bawaan** memudahkan pemulihan penyesuaian.
- Jika preset default pribadi dihapus, aplikasi kembali ke Sosmed Vertikal.
- Mengganti preset sebelum proses langsung memperbarui ringkasan output.
- Proses menyimpan snapshot preset. Mengubah preset saat proses berjalan hanya memengaruhi proses berikutnya.
- Mengganti preset pada hasil membuat versi pemrosesan baru; transkripsi digunakan ulang jika bahasa dan konfigurasi transkripsinya tetap sama.
- Gaya subtitle sederhana cukup untuk MVP; highlight per kata tetap fitur lanjutan.

## 6. Saran fitur untuk meningkatkan produktivitas

| Fitur | Manfaat | Prioritas |
| --- | --- | --- |
| Caption otomatis | Mengurangi pekerjaan menulis deskripsi posting | MVP |
| Preset tersimpan | Sekali atur bahasa, gaya, rasio, dan hook; gunakan berulang | MVP |
| Beberapa rasio sekaligus | Menghindari proses terpisah untuk setiap tujuan | MVP |
| Unduh seluruh hasil | Memindahkan paket konten dalam satu tindakan | MVP |
| Batch upload | Mengantrekan banyak video dengan preset yang sama | Tahap 2 |
| Brand preset | Otomatis menggunakan font, warna, logo, dan gaya bahasa brand | Tahap 2 |
| Auto reframe | Membantu mempertahankan subjek pada crop vertikal | Tahap 2 |
| Cover otomatis | Membuat gambar cover dari frame dan judul | Tahap 2 |
| Kamus istilah | Membantu koreksi nama brand dan istilah khusus | Tahap 2 |
| Ringkasan dan poin utama | Menggunakan kembali isi video untuk materi posting lain | Tahap 2 |
| Terjemahan subtitle | Menghasilkan varian bahasa dari satu video | Tahap 3 |
| Pilihan klip pendek otomatis | Membuat cuplikan dari video panjang, dengan preview hasil | Tahap 3 |
| Integrasi publikasi | Mengirim hasil ke platform setelah otorisasi pengguna | Tahap 3 |

Prioritas setelah MVP: **batch upload** dan **brand preset**, karena mengurangi langkah yang berulang saat memproses banyak konten.

## 7. Alur pemrosesan teknis

```text
Unggah video + preset
        ↓
Validasi media dan baca metadata
        ↓
Ekstraksi audio → transkripsi dengan timestamp
        ↓
Susun subtitle + hook + caption
        ↓
Terapkan komposisi untuk setiap rasio
        ↓
Render video → simpan output → paket unduhan
```

Arsitektur ditetapkan sebagai aplikasi desktop Python:

- PySide6 untuk jendela, pemilihan berkas, pengaturan preset, progres, dan preview hasil.
- Core Python untuk aturan produk dan orkestrasi pemrosesan.
- Proses worker lokal terpisah untuk transkripsi dan render.
- faster-whisper untuk transkripsi lokal dengan timestamp.
- FFmpeg/ffprobe untuk analisis media, ekstraksi audio, subtitle, dan output video.
- SQLite untuk riwayat, preset pribadi, revisi, serta checkpoint.
- Folder lokal untuk sumber kerja dan output. File sumber pengguna tidak ditimpa.
- Adapter model bahasa untuk hook dan caption; provider/model dipilih terpisah tanpa mengubah core.

Detail implementasi, struktur folder, dan aturan dependensi tersedia di [ARSITEKTUR_TEKNIS.md](ARSITEKTUR_TEKNIS.md).

Transkripsi dilakukan sekali per sumber dan digunakan kembali untuk semua rasio. Perubahan hook tidak perlu menjalankan transkripsi ulang. Koreksi subtitle memicu penyusunan subtitle dan render; hook/caption ditandai perlu diperbarui jika isi koreksi mengubah makna.

Jika audio tidak memadai, hasil transkripsi kosong, atau pembuatan teks gagal, laporkan keterbatasannya dan sediakan output yang berhasil. Jangan menandai seluruh paket lengkap ketika komponen wajib belum tersedia.

## 8. Ukuran keberhasilan produk

- **Waktu aktif pengguna:** waktu untuk memilih video, mengatur, meninjau, dan mengambil hasil; dipisahkan dari waktu tunggu mesin.
- **Langkah manual:** jumlah tindakan yang diperlukan untuk menghasilkan paket siap unggah.
- **Hasil tanpa koreksi:** persentase job yang digunakan tanpa perubahan subtitle, hook, atau komposisi.
- **Keberhasilan job:** persentase video sumber valid yang menghasilkan seluruh output terpilih.
- **Waktu dan biaya pemrosesan:** durasi serta biaya per menit video dan per varian render.

Target angka ditetapkan setelah pengukuran pada contoh video nyata. Sasaran UX awal: alur utama pilih video, proses, dan buka hasil; pemeriksaan hasil tetap tersedia.

## 9. Kriteria penerimaan MVP

Kriteria ini untuk implementasi berikutnya, belum diuji pada tahap rancangan.

1. Pengguna memasukkan satu video tanpa menyuntingnya dan menerima paket hasil otomatis.
2. Video berucapan menghasilkan transkrip TXT dan subtitle SRT yang bertimestamp.
3. Output MP4 memuat subtitle serta hook default, kecuali hook dinonaktifkan.
4. Semua rasio terpilih dihasilkan dengan dimensi sesuai preset.
5. Audio dan urutan video tetap sesuai sumber; subtitle sinkron dengan ucapan.
6. Hook dan caption berlandaskan isi transkrip serta dapat disalin dan diganti.
7. Mengganti hook atau mengoreksi teks tidak memerlukan pemilihan ulang sumber.
8. Job dapat dilanjutkan melalui retry tahap gagal dan hasil yang sudah selesai tetap tersedia.
9. Preset default otomatis terpilih; preset dapat diganti, diduplikasi, dan disimpan sebagai preset pribadi.
10. Status menjelaskan jika video tidak memiliki ucapan, media tidak didukung, atau output hanya berhasil sebagian.
11. Jendela tetap responsif selama pemrosesan dan checkpoint dapat dilanjutkan setelah proses terhenti.
12. Perubahan preset tidak mengubah snapshot proses berjalan atau hasil lama.

## 10. Keputusan yang sudah ditetapkan dan yang masih terbuka

Sudah ditetapkan:

- Aplikasi desktop internal berbasis Python.
- Pemrosesan otomatis dengan koreksi hasil yang sederhana.
- Preset default yang bisa diganti serta preset pribadi.
- Clean architecture dengan core terpisah dari UI, database, FFmpeg, dan provider AI.

Masih perlu ditentukan sebelum implementasi terkait:

- Rentang durasi dan ukuran sumber berdasarkan contoh penggunaan.
- Model transkripsi yang sesuai RAM/GPU dan kualitas Bahasa Indonesia pada mesin pengguna.
- Model/provider hook dan caption: lokal atau layanan eksternal.
- Lokasi folder kerja, folder hasil, dan kebijakan pembersihan data sementara.

Satu video menghasilkan video bersubtitle, transkrip, tiga pilihan hook, caption, dan ukuran terpilih secara otomatis. Pengaturan dibuat minimal agar pengguna cepat memproses video berikutnya.
