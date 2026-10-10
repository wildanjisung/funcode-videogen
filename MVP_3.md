# MVP 3 — Editor video visual dengan preset Videogen

Tanggal riset: 9 Oktober 2026.

Status per 10 Oktober 2026: workspace MVP 3A dan pengeditan satu sumber MVP 3B sudah diimplementasikan setelah perintah `gas`. Playback libopenshot dengan overlay libass, timeline, pemotongan, dan arsip diagnostik tersedia. Bukti otomatis dan batas evaluasi tercatat di bagian 19; sinkronisasi suara fisik dan kenyamanan desktop masih pending.

## 1. Pemahaman kebutuhan

Videogen berkembang dari generator subtitle/hook menjadi tempat menyusun video secara visual. Pengguna membuka video yang sudah memiliki gaya bawaan, melihat hasilnya, lalu melakukan penyesuaian langsung pada canvas dan waktu video. Preset yang sudah dipilih tetap menjadi titik awal; pengguna tidak perlu mengisi banyak angka.

Yang sudah jelas dari pengguna:

- Acuan pengalaman penggunaan adalah **Edits by Instagram**.
- Penataan dilakukan manual seperti aplikasi editor video.
- Preset/default yang ada dipertahankan.
- Hook dan subtitle tetap bisa diedit secara WYSIWYG; gaya/frame subtitle berlaku seluruh video sesuai keputusan MVP 2.

Yang masih merupakan usulan: timeline, playback bersuara, trim/split, beberapa klip, audio tambahan, teks tambahan, dan animasi. Menyebut editor seperti Edits belum otomatis menyetujui seluruh fitur tersebut. Lingkup bertahap di Bagian 5 perlu direview.

## 2. Apakah ada repo yang searah?

**Ada.** Beberapa proyek menyediakan pola canvas, timeline, dan pengaturan visual yang relevan. Kesesuaian dengan alur Videogen adalah penilaian desain; bukan bukti bahwa kode mereka dapat langsung dipasang pada aplikasi ini.

### Acuan produk: Edits by Instagram

