# Verifikasi UI web Videogen

Tanggal: 27 Oktober 2026. Host pengujian: Linux x86_64, Python 3.13.5. [Rekaman runtime](runtime.json) memuat ID job/proyek/revisi, metadata video, hasil pemeriksaan layout, ukuran/hash artefak, dan versi dependency.

## Hasil

| Pemeriksaan | Bukti |
| --- | --- |
| Seluruh regresi | **43 tes lulus**, 15,950 detik; mencakup 9 tes web dan tes desktop/subtitle/timeline sebelumnya |
| Worker preview/render asli | Tes web menghasilkan PNG, MP4, TXT, SRT melalui worker Python dan FFmpeg; model transkripsi sengaja tidak tersedia pada tes render ulang |
| Transkripsi nyata melalui HTTP | Unggah potongan 8 detik dari `assets/video/IMG_1703.MOV`, model faster-whisper-small lokal menghasilkan 23 kata |
| Preview nyata | HTTP 200 PNG; semua cue valid, font terverifikasi worker; [frame preview](preview.png) diperiksa secara visual |
| Render dan unduhan | MP4 1.726.570 byte, TXT 126 byte, SRT 422 byte; seluruh unduhan HTTP 200 |
| Playback/range | HTTP 206 untuk range hasil MP4; tes proxy playback juga lulus |
| Revisi dan draft | Draft/revisi terbaca ulang; setelah restart server, hash MP4 sama dengan hasil sebelum restart |
| Stale preview | Perubahan versi draft menolak render dari preview lama; perubahan hash timing ditolak worker |
| Cue tidak muat | Preview mengembalikan alasan validasi; render ditolak sampai semua cue valid |
| Pembatalan | Proses anak worker lifecycle dihentikan; slot aktif dan timer dibersihkan, termasuk saat upload dibatalkan |
| Akses lokal | Host/Origin lintas situs ditolak; path font dari payload browser ditolak; upload dibatasi dan file parsial dibersihkan |
| Sintaks | `python -m compileall -q src` dan `node --check src/videogen/web/static/app.js` lulus |
| Konsistensi HTML/JS | Seluruh 72 referensi elemen statis ditemukan; 80 ID HTML unik |
| Dependency | `pip check`: tidak ada requirement rusak |

Perintah regresi:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -v
```

Server yang digunakan untuk smoke test:

```bash
.venv/bin/videogen-web --data-dir output/web --port 8765
```

Data media/proyek uji tetap berada di `output/web` dan `output/web-smoke`, yang sudah diabaikan Git. Bukti di direktori ini tidak menyertakan seluruh video hasil atau teks transkrip lengkap.

## Batas bukti

- Inventori computer-use menunjukkan `apps: []`, `browsers: []`. **Belum ada pengujian interaksi atau screenshot UI browser**, termasuk drag/keyboard, playback bersuara, dan responsive layout. Pemeriksaan HTML, JavaScript, API, serta frame FFmpeg tidak menggantikan bukti tersebut.
- Windows/macOS belum diuji secara native. Tes pemetaan path dan cleanup berbasis psutil belum menjadi bukti lintas OS.
- Tidak mengklaim akurasi onset kata 200 ms. Tidak melakukan anotasi timing independen.
- Terdapat deprecation warning dari TestClient Starlette tentang adapter httpx dan warning SWIG pada tes libopenshot lama; seluruh tes tetap lulus.
- Sandbox menghambat event loop lintas thread pada TestClient. Tes/runtime berhasil ketika dijalankan di luar sandbox; ini dipisahkan dari kegagalan kode produk.

Panduan instalasi dan batas fitur: [WEB_UI.md](../../../WEB_UI.md).
