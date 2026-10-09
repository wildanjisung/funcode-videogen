# Pemeriksaan MVP 1

Tanggal: 9 Oktober 2026. Pemeriksaan menggunakan checkout lokal, Helvetica Neue Bold pada cache, serta video pengguna `assets/video/IMG_1703.MOV`.

## 1. Bug dan gap implementasi

| Gap | Perbaikan | Bukti |
| --- | --- | --- |
| Clipping sebelum offset | Sanitasi transkrip tanpa clipping; offset diterapkan sebelum clipping video | Kata audio 11–11,5 dengan offset −2 tetap tampil pada video 9–9,5 |
| Overlap antarcue | Kata yang overlap berada dalam grup/cue yang sama | Input 0–2 dan 1,5–2,5 menjadi satu cue 0–2,5 |
| Akhir kata terpotong | Akhir cue menggunakan nilai akhir terbesar semua kata | Kata 0–2 tetap berakhir pada 2 walau kata berikutnya berakhir pada 1,2 |
| Layout memakai perkiraan karakter | Layout final memakai metrik file font; pembungkusan dan ukuran per cue tetap selama highlight | Render kata 35 huruf W dan fallback segmen muat pada portrait dan landscape |
| Font hanya diperiksa keberadaannya | Validasi format, keterbacaan, family, weight 700, dan style non-italic | Font hilang, rusak, DejaVu Sans, serta Helvetica Neue Regular ditolak |
| Font render tidak tercatat | Log dan pemeriksaan nama PostScript `fontselect` | Worker video nyata mencatat `HelveticaNeue-Bold`; substitusi/missing evidence ditolak pada tes |
| Setup font belum lengkap | README menjelaskan font lokal, override path absolut, unduhan preview personal, dan pemeriksaan font | Langkah menggunakan default cache maupun `VIDEOGEN_FONT_PATH` terdokumentasi |

## 2. Tes regresi

Perintah:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Hasil: **13 tes lulus, tanpa skip**. Mencakup offset positif/negatif, clipping tepi video, overlap, akhir kata yang bersarang, urutan kata pada timestamp sama, batas empat kata, warna pada jeda, presisi ASS, font salah, layout panjang, fallback segmen, dan kegagalan yang jelas ketika teks tidak dapat muat pada ukuran minimum.

Font layout pada instalasi lain memerlukan file Helvetica Neue Bold melalui cache atau `VIDEOGEN_FONT_PATH`. Jika tidak tersedia, lima tes layout ditandai skip; hasil tersebut tidak setara dengan pemeriksaan lengkap lokal ini.

## 3. Render portrait dan landscape

Pemeriksaan memakai video sintetis hitam dengan audio kosong, dimensi 720 × 1280 dan 1280 × 720, serta renderer aplikasi yang sama. Masker piksel glyph diperiksa pada kata panjang, fallback segmen, jeda putih, dan kata aktif. Semua delapan sampel memiliki glyph di dalam area horizontal 8%–92% frame. Fallback segmen dan jeda tidak memiliki glyph kuning; kata aktif memiliki glyph kuning.

Artefak lokal:

- [Hasil pemeriksaan piksel](output/mvp1-verification/layout/pixel-checks.json).
- [Preview portrait](output/mvp1-verification/layout/preview-720x1280.mp4).
- [Preview landscape](output/mvp1-verification/layout/preview-1280x720.mp4).

## 4. Pipeline video nyata

Perintah:

```bash
.venv/bin/python -m videogen.worker_main \
  --source assets/video/IMG_1703.MOV \
  --output output/mvp1-verification \
  --log-file output/mvp1-verification/worker.log
```

Worker selesai dengan exit code 0 dan menghasilkan paket MP4, TXT, dan SRT. Log font:

```text
Subtitle font validated: family=Helvetica Neue style=Bold weight=700 postscript=HelveticaNeue-Bold
fontselect: (Helvetica Neue, 700, 0) -> HelveticaNeue-Bold, 0, HelveticaNeue-Bold
```

| Properti | Hasil |
| --- | --- |
| Dimensi sumber dan hasil | 720 × 1280 |
| Durasi video sumber | 50,368333 detik |
| Durasi video hasil | 50,366667 detik |
| Selisih durasi | −1,666 ms |
| Paket hasil | MP4, TXT, dan SRT tersedia |

Korelasi waveform audio membandingkan satu detik audio sumber dengan hasil di sekitar detik 1, 25, dan 49. Audio didekode mono 16 kHz, lalu pencarian offset menggunakan langkah 0,5 ms dalam rentang ±200 ms.

| Sampel | Pergeseran audio hasil dari sumber | Korelasi ternormalisasi |
| --- | --- | --- |
| Awal, pusat detik 1 | 0 ms | 0,999589 |
| Tengah, pusat detik 25 | 0 ms | 0,999040 |
| Akhir, pusat detik 49 | 0 ms | 0,999333 |

Artefak lokal:

- [Video hasil lengkap](output/mvp1-verification/IMG_1703_subtitled_a669bd7fa4/IMG_1703_subtitled.mp4).
- [Log worker](output/mvp1-verification/worker.log).
- [Metadata dan korelasi audio](output/mvp1-verification/media-checks.json).
- Klip untuk menilai highlight terhadap ucapan: [awal](output/mvp1-verification/awal.mp4), [tengah](output/mvp1-verification/tengah.mp4), [akhir](output/mvp1-verification/akhir.mp4).

## 5. Batas bukti

Korelasi audio membuktikan audio hasil tidak bergeser dari sumber pada tiga sampel. Ini tidak mengukur akurasi timestamp Whisper terhadap awal/akhir kata yang sebenarnya diucapkan. Target sekitar 200 ms pada kriteria penerimaan belum dinyatakan lulus berdasarkan anotasi ucapan independen. Klip disediakan untuk pemeriksaan tersebut.

Status `pending`, target 200 ms, alasan perlunya anotasi ucapan independen, dan tautan klip dicatat pada log worker pemeriksaan. Untuk proses berikutnya, aplikasi otomatis mencatat status evaluasi serta sampel cue awal/tengah/akhir dengan indeks dan timestamp video. Isi transkrip tidak dimasukkan ke log; nilai pengukuran error tetap `unmeasured` sampai evaluasi independen dilakukan.

File hasil dan cache font bersifat lokal serta diabaikan Git. Laporan ini menyimpan hasil pemeriksaan; tautan artefak memerlukan file lokal yang masih tersedia. Instalasi Linux baru seluruhnya belum dilakukan; setup font, validasi, dan kasus dependency gagal diperiksa pada environment yang tersedia.