Meta menjelaskan Edits sebagai aplikasi pembuatan video di ponsel dengan timeline presisi frame dan pengeditan tingkat klip. Pengalaman yang relevan untuk kita adalah preview utama, navigasi waktu, pengaturan berdasarkan objek terpilih, dan alur ekspor. Artikel juga mencakup fitur lain yang lebih luas; tidak semuanya menjadi lingkup MVP 3. Belum melakukan pemeriksaan langsung UI Edits atau membandingkan screenshot pengguna, sehingga rancangan ini tidak mengklaim kesamaan visual persis. [Pengumuman resmi Meta](https://about.fb.com/news/2025/04/introducing-edits-streamlined-video-creation-app/amp/).

### Perbandingan repo

| Referensi | Bukti dari sumber primer | Kesesuaian untuk Videogen | Batas pemakaian |
| --- | --- | --- | --- |
| [OpenCut](https://github.com/OpenCut-app/OpenCut) dan [opencut-classic](https://github.com/OpenCut-app/opencut-classic) | OpenCut sedang ditulis ulang, dengan rencana inti Rust lintas platform. Classic memiliki aplikasi Next.js dan komponen Rust, tetapi sudah diarsipkan/tidak dipelihara. | Referensi arah editor sederhana dan pemisahan UI, model proyek, dan renderer. | Rencana rewrite belum sama dengan fitur siap pakai. Classic dapat dipelajari sebagai snapshot, bukan ketergantungan yang diasumsikan terus dipelihara. [README OpenCut](https://raw.githubusercontent.com/OpenCut-app/OpenCut/main/README.md), [README Classic](https://github.com/OpenCut-app/opencut-classic). |
| [OpenVideo Editor](https://github.com/openvideodev/react-video-editor), sebelumnya URL DesignCombo | README menyebut canvas drag/resize/rotate, timeline beberapa track, trim/split/snapping, dan ekspor di browser. Stack saat ini Next.js, PixiJS/WebCodecs, dan paket OpenVideo. | Referensi interaksi canvas dan timeline paling dekat dengan penataan manual yang dibayangkan pengguna. | Frontend/engine web berbeda dari Python/Qt. URL lama mengarah ke repo ini; deskripsi lama tentang Remotion tidak cukup untuk menyimpulkan renderer saat ini. [README repo](https://github.com/openvideodev/react-video-editor). |
| [OpenShot](https://github.com/OpenShot/openshot-qt) | README menyebut Python, binding PyQt/PySide, libopenshot/libopenshot-audio, timeline, layer, transformasi, subtitle, dan ekspor FFmpeg. | Referensi teknis terdekat untuk lifecycle desktop, proyek, timeline, dan preview. | Ketergantungan engine tambahan serta cakupan UI lebih besar dari Videogen sekarang. Kedekatan Python/Qt tidak berarti modulnya bisa langsung dipakai. [README OpenShot](https://raw.githubusercontent.com/OpenShot/openshot-qt/develop/README.md). |

### Lisensi dan batas riset

- Classic mencantumkan MIT. [LICENSE Classic](https://raw.githubusercontent.com/OpenCut-app/opencut-classic/main/LICENSE).
- OpenVideo memakai lisensi Free/Company berdasarkan kategori pengguna/organisasi. File lisensinya juga membatasi penjualan/pelisensian turunan. Jangan menganggap repo ini MIT atau bebas diambil untuk semua bentuk produk. [LICENSE OpenVideo](https://raw.githubusercontent.com/openvideodev/react-video-editor/main/LICENSE).
- OpenShot mencantumkan GPL versi 3 atau lebih baru. [Pernyataan lisensi README](https://raw.githubusercontent.com/OpenShot/openshot-qt/develop/README.md), [COPYING](https://raw.githubusercontent.com/OpenShot/openshot-qt/develop/COPYING).

Temuan ini berdasarkan README, status repo, dan berkas lisensi yang dibaca pada tanggal riset. Belum mengaudit seluruh implementasi, dependency, distribusi, performa, atau kualitas output repo tersebut. Tidak melakukan clone/install/demo. Adopsi kode/engine perlu review khusus terhadap versi yang akan digunakan; mengambil pola interaksi UI tidak memerlukan migrasi stack aplikasi secara otomatis.

## 3. Posisi Videogen sekarang

Temuan berikut berasal dari sumber lokal, bukan klaim hasil pengujian GUI:

| Sudah tersedia pada sumber | Belum tersedia pada jalur saat ini |
| --- | --- |
| Hook/subtitle dengan drag, resize, font/warna/stroke dan preset berdasarkan target. | Workspace editor dengan timeline visual berisi track dan objek waktu. |
| Gaya subtitle global seluruh cue; timestamp kata disimpan. | Playback video bersuara di canvas editor. |
| Slider waktu dan preview PNG dari worker FFmpeg. | Seek berkelanjutan dengan clock audio/video dan overlay yang selalu sinkron. |
| Sesi sementara, Terapkan/Batal, Undo/Redo gaya/teks hook. | Undo/Redo lintas operasi timeline/klip. |
| Draft/proyek, revisi output, progress, diagnostik. | Model urutan klip, trim/split, time mapping, dan audio tambahan. |

Rujukan lokal:

- [Dependency dan entry point](pyproject.toml): Python, PySide6-Essentials, faster-whisper, PyAV.
- [Halaman/preview](src/videogen/presentation/desktop.py): slider dan worker preview gambar.
- [Editor visual](src/videogen/presentation/hook_style_editor.py) dan [pointer/canvas](src/videogen/presentation/hook_preview.py).
- [Proyek/preview/render](src/videogen/application/projects.py): satu sumber video, snapshot gaya, revisi hasil.
- [Penyusunan cue](src/videogen/domain/models.py), [serializer subtitle](src/videogen/infrastructure/subtitles.py), dan [FFmpeg](src/videogen/infrastructure/ffmpeg.py).

Kesimpulan: fondasi penataan overlay sudah ada, tetapi menambahkan tampilan timeline saja belum menjadikan aplikasi editor video lengkap. Gap terbesar adalah playback dan model waktu yang konsisten dengan render.

## 4. Rekomendasi arah

**Lanjutkan Videogen dengan workspace editor visual, memakai referensi interaksi OpenVideo/OpenCut dan lifecycle desktop OpenShot. Pertahankan Python/Qt dan FFmpeg sebagai arah awal.** Ini rekomendasi berdasarkan kecocokan sumber lokal, bukan keputusan engine playback yang sudah dibuktikan.

Alasannya: logika Whisper, warna kata aktif, font, preset, snapshot, dan revisi hasil sudah ada. Memindahkan seluruh aplikasi ke engine web/Rust membawa pekerjaan migrasi sebelum kebutuhan editor dasar terbukti. Jika prototype playback menunjukkan jalur saat ini tidak memadai, pilihan engine dapat ditinjau ulang dengan bukti.

Default berarti:

1. Proyek yang dibuka menggunakan snapshot gaya tersimpannya sesuai normalisasi MVP 2.
2. Proyek baru menggunakan default preset pilihan pengguna; jika tidak ada, gaya bawaan sekarang.
3. Hook tetap kapital, hitam dengan latar putih; subtitle putih, stroke tipis, kata aktif kuning, kecuali preset pengguna menentukan lain.
4. Tidak mengganti preset tersimpan atau menjadikan edit manual sebagai default tanpa tindakan eksplisit.
5. Tidak menambahkan safe zone atau koreksi posisi otomatis. Subtitle tetap global, bukan override per cue.

## 5. Usulan lingkup bertahap

### MVP 3A — Workspace editor dan navigasi video

Direkomendasikan sebagai tahap pertama:

- Preview/canvas menjadi area utama; inspector ringkas mengikuti objek Hook/Subtitle yang dipilih.
- Toolbar utama: pilih objek, font/gaya, Undo/Redo, preset, dan ekspor. Angka presisi tetap tersembunyi secara default.
- Playback/pause dengan audio, scrub waktu, serta navigasi cue. Saat mulai drag/edit, playback berhenti pada frame saat ini agar objek tidak berganti selama gesture.
- Timeline bawah dengan track Video, Hook, dan Subtitle. Video mencakup seluruh sumber; Hook menunjukkan interval aktif; Subtitle menunjukkan cue individual dengan satu gaya global.
- Klik cue memilih waktu preview, tanpa membuat gaya subtitle khusus cue. Hook mempertahankan mulai di awal dan durasi yang sudah tersedia; penggeseran interval hook ke waktu lain belum masuk tahap ini.
- Zoom timeline mengubah skala tampilan, bukan durasi atau timing. Scrub/seleksi objek tidak menambah Undo gaya.
- Drag/resize visual tetap ada. Biru selama drag berarti objek aktif; setelah release pembaruan preview ditandai jelas. Overlay/input editor tidak masuk output.
- Simpan proyek, preset/default, progress ekspor, dan buka folder hasil tetap tersedia.

### MVP 3B — Pengeditan satu klip, setelah lingkup diterima

Lingkup dan penanganan gap diterima pengguna: trim awal/akhir, split, membuang segmen dari satu video, serta Undo/Redo; urutan segmen mengikuti sumber. Keputusan rinci dan pembuktian ada pada Bagian 18. Implementasi 3B belum dimulai.

### Pengembangan berikutnya, belum menjadi komitmen

Beberapa video, susun ulang klip, musik/B-roll, teks tambahan, keyframe, transisi, speed, serta crop/aspect ratio. Menambahkannya sekaligus akan memperluas model proyek, renderer, dan UI. Pemilihan fitur dilakukan berdasarkan kebutuhan penggunaan setelah 3A/3B.

## 6. Gambaran workspace

```text
Video / proyek                 Undo  Redo   Preset   Ekspor
┌──────────────────────────────┬───────────────────────────┐
│                              │ Objek aktif: Hook         │
│         VIDEO CANVAS         │ Font / ukuran / gaya      │
│       hook dan subtitle      │ Pusatkan / reset posisi   │
│                              │ Angka lanjutan [tertutup] │
└──────────────────────────────┴───────────────────────────┘
       Play/Pause       waktu / durasi       zoom timeline
Video     [──────────────────────────────────────────────]
Hook      [interval hook]
Subtitle  [cue 1] [cue 2]     [cue 3] ...  [cue terakhir]
Status: siap / sedang menggeser / preview memperbarui / gagal
```

Desktop menyesuaikan ruang layar; tampilan ini adalah rancangan alur, bukan mockup final atau salinan screenshot Edits. Inspector dapat dilipat agar canvas tetap nyaman. Timeline tidak harus menawarkan banyak tool sebelum ada implementasi fungsi terkait.

## 7. Gap dan usulan penanganan

| Gap | Usulan penanganan | Status |
| --- | --- | --- |
| Istilah seperti Edits dapat berarti penataan overlay atau pengeditan klip penuh. | Pisahkan 3A dan 3B; tetapkan batas fitur sebelum `gas`. | Lingkup perlu diterima. |
| Preview sekarang gambar per request, bukan playback. | Gunakan libopenshot wajib untuk playback; buktikan audio, pause, seek, rotasi, codec, dan integrasi overlay sebelum menganggap layak. | Build dan adapter awal ada; runtime belum dibuktikan. |
| Renderer interaktif dapat menghasilkan glyph/layout/warna berbeda dari ASS/libass. | Gunakan model gaya/layout yang sama. Jika renderer playback berbeda, labeli sebagai preview interaktif; sediakan pemeriksaan frame FFmpeg dan jangan mengklaim kesamaan WYSIWYG final sebelum bukti cocok. | Gap teknis utama. |
| Clock playback, frame nyata, dan highlight kata dapat berbeda. | Gunakan satu waktu video sebagai playhead; overlay mengambil waktu frame yang ditampilkan, bukan hanya timer UI. Bedakan sinkronisasi preview dari akurasi onset Whisper. | Belum dibuktikan. |
| Timeline slider sekarang terbatas pada skala 0–1000. | Timeline memakai waktu sumber dan metadata frame, bukan menyalin batas resolusi slider sebagai presisi edit. Variable frame rate tidak dianggap FPS tetap. | Rancangan teknis diperlukan. |
| Banyak cue dapat membuat timeline lambat atau sulit dibaca. | Thumbnail/cue dirender hanya yang terlihat; cache berdasarkan identitas sumber/snapshot. Zoom dan scroll tidak memicu transkripsi/render final. | Performa pending. |
| Memilih satu cue dapat disalahartikan mengedit gaya cue itu saja. | Inspector tetap berlabel Subtitle · Seluruh video; selection cue hanya navigasi waktu. | Keputusan global dipertahankan. |
| Edit ketika playback berjalan dapat memindahkan objek pada cue yang berubah. | Pause saat interaksi edit dimulai; playback dilanjutkan lewat tindakan Play. | Usulan UX. |
| UI baru dapat kembali penuh kontrol dan status ambigu. | Canvas dominan, inspector kontekstual/lipat, angka tersembunyi; bedakan drag, playback, pembaruan preview, dan ekspor. | Evaluasi layar pengguna diperlukan. |
| Model draft yang ada belum mewakili urutan klip. | 3A memakai satu sumber dan model overlay saat ini; schema timeline klip baru dibuat ketika 3B diterima. Simpan atomik dan pakai snapshot ekspor tetap. | Jangan melakukan migrasi klip sebelum diperlukan. |
| Trim/split dapat merusak timing/highlight dan audio. | Data kata sumber tetap tersimpan, dengan pemetaan source time ke output time. Validasi semua cue setelah perubahan edit. | Khusus 3B, belum siap implementasi. |
| Mengadopsi repo tampak cepat tetapi stack/status/lisensinya berbeda. | Gunakan sebagai referensi awal. Sebelum mengambil kode, periksa commit, dependency, lisensi, dan kecocokan font/caption pada komponen yang benar-benar akan dipakai. | Belum ada repo/engine yang dipilih untuk integrasi. |

## 8. Urutan pekerjaan setelah rancangan diterima

1. Terima/batasi lingkup 3A dan tentukan apakah 3B harus masuk MVP 3 pertama.
2. Sesudah perintah eksekusi, buat prototype playback/canvas untuk satu video yang sudah ada; ukur sinkronisasi dan kesesuaian frame terhadap FFmpeg. Ini belum dilakukan pada riset ini.
3. Pilih engine berdasarkan bukti tersebut, lalu susun workspace dan timeline sederhana.
4. Hubungkan preset, sesi edit, Undo/Redo, snapshot ekspor, progress, serta folder hasil.
5. Pemeriksaan runtime dilakukan ketika diminta pengguna; catat bukti, keterbatasan, dan kegagalan. Tidak mengganti status pending hanya karena kode berhasil dikompilasi.

## 9. Kriteria penerimaan yang diusulkan

- Membuka proyek langsung menampilkan gaya/presetnya, tanpa penataan ulang wajib.
- Play/pause/audio/seek bekerja pada satu clock; posisi cue dan highlight mengikuti frame yang ditampilkan.
- Pengguna dapat menata Hook/Subtitle pada canvas dan menavigasi cue melalui timeline tanpa membuka angka.
- Semua cue memakai frame/gaya subtitle global; timing kata tidak berubah oleh penataan gaya.
- Drag, resize, ketik, seleksi, scrub, dan klik cue mempunyai hasil berbeda yang jelas; Undo hanya merekam perubahan edit.
- Gaya akhir tersimpan atomik, dapat dibuka ulang, dan ekspor memakai snapshot yang sama. Preview/frame pemeriksaan FFmpeg serta hasil export harus dibandingkan, termasuk tepi/clipping/font.
- UI tetap dapat digunakan pada layar minimum saat ini 800×600 dan skala layar pengguna, termasuk ketika inspector dilipat.
- Progress dan tombol lokasi hasil tetap bekerja; error/cancel tidak mengganti hasil sukses sebelumnya.

## 10. Log dan evaluasi pending

Saat implementasi nanti, catat versi editor/project, identitas sumber/snapshot/request, engine preview, waktu yang diminta dan waktu frame nyata, target/cue terpilih, gesture, preset/font, fase progres, hasil ekspor, serta referensi bukti. Jangan menambahkan isi transkrip/hook atau kunci layanan ke diagnostik.

Evaluasi awal: `playback_audio_sync`, `seek_accuracy`, `interactive_ass_parity`, `timeline_navigation`, `global_subtitle_style`, `default_preset_preservation`, `editor_usability`, `timeline_performance`, `undo_redo_session`, `export_snapshot_match`, `progress_feedback`, dan `open_result_folder` semuanya **pending**. Target toleransi presisi/performa perlu ditetapkan dari prototype, bukan dijanjikan tanpa ukuran. Akurasi onset Whisper sekitar 200 ms tetap pending dari MVP 1; playback yang sinkron tidak membuktikan timestamp Whisper benar.

## 11. Kesimpulan analisis

Repo yang searah sudah ada. Referensi interaksi terdekat adalah OpenVideo/OpenCut; referensi stack desktop terdekat adalah OpenShot. Untuk Videogen, rekomendasi awal adalah **3A: workspace editor + timeline navigasi + playback + penataan manual, dengan preset saat ini tetap menjadi default**.

Riset dan pencatatan sudah selesai. Rancangan awal masih perlu penetapan lingkup serta pembuktian pilihan playback/renderer setelah diizinkan. **Belum menyatakan semua gap aman atau siap implementasi penuh.**

## 12. Keputusan: OpenCut sebagai migrasi tertunda

Pengguna menerima bahwa penggunaan OpenCut sebagai fondasi aplikasi harus diperlakukan sebagai **proyek migrasi tersendiri**. Keputusan ini disimpan dahulu; tidak memulai migrasi, instalasi, atau perubahan implementasi MVP 3.

Migrasi nanti perlu memetakan proyek, preset, font, transkrip/timestamp, highlight kata, Undo/Redo, preview, dan snapshot ekspor. OpenCut belum ditetapkan sebagai engine MVP 3. Persetujuan pencatatan bukan perintah eksekusi; implementasi menunggu `gas` atau `eksekusi` untuk lingkup tersebut.

## 13. Evaluasi OpenShot untuk MVP 3

**Rekomendasi analisis: prioritaskan evaluasi libopenshot dibanding migrasi penuh ke OpenCut**, karena kedekatan dengan stack desktop Videogen. Ini kandidat yang lebih masuk akal secara integrasi, bukan engine yang sudah terbukti cocok.

[OpenShot editor](https://github.com/OpenShot/openshot-qt/blob/develop/README.md) memakai Python dan binding Qt, termasuk PySide6 pada cabang develop yang diperiksa. [libopenshot](https://github.com/OpenShot/libopenshot/blob/develop/README.md) adalah library C++ dengan binding Python, player Qt, compositing, dan pengolahan audio/video. Dukungan yang tercantum pada upstream tidak membuktikan paket lokal atau kompatibilitas `.venv` Videogen.

| Pilihan | Dampak | Usulan |
| --- | --- | --- |
| OpenShot sebagai referensi interaksi | Tidak mengubah stack; ambil gagasan timeline/transform dan sederhanakan kontrol sesuai kebutuhan. | Dapat dipakai dalam rancangan. |
| libopenshot sebagai engine dalam UI Videogen | Integrasi library native, binding Python/Qt, playback dan pemetaan waktu; UI, preset dan alur transkripsi tetap dikelola Videogen. | Wajib dipakai; build lokal dan adapter awal tersedia. |
| Fork seluruh openshot-qt | Membawa workspace, model proyek, dependency dan alur editor lain; perlu mengintegrasikan kembali fitur khusus Videogen. | Perlakukan sebagai proyek integrasi/migrasi; belum direkomendasikan untuk lingkup 3A. |

Library tidak otomatis menyediakan UI timeline sederhana seperti Edits. Kedekatan teknologi mengurangi perubahan bahasa/framework, tetapi tidak menghilangkan pekerjaan integrasi atau membuktikan WYSIWYG.

### Gap sebelum memilih engine

- **Binding/dependency:** pastikan versi Python, Qt6/PySide6, libopenshot, libopenshot-audio dan FFmpeg kompatibel serta dapat didistribusikan pada target pengguna. Jangan menganggap semua tersedia lewat pip.
- **Preview dan hasil:** buktikan font Helvetica Neue, ukuran, wrapping, clipping, panel hook, stroke subtitle dan highlight kata cocok dengan renderer ASS/FFmpeg saat ini. Evaluasi apakah overlay tetap dirender lewat jalur saat ini; jangan mengganti renderer sebelum bukti.
- **Waktu:** ukur audio sync, seek, frame nyata dan video variable frame rate. Binding yang berhasil dimuat tidak membuktikan ketepatan playback.
- **Data dan interaksi:** pertahankan preset default, subtitle global, Undo/Redo serta snapshot ekspor. Tentukan adapter timeline tanpa mengubah timestamp sumber.
- **Distribusi kode:** bedakan lisensi aplikasi openshot-qt (GPL-3.0-or-later) dan libopenshot (LGPL-3.0-or-later), sebagaimana README masing-masing. Tinjau komponen dan dependency yang benar-benar diambil sebelum distribusi.

Compatibility import dan build lokal kini terbukti; pembuktian runtime, playback satu sumber, sinkronisasi, parity frame, performa, dan distribusi masih **pending**. Libopenshot adalah keputusan wajib pengguna, bukan lagi kandidat yang menunggu izin. Catat hasil serta kegagalan dalam log evaluasi.

## 14. Keputusan 3A yang diterima setelah pemeriksaan gap

Pengguna menerima seluruh usulan penanganan berikut. Persetujuan rancangan tidak memulai implementasi.

### Lingkup dan integrasi

- Tahap pertama adalah **3A**: satu video sumber, workspace/canvas, playback bersuara, timeline navigasi, editor Hook/Subtitle, preset dan alur ekspor yang ada. Trim/split serta fitur pengembangan berikutnya tetap di luar 3A.
- Prioritaskan prototype libopenshot sebagai engine playback dalam UI Videogen. Ekspor tetap melalui ASS/FFmpeg saat ini sampai kesesuaian terbukti; tidak fork seluruh OpenShot atau memulai migrasi OpenCut.
- Track Video/Hook/Subtitle hanya untuk navigasi. Tidak menyediakan drag interval, trim atau split. Hook mulai di awal; durasi diubah lewat kontrol yang tersedia, termasuk pilihan sepanjang video.
- Subtitle tetap memakai satu gaya/frame global. Memilih cue mengubah waktu dan target Subtitle, bukan gaya khusus cue atau timestamp sumber.

### Waktu, canvas dan interaksi

- Gunakan waktu frame yang benar-benar ditampilkan sebagai acuan overlay. Petakan clock player ke waktu sumber; pertahankan offset `audio_start - video_start` yang sudah digunakan Videogen. Jangan menerapkan offset dua kali.
- Koordinat overlay memakai ukuran video setelah orientasi dan rasio piksel diterapkan. Letterbox di sekitar video tidak termasuk canvas. Resize jendela/skala layar tidak mengubah posisi tersimpan.
- Saat gesture edit dimulai, pause dan bekukan frame; tunda scrub/pergantian target sampai gesture selesai atau dibatalkan. Playback dilanjutkan lewat Play, bukan otomatis setelah edit.
- Inspector menentukan target aktif ketika Hook/Subtitle bertumpuk. Canvas hanya memindahkan target tersebut.
- Saat objek tidak terlihat pada waktu terpilih, sediakan frame bantu edit dengan label jelas. Frame/outline bantu tidak ikut ekspor dan tidak dianggap bukti tampilan final pada waktu itu.
- Posisi tetap bebas tanpa safe zone atau pemindahan otomatis. Sediakan Pusatkan objek dan Reset posisi untuk memulihkan objek di luar canvas; tindakan ini dapat di-Undo.
- Shortcut playback tidak mengambil Space/panah dari input teks hook. Scrub dan selection bukan perubahan gaya dan tidak menambah riwayat Undo.
- Akhir video berhenti tanpa loop otomatis. Saat ekspor dimulai, hentikan playback dan gunakan snapshot yang telah diterapkan serta divalidasi.

### Konsistensi, kegagalan dan penyimpanan

- Request terbaru saja yang boleh tampil. Kaitkan frame/cue dengan proyek, sesi, request dan snapshot yang sama; buang hasil seek/preview lama setelah edit atau pergantian proyek.
- Validasi seluruh cue setelah perubahan gaya subtitle global. Frame yang berhasil tampil tidak cukup untuk mengaktifkan ekspor.
- Perpindahan target dalam sesi mempertahankan edit sementara. Terapkan/Batal berlaku pada sesi Hook/Subtitle; perpindahan proyek atau penutupan saat ada perubahan menawarkan Terapkan, Buang perubahan, atau Tetap mengedit. Preset/default yang disimpan eksplisit tetap mengikuti perilaku MVP 2.
- Ketika proyek diganti/editor ditutup: hentikan audio/player, batalkan request, lepaskan sumber dan abaikan callback sesi lama.
- Jika engine gagal, tampilkan sebab dan lokasi log; sediakan tindakan eksplisit memakai preview gambar lama. Jangan mengubah engine diam-diam atau menghapus hasil sukses sebelumnya.
- Kesamaan font, wrapping, panel hook, posisi, clipping, stroke dan highlight terhadap frame ASS/FFmpeg harus dievaluasi. Sebelum bukti, label preview interaktif sesuai keterbatasannya dan sediakan frame pemeriksaan FFmpeg.

## 15. Kontrak log untuk analisis error dan bug 3A

**Wajib diterapkan bersama prototype, bukan ditunda sampai bug muncul.** Implementasi log awal tersedia; cakupan dan ketahanannya belum dibuktikan. Semua fase, keputusan penting, kegagalan dan hasil evaluasi harus tersimpan di disk, bukan hanya terlihat di status UI.

### Penyimpanan dan retensi

- Jalur saat ini: log aplikasi di `$XDG_STATE_HOME/videogen/videogen.log` (fallback `~/.local/state/videogen/videogen.log`), serta `diagnostics.jsonl` per proyek. Logger aplikasi saat ini berotasi 2 MB dengan tiga backup; **tidak menjamin seluruh riwayat tersimpan**.
- Untuk 3A, tambahkan arsip per run di `<project_dir>/diagnostics/mvp3a/<run_id>/`: `manifest.json`, `events.jsonl`, `evaluation.json`, dan berkas error/bukti terkait. Sebelum proyek dibuka atau bila lokasi proyek tidak dapat ditulis, gunakan direktori run di state Videogen dan tampilkan lokasinya.
- Arsip run/evaluasi tidak ditimpa run berikutnya, tidak ikut terhapus bersama temporary preview, dan tidak dihapus otomatis oleh rotasi log aplikasi. Penghapusan/arsip manual harus eksplisit; tidak menjanjikan retensi tak terbatas tanpa kapasitas disk.
- Gunakan writer terkoordinasi agar GUI/worker tidak merusak baris JSONL. Manifest dan evaluasi disimpan atomik; flush saat fase selesai, gesture commit/cancel, error, dan penutupan. Run tanpa terminal event ditandai tidak selesai saat aplikasi dibuka kembali.
- Jika penyimpanan log gagal (disk penuh, izin, lokasi hilang), tampilkan status dan lokasi alternatif; jangan melaporkan bukti tersimpan. Kegagalan log tidak menghapus output sukses. Akhir run memuat jumlah event serta apakah ada event gagal ditulis.

### Konteks minimum

Setiap event memuat versi schema log, UTC, waktu monotonic/durasi, nomor urut, `run_id`, `project_id` bila tersedia, `session_id`, operasi/fase/status. Tambahkan `request_id`, `gesture_id`, `revision_id` dan hash snapshot sesuai operasi agar bug bisa ditelusuri lintas GUI/player/worker.

Manifest memuat versi aplikasi/commit bila tersedia, Python, OS, Qt/PySide6, engine/build, libopenshot-audio, FFmpeg/libass, sumber/hash, codec, stream terpilih, dimensi/orientasi/rasio piksel, durasi/titik awal audio-video, metadata frame rate, skala layar, preset dan identitas/hash font. Nilai yang tidak tersedia ditulis sebagai tidak diketahui, bukan dikarang.

| Area | Data yang wajib dicatat |
| --- | --- |
| Lifecycle | Startup, buka/ganti proyek, init/stop/release engine, mode preview, penutupan normal/tidak selesai. |
| Playback/seek | Play/pause/end, waktu diminta dan frame aktual, audio clock jika tersedia, offset, latensi, request yang dibatalkan/diabaikan, buffering/drop bila engine menyediakan. |
| Edit | Target/cue, gesture mulai/commit/cancel dan sebab, posisi/gaya sebelum-sesudah, snapshot, Undo/Redo, status sementara/terapkan/batal, preset/default. |
| Validasi | Hash kata/gaya/font, seluruh cue valid atau daftar cue gagal beserta waktu/alasan, hasil frame pemeriksaan FFmpeg. |
| Ekspor | Snapshot/revisi, fase/progres/perubahan fase, mulai/selesai/cancel, exit code, validasi hasil, lokasi output dan tindakan buka folder. |
| Error | Operasi dan konteks aktif, tipe/pesan error yang disaring, traceback Python, stderr/exit code atau sinyal worker/engine, tindakan pemulihan dan hasilnya. |
| Evaluasi | Check ID, status pending/pass/fail/blocked/not_run, metode, toleransi, nilai terukur, lingkungan, lokasi bukti, keterbatasan. |

Jangan menulis setiap gerakan mouse/frame secara sinkron ke disk. Simpan batas gesture dan perubahan final lengkap; metrik playback menggunakan sampel berkala dan ringkasan, dengan interval/jumlah sampel serta event yang dibuang tercatat. Ini membatasi beban log tanpa menyembunyikan kegagalan. Bukti frame hanya saat pemeriksaan/error yang relevan, bukan menyalin seluruh video.

Isi transkrip/hook, kredensial dan kunci layanan tidak masuk diagnostik. Simpan hash/identitas untuk korelasi; bukti frame dapat mengandung isi video dan tetap lokal. Sediakan lokasi arsip yang mudah dibuka/disalin untuk analisis pengguna.

Crash native atau listrik mati tidak menjamin traceback/flush terakhir. Catat event sebelum operasi berisiko, terminal process/sinyal jika tersedia, dan status run tidak selesai; jangan mengklaim semua crash memiliki bukti lengkap. Pilihan isolasi engine harus dinilai pada prototype untuk membatasi dampak kegagalan native.

## 16. Kriteria evaluasi dan kesiapan prototype 3A

Sebelum menilai prototype, simpan kriteria berversi di manifest/evaluasi: toleransi sinkronisasi audio-video, error seek terhadap frame aktual (termasuk VFR), latensi seek/respons edit, kelancaran playback, kesesuaian geometri/warna/font terhadap FFmpeg, serta batas sumber/daya perangkat yang dievaluasi. Angka ditetapkan sebelum hasil diberi pass/fail; pengukuran eksplorasi tanpa toleransi tetap pending. Perubahan toleransi harus tercatat dan tidak mengubah hasil lama diam-diam.

Tambahkan pemeriksaan pending: `engine_binding_compatibility`, `source_time_offset`, `display_coordinate_mapping`, `latest_request_only`, `gesture_playback_lock`, `hidden_object_edit`, `session_navigation`, `shortcut_input_focus`, `playback_end_export_pause`, `engine_failure_recovery`, `log_persistence`, `log_write_failure`, dan `incomplete_run_detection`. Daftar Bagian 10 tetap berlaku; target onset Whisper sekitar 200 ms tetap evaluasi terpisah.

Log dianggap memenuhi rancangan setelah ada bukti run normal, gagal/cancel, reopen, serta kegagalan writer yang dievaluasi ketika pengujian diizinkan. Keberhasilan pencatatan satu event tidak membuktikan seluruh kontrak terpenuhi.

**Kesimpulan rancangan:** tidak ada gap rancangan tambahan yang diketahui menghalangi prototype 3A terbatas. Lingkup dan aturan interaksi telah diterima. Implementasi awal dengan libopenshot wajib berjalan dan catatan status ada pada Bagian 17. Kompatibilitas runtime, WYSIWYG, sinkronisasi, performa dan persistensi log tetap pending pembuktian.

## 17. Catatan historis eksekusi prototype 3A (9 Oktober 2026)

Catatan berikut menggambarkan prototype sebelum implementasi bagian 19; gap overlay/workspace di bawah telah ditangani pada implementasi terbaru.

### Implementasi dan lingkungan

- Dependency build Qt6/FFmpeg/SWIG dipasang setelah pengguna memberi izin. `libopenshot-audio` dan `libopenshot` 1.0.1 dibangun dari upstream dengan Qt6, Python 3.13 dari `.venv`, lalu dipasang di `.venv/lib`; binding berada di `.venv/lib/python3.13/site-packages`. Import menunjukkan versi 1.0.1 serta API `QtPlayer` dan `Timeline` tersedia. Ini hanya bukti kompatibilitas import, bukan bukti playback.
- Build memakai `libopenshot` commit `983c847ce7d0b7bfa4014d90bf86aa961a825f86` dan `libopenshot-audio` commit `b4b8cc7779694d75df034ef4a370a8083b07e243`; dependency native tidak masuk Git karena berada di `.venv`. Rebuild/distribusi belum otomatis.
- `infrastructure/libopenshot_player.py` memuat library lokal dan membangun `FFmpegReader → Timeline` dari metadata sumber agar dimensi/orientasi dan frame rate sumber dipakai, lalu menghubungkan `QtPlayer` ke widget PySide6. Playback/jeda, seek slider, posisi waktu, pelepasan engine, serta error dicatat. Jalur ekspor tetap ASS/FFmpeg.
- UI menyediakan mode playback libopenshot terpisah dari preview hasil FFmpeg. Label menyebut overlay hook/subtitle belum parity. Tombol kembali memulihkan preview FFmpeg; editor gaya dan ekspor menutup playback terlebih dahulu.
- Workspace sekarang menyediakan daftar navigasi cue subtitle dengan timestamp dari kata sumber; memilih cue memindahkan playhead. Scrub memakai waktu milidetik dan label menampilkan centisecond. Daftar cue adalah navigasi waktu, belum berupa track grafis berbentuk clip/bar dan belum menyediakan inspector terpilih.
- `MVP3RunLog` membuat manifest dan `events.jsonl` per run, flush tiap event dan fsync untuk fase terminal/commit, serta arsip proyek `diagnostics/mvp3a/<run_id>/`. Log menyaring field isi hook/transkrip/kredensial, menangani fallback ke direktori state atau `/tmp`, dan menandai run terputus saat proyek dibuka. GUI mencatat operasi worker/progres/error, ekspor/hash snapshot, preview, sesi editor, gesture, evaluasi, dan event player. Ini belum membuktikan retensi/kelengkapan semua kontrak.

### Belum dibuktikan / gap implementasi tersisa

- Pengguna melaporkan `name '_info' is not defined` saat membuka proyek setelah transkripsi. Penyebabnya referensi `_info` tertinggal setelah variabel hasil `load_project` diubah menjadi `info`; referensi sudah diperbaiki. Kegagalan pembukaan proyek pada jalur ini kini mencatat jenis error, pesan, dan traceback di log run. Pembuktian ulang melalui GUI masih menunggu run pengguna; proyek/transkrip yang berhasil dibuat dapat dibuka tanpa transkripsi ulang.

- Percobaan membuka `.venv/bin/videogen` sebagai jendela desktop gagal karena command environment tidak menerima `DISPLAY`; `DISPLAY=:1` juga tidak tersambung. Qt melaporkan `libxcb-cursor0` hilang. Instalasi paket itu terhalang karena `pkexec` tidak setuid dan apt tidak mendapat izin lock. MainWindow kemudian dapat dijalankan offscreen untuk menguji jalur UI.
- Probe awal menemukan mismatch PySide6 6.12 dengan build Qt 6.8.2. `.venv` kini memakai PySide6/shiboken 6.8.2 dan `pyproject.toml` mematok PySide6-Essentials ke versi yang sama agar pemasangan ulang tidak mengembalikan mismatch. Probe pertama juga menemukan seek awal diabaikan sebelum thread player aktif; adapter kini menahan seek itu dan menerapkannya setelah Play.
- MainWindow pada halaman Hook offscreen berhasil membuka `IMG_1703.MOV` (720×1280, 30 fps, 50.37 dtk) dan `HookPreview` menerima frame 720×1280. Seek slider saat playback ke 2.0 dtk terbaca 2.0 dtk; mode Pause aktif dan playhead tetap 3.6 dtk setelah 500 ms. Perangkat audio terinisialisasi pada 44.1 kHz tanpa error OpenShot; pengguna mengonfirmasi suara terdengar. Ini membuktikan audibilitas menurut konfirmasi pengguna, tetapi belum membuktikan sinkronisasi audio-video atau aplikasi dapat diluncurkan dari lingkungan GUI ini.
- Pengukuran singkat setelah seek 2.0 dtk menunjukkan playhead maju 1.6 dtk dalam 1.5 dtk dinding. Belum ada toleransi yang ditetapkan, jadi cadence/sinkronisasi tetap pending dan belum dinilai pass/fail. VFR, rotasi, codec lain, akhir video, dan recovery juga belum diperiksa.
- Detail run tersimpan pada [manifest](diagnostics/mvp3a-runtime/2026-10-09/manifest.json), [events](diagnostics/mvp3a-runtime/2026-10-09/events.jsonl), dan [evaluation](diagnostics/mvp3a-runtime/2026-10-09/evaluation.json). Statusnya partial pass: jalur frame/seek/pause/audio-init lolos dasar secara offscreen; audibilitas dikonfirmasi pengguna, sementara visible GUI belum diverifikasi pada sesi ini.
- Preview libopenshot masih menampilkan frame sumber tanpa overlay Videogen. Sinkronisasi kata/offset audio-video, parity font/layout, koordinat layar, penguncian gesture saat playback, track timeline grafis, inspector workspace dan interaksi WYSIWYG terpadu belum selesai. Navigasi cue bertimestamp sudah tersedia.
- Akurasi seek di desktop, VFR, video berputar, latensi/drop, playback berhenti di akhir, pemulihan engine gagal, serta validasi seluruh cue belum diukur. Nilai toleransi masih harus ditetapkan sebelum evaluasi pass/fail.
- Build native saat ini lokal dan berada dalam `.venv`; belum ada skrip bootstrap/rebuild atau paket distribusi yang reproduktif. Lisensi build/dependency dan target host perlu diaudit sebelum distribusi.
- Persistensi log belum diperiksa pada run normal/gagal/cancel/reopen/write failure; traceback native/crash tetap mungkin tidak tersedia.

Suite tes tidak dijalankan. Aplikasi GUI dicoba tetapi tidak dapat tersambung ke display; integrasi MainWindow diuji offscreen. Prototype 3A **belum selesai**; playback cadence, sinkronisasi A/V, visible GUI, WYSIWYG, dan timeline grafis/inspector masih harus diverifikasi. Audibilitas sudah dikonfirmasi pengguna.

## 18. Keputusan MVP 3B yang diterima pengguna

Status: rancangan disetujui dan implementasi diizinkan melalui `gas`. Hasil implementasi serta bukti terbaru tercatat di bagian 19.

### Lingkup dan model waktu

- Satu sumber video; trim awal/akhir, split, hapus segmen, dan Undo/Redo. Segmen mempertahankan urutan sumber.
- Setiap segmen memiliki ID, waktu masuk/keluar sumber, dan urutan. File sumber, kata, dan transkrip asli tetap tersimpan.
- Satu pemetaan waktu sumber ke hasil dipakai oleh playback, seek, cue, hook, highlight, dan ekspor. Offset audio-video diterapkan sekali pada acuan waktu yang disepakati.
- Interval potongan memakai awal termasuk dan akhir tidak termasuk. Batas video mengacu pada timestamp frame aktual, termasuk sumber VFR; pembulatan batas yang dilakukan engine harus tercatat.
- Batas potongan secara default mengikuti awal/akhir kata. Potong bebas tersedia dengan indikator kata terpotong sebelum ekspor. Kata terpotong tetap ditandai dan highlight dibatasi pada bagian ucapan yang dipertahankan.
- Cue dibangun ulang dari kata yang dipertahankan dan tidak melintasi sambungan segmen. Timeline, playback, preview FFmpeg, dan ekspor memakai pembentukan cue yang sama.
- Hook mulai pada detik 0 hasil edit dan durasinya dibatasi panjang hasil. Gaya subtitle tetap global.
- Timeline kosong memblokir ekspor. Segmen tanpa ucapan boleh diekspor dengan subtitle kosong yang valid; pemeriksaan kelengkapan output perlu mengakomodasi hasil ini.

### Data, interaksi, dan keluaran

- TXT/SRT hasil mengikuti segmen yang dipertahankan. Copy prompt memakai transkrip hasil edit secara default dan menyediakan pilihan transkrip sumber. Hook yang sudah ada ditandai perlu diperiksa setelah potongan berubah.
- Trim/split/hapus menjadi operasi Undo/Redo. Penyimpanan dilakukan atomik; proyek lama dibuka sebagai satu segmen penuh dengan kompatibilitas yang tervalidasi.
- Setiap perubahan edit memiliki revisi. Callback preview dari revisi lama diabaikan. Ekspor memakai snapshot segmen/gaya yang tetap dan mencatat hash snapshot.
- Progress memakai durasi hasil edit. Diagnostik menyimpan durasi sumber dan hasil.

### Bukti dan log evaluasi

- Catat operasi, ID/revisi segmen, daftar segmen sebelum/sesudah, batas diminta dan batas aktual, pemetaan waktu, kata terdampak, tindakan Undo/Redo, snapshot ekspor, pembatalan, dan error beserta traceback bila tersedia.
- Simpan bukti dan hasil evaluasi per run dengan pola manifest/events/evaluation MVP3A. Toleransi frame batas potongan, seek, durasi, sinkronisasi audio-video, dan parity overlay harus ditetapkan sebelum penilaian pass/fail.
- Kasus wajib: split tanpa menghapus bagian; trim awal/akhir; hapus bagian tengah; potong di tengah kata; sisa video tanpa ucapan; timeline kosong; Undo/Redo; simpan dan buka ulang proyek; edit saat request preview berjalan; ekspor dari snapshot tetap; gagal/batal dan pemeriksaan log setelahnya.
- Bandingkan playback dan ekspor FFmpeg pada frame sambungan, durasi hasil, audio, cue, font/layout dan highlight. Split tanpa penghapusan harus mempertahankan kontinuitas konten dan waktu sesuai toleransi yang ditetapkan.
- Status awal seluruh kasus adalah **pending/not_run**; hasil eksekusi terbaru dijelaskan pada bagian 19. Akurasi onset Whisper sekitar 200 ms tetap evaluasi terpisah.


## 19. Implementasi dan bukti 10 Oktober 2026

### Perilaku yang tersedia

- Canvas playback native libopenshot dengan hook/subtitle libass dari ASS yang sama dengan ekspor FFmpeg; inspector dapat disembunyikan melalui Pengaturan.
- Track Video/Hook/Subtitle, playhead milidetik, zoom/scroll, seek, pause, dan pembekuan posisi saat masuk editor gaya. Gaya subtitle berlaku global.
- Split, trim sebelum/sesudah, drag batas segmen, hapus, Undo/Redo, simpan dan buka kembali. Operasi menyimpan snapshot sebelum mengubah state UI.
- Snap default: tepi kata terdekat lalu timestamp frame sumber aktual terdekat; jarak sama memilih batas lebih awal. Mode bebas tetap mengikuti batas frame aktual.
- Split tanpa penghapusan menggabungkan interval yang bersambung saat pemetaan kata; identitas kata sumber dipertahankan sehingga kata tidak digandakan. Highlight kata parsial dibatasi pada bagian yang dipertahankan.
- Timeline kosong memblokir ekspor; segmen tanpa ucapan menghasilkan TXT/SRT kosong yang valid. Copy prompt default memakai transkrip hasil edit.
- Progress ekspor memakai durasi hasil. Pengindeksan frame dan diagnostik berjalan melalui proses terpisah, dengan pembatalan dan traceback. Kontrol editor terkunci selama worker aktif.
- Tombol Periksa editor / log mengarsipkan manifest, event, evaluation, ASS dan pasangan gambar overlay. Evaluasi manual juga tersimpan atomik pada arsip run; kegagalan penulisan dicatat dan dilaporkan.

### Bukti yang sudah diperoleh

- 34 pengujian lolos: regresi MVP1/2, pemetaan waktu/offset, split tanpa duplikasi, batas VFR, kata parsial, ekspor sambungan, subtitle kosong, Undo/Redo, buka ulang, identitas frame native pada video uji, dan kegagalan penyimpanan evaluasi.
- Diagnostik dijalankan dari MainWindow aktual pada salinan metadata proyek IMG_1781; sumber asli tidak diubah. Progress mencapai 100 dan kontrol kembali aktif.
- Parity raster ASS diuji pada empat waktu: mean error 8-bit maksimum 0.03781 (batas 2), fraksi piksel dengan error >16 maksimum 0.000841 (batas 0.005).
- Native mengirim 88 frame; pause tidak mengubah posisi; delta playhead 2.9 s terhadap wall-clock 2.90465 s (batas error 0.1 s); seek 27.95 s teramati 27.93333 s (batas satu frame pada 30 fps).
- Probe MainWindow pada 1040×720 dan 800×600 membuktikan kontrol/timeline muat dan masuk editor mempertahankan playhead. Kenyamanan canvas pada ukuran minimum tetap memerlukan penilaian pengguna.
- Bukti: [evaluation](diagnostics/mvp3-runtime/2026-10-10/editor-diagnostic/evaluation.json), [manifest](diagnostics/mvp3-runtime/2026-10-10/editor-diagnostic/manifest.json), [events](diagnostics/mvp3-runtime/2026-10-10/editor-diagnostic/events.jsonl), [UI proof](diagnostics/mvp3-runtime/2026-10-10/ui-proof.json), [test log](diagnostics/mvp3-runtime/2026-10-10/tests.log), dan [evaluasi pending](diagnostics/mvp3-runtime/2026-10-10/pending-evaluations.json). Path absolut dalam arsip menunjukkan lokasi bukti asli saat run.

### Batas yang tetap dicatat untuk evaluasi

- Sinkronisasi audio-video fisik, korelasi frame-clock pada video pengguna/desktop terlihat, akurasi onset Whisper sekitar 200 ms, HDR/rotasi, performa video panjang, dan kenyamanan interaksi masih pending.
- Korelasi frame native lolos pada sumber sintetis dengan identitas frame; bukti itu belum membuktikan seluruh sumber VFR atau perangkat audio.
- Lifecycle pembatalan/error ditangani, tetapi matriks crash/recovery dan pembatalan seluruh tahap belum diuji lengkap.
- Rebuild libopenshot pada mesin bersih belum dibuktikan; instalasi lokal Qt6/Python 3.13 yang sekarang dipakai telah bekerja.
- Ekspor menonaktifkan B-frame agar durasi paket frame terakhir konsisten pada CFR/VFR; ukuran file dapat meningkat. Preview FFmpeg melakukan decode menuju posisi sumber dan dapat lambat pada video panjang.
- Semua item pending harus dipakai sebagai bahan analisis berikutnya; kelulusan pengujian otomatis tidak mengubahnya menjadi passed.

### Cara evaluasi berikutnya

1. Tutup aplikasi lama, jalankan `.venv/bin/videogen`, lalu Buka proyek.
2. Uji Putar, seek, Edit hook/subtitle, Split, trim, hapus, Undo/Redo, dan Render video.
3. Klik Periksa editor / log; tunggu progress selesai. Lokasi arsip tampil pada status.
4. Gunakan Catat evaluasi / keluhan untuk gejala, posisi waktu, dan langkah reproduksi. Buka folder proyek / log untuk mengambil arsip.

- Run diagnostik final setelah penambahan log pending juga selesai dengan exit code 0; [evaluation final](diagnostics/mvp3-runtime/2026-10-10/final-diagnostic/evaluation.json).


## 20. Pemulihan editor saat layout tidak muat

Diizinkan melalui `gas`, 10 Oktober 2026.

- Seleksi/handle visual tetap berada dalam area video yang bisa diklik, termasuk ketika geometri objek yang diminta keluar frame. Proxy seleksi ini tidak mengubah koordinat/gaya ekspor; posisi objek tetap bebas ditentukan pengguna.
- Drag ukuran memakai pusat proxy yang terjangkau. Frame kuning tetap menerima drag, resize, dan edit teks; Terapkan/Render menunggu validasi terbaru.
- Saat preview gagal, gambar terakhir dipertahankan dan diberi status eksplisit. Pengguna dapat memperbaiki tanpa wajib Undo, atau memakai Pusatkan hook/subtitle yang sudah tersedia. Pusatkan hanya mengubah posisi objek aktif dan tercatat dalam history Undo.
- Pergantian target Hook/Subtitle tetap tersedia saat salah satu layout gagal. Callback preview lama tetap ditolak berdasarkan request ID.
- Event `editor_preview_recovery` mencatat target, sesi, pesan error dan geometri. Event gesture yang sudah tersedia mencatat awal/akhir interaksi.
- Pemeriksaan sintaks Python dan diff whitespace lolos. Reproduksi langsung pada desktop pengguna belum dilakukan; pemulihan kondisi screenshot belum boleh dinyatakan terbukti.
- Evaluasi pending: buat hook tidak muat, drag/resize/edit teks kembali tanpa Undo, Terapkan setelah valid; ulangi untuk subtitle, objek keluar frame, pergantian target saat gagal, Undo Pusatkan, dan respons preview lama saat drag baru.


## 21. Tahan validasi sejak mouse ditekan

Diizinkan melalui `gas`, 10 Oktober 2026.

- Klik objek/handle langsung menghentikan timer preview, menaikkan request ID, menyembunyikan warning sebelumnya, dan menampilkan seleksi biru sebelum ambang drag tercapai.
- Worker preview tidak dimulai selama pending drag atau drag aktif. Callback saat interaksi aktif ditolak, selain pemeriksaan request ID yang sudah tersedia.
- Setelah drag dilepas, jalur yang sudah ada menjadwalkan validasi geometri terbaru. Drag batal memulihkan geometri awal.
- Klik tanpa drag memulihkan status validasi sebelumnya tanpa menambah history. Jika preview sebelumnya masih pending, preview dijadwalkan ulang setelah release.
- Kehilangan capture saat pending memakai jalur release; pending state dibersihkan. Signal sesi dilepas saat editor ditutup.
- Event `editor_pointer_pressed` dan `editor_pointer_released_without_drag` melengkapi log gesture yang sudah tersedia untuk hook/subtitle.
- Compile sintaks dan diff whitespace lolos. Uji desktop untuk press-tahan, drag lambat, preview lama selesai saat mouse masih ditekan, klik tanpa gerak, batal/capture lost, serta drag berikutnya masih pending evaluasi pengguna.
