# Perbaikan alur simpan dan render

27 Oktober 2026. Lingkup: controller/form UI web; tidak mengubah transkrip, draft pengguna, worker, atau aturan validasi render pada backend.

## Penyebab dan bukti

- Proyek terakhir memiliki draft versi 3, sementara preview terakhir selesai untuk versi 2. Layout preview valid, tetapi snapshot sudah usang. Controller lama menonaktifkan render sampai pengguna memperbarui preview secara manual.
- Save dinonaktifkan ketika draft sudah tersimpan, tetapi label tetap `Simpan draft`; alasan tidak terlihat.
- Input posisi memakai `step=1`, sementara drag/keyboard menghasilkan koordinat pecahan. Reproduksi DOM dengan posisi `50.12` memicu `validity.stepMismatch` dan memblokir seluruh tombol. Validasi tersebut sebelumnya tidak menyebut kolom penyebabnya.

## Perubahan

- Toolbar memakai label **Draft tersimpan** setelah simpan berhasil, disertai status penyimpanan.
- Status alur selalu menjelaskan tindakan berikutnya, termasuk saat menyimpan, memeriksa preview, merender, hook kosong, atau nilai tidak valid.
- **Render MP4** otomatis menyimpan draft, membuat preview terbaru bila diperlukan, memeriksa seluruh cue, lalu merender. Backend tetap menuntut preview dan hash timing yang sesuai.
- Input posisi/lebar/durasi/stroke menerima desimal yang didukung model. Nilai tidak valid diberi `aria-invalid`, nama kolom, alasan, dan tombol untuk memfokuskan kolom tanpa menghapus isinya.
- Subtitle tidak muat menghentikan render, menampilkan waktu/reason cue pertama, serta menyediakan tindakan menuju pengaturan subtitle.
- Perubahan saat pemeriksaan berlangsung membatalkan kelanjutan render otomatis; tidak merender hook lama. Preview manual tetap tidak memulai ekspor otomatis.

## Verifikasi

Tes controller/form dengan jsdom: **9 lulus**. Menggunakan HTML dan controller produksi, menjalankan event input/click, serta memeriksa permintaan API yang dihasilkan. Kasus render lama dan koordinat pecahan direproduksi gagal sebelum perbaikan.

```bash
npm ci --prefix tests/web
npm test --prefix tests/web
```

Tes API/worker terdekat: **9 lulus**, termasuk penolakan snapshot usang dan layout tidak valid.

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p test_web.py -v
```

Halaman, JavaScript dan CSS di localhost diperiksa melalui HTTP; hash aset yang disajikan sama dengan source terbaru. Backend tidak perlu direstart untuk perubahan aset statis. Tidak melakukan simpan/render pada proyek pengguna untuk verifikasi ini. Browser computer-use tidak tersedia; belum mengklaim screenshot atau pemeriksaan visual layout.
