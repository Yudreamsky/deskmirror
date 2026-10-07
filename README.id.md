[English](README.md) · [简体中文](README.zh-CN.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · **Bahasa Indonesia**

# DeskMirror

Penerjemah layar untuk Windows. Letakkan "cermin" yang bisa diseret di mana saja di desktop: di dalam bingkainya,
bagian layar yang sama tampil dengan teks yang sudah diterjemahkan di tempat aslinya; di luar bingkai, desktop Anda
tetap seperti biasa. Halaman web, PDF, aplikasi, gim, dan subtitel video semuanya diterjemahkan dengan cara yang sama,
tanpa ekstensi peramban.

![Cermin digeser ke kotak dialog gim dan teks Jepangnya berubah menjadi bahasa Inggris](docs/images/hero-en.gif)

Baru pertama kali? Mulailah dengan [panduan singkat](docs/QUICKSTART.en.md) (panduan yang sama terbuka saat pertama kali
dijalankan), lalu [panduan pengguna](docs/GUIDE.en.md). Keduanya dalam bahasa Inggris; ada juga versi bahasa Mandarin.

## Contoh tampilan

DeskMirror yang dijalankan pada halaman uji proyek ini (layanan terjemahan: DeepSeek). Terjemahan di gambar berbahasa
Inggris; bila Anda memilih bahasa Indonesia sebagai bahasa ibu, terjemahannya tampil dalam bahasa Indonesia.

| Halaman web | Subtitel video |
|---|---|
| ![Halaman web berbahasa Mandarin; di dalam cermin teksnya berbahasa Inggris](docs/images/web-en.jpg) | ![Video bersubtitel Mandarin; di dalam cermin subtitelnya berbahasa Inggris](docs/images/video-en.jpg) |
| **Gim dalam mode jendela** | **PDF** |
| ![Gim berbahasa Jepang: misi, menu, penghitung waktu, papan nama, dan dialog semuanya berbahasa Inggris](docs/images/game-en.jpg) | ![PDF berbahasa Mandarin; di dalam cermin abstraknya berbahasa Inggris](docs/images/pdf-en.jpg) |

**Komik**: teks vertikal di dalam balon kata langsung dibaca dan diganti di tempatnya; garis tepi balon tetap utuh.

<img src="docs/images/manga-en.jpg" width="560" alt="Halaman komik berbahasa Jepang: balon kata dan narasinya berbahasa Inggris">

## Fitur

- **Di tempat aslinya**: terjemahan muncul di posisi teks asli, dengan ukuran dan warna yang sedekat mungkin; tahan
  Ctrl+Alt+O untuk melihat teks aslinya.
- **Mengikuti layar**: menggulir, memindahkan dan menumpuk jendela, subtitel video. DeskMirror memperhatikan apa yang
  berubah di layar, jadi tidak bergantung pada program tertentu.
- **Menerjemahkan lebih dulu di latar belakang**: teks di layar tempat cermin berada diterjemahkan lebih awal, jadi ke
  mana pun cermin diseret, terjemahannya sudah siap; tidak ada yang diterjemahkan dua kali.
- **Pilih layanan terjemahan sendiri**: model [Ollama](https://ollama.com) lokal (gratis, teks tidak keluar dari PC
  Anda), atau API apa pun yang kompatibel dengan OpenAI seperti DeepSeek, Qwen, atau OpenAI.
- **Privasi di tangan Anda**: daftar program yang tidak diterjemahkan (aplikasi obrolan, pengelola kata sandi, dan
  perbankan daring dilewati secara bawaan; saat mengobrol dengan rekan atau teman dari luar negeri, nyalakan
  "Translate chat apps" dengan sekali klik), tiga cakupan terjemahan awal, dan pemakaian hari ini sekilas. Teks di
  layar tidak disimpan ke disk secara bawaan.
- **Ganti bahasa kapan saja**: tombol bahasa di tab cermin (misalnya "Auto→ID") menentukan bahasa sumber dan bahasa
  tujuan. Mendukung bahasa Mandarin, Inggris, Jepang, Korea, dan Indonesia.
- **Antarmuka bahasa Inggris atau Mandarin**: saat pertama kali dijalankan, Anda memilih bahasa ibu; terjemahan muncul
  dalam bahasa itu. Antarmuka hanya tersedia dalam bahasa Mandarin dan Inggris, jadi bila memilih bahasa Indonesia,
  antarmukanya berbahasa Inggris. Keduanya bisa diubah nanti di Settings.
- **Glosarium**: istilah di glosarium selalu dipakai, dan istilah lain pun dijaga tetap konsisten. Subtitel dan dialog
  gim diterjemahkan dengan beberapa baris sebelumnya sebagai konteks, sehingga nama dan gaya bicara tetap runtut.
- **Pas di tempatnya**: terjemahan yang lebih panjang dari aslinya lebih dulu dipadatkan sedikit, lalu meminjam ruang
  kosong di dekatnya, dan baru setelah itu diperkecil. Terjemahan tidak meluber ke tepi panel, gambar, atau video.
- **Komik**: teks vertikal di balon kata dikenali langsung. Terjemahan bahasa Mandarin dan Jepang ditulis vertikal di
  tempat aslinya, dan bahasa Inggris diletakkan rata tengah di dalam balon.
- **Terjemahan gambar**: tekan Ctrl+Alt+V atau klik "Image" di tab untuk mengirim isi bingkai ke model yang bisa
  membaca gambar (secara bawaan gemma4:12b di Ollama). Cocok untuk huruf dekoratif, efek suara, dan teks di dalam
  gambar.
- Juga: panel riwayat, menyunting terjemahan, beberapa cermin sekaligus, cermin yang mengikuti jendela, jeda, tangkapan
  layar.

## Pemasangan

Yang Anda perlukan:

- Windows 11 (Windows 10 seharusnya bisa, tetapi belum diuji)
- Layanan terjemahan, salah satu dari:
  - Lokal: pasang [Ollama](https://ollama.com), lalu jalankan `ollama pull gemma4:12b` (sekitar 7,6 GB; perlu kartu
    grafis dengan memori video yang besar)
  - Cloud: kunci API untuk DeepSeek atau layanan serupa (bayar sesuai pemakaian)

### Unduh dan langsung pakai (disarankan)

1. Unduh `DeskMirror-<versi>-win64.zip` (sekitar 140 MB) dari
   [Releases](https://github.com/Yudreamsky/deskmirror/releases/latest).
2. Ekstrak ke folder mana pun yang bisa ditulisi (misalnya Documents atau drive D:), lalu klik dua kali
   `DeskMirror.exe`. Selanjutnya cukup ikuti panduan memulai.
   - Jika Windows menampilkan "Windows melindungi PC Anda" (programnya tidak bertanda tangan kode), klik
     "Info selengkapnya" → "Tetap jalankan".
   - Pengaturan dan log disimpan di folder itu. Untuk memperbarui, ekstrak versi baru ke lokasi yang sama dan timpa
     yang lama; pengaturan Anda tetap tersimpan.
   - Jangan mengekstrak ke C:\Program Files (pengaturan tidak bisa ditulis di sana dan akan disimpan di
     `%LOCALAPPDATA%\DeskMirror`).
3. Tidak perlu Python; model pengenalan teks (termasuk bahasa Korea) sudah ada di dalam paket.

### Menjalankan dari kode sumber

1. Pasang [Python 3.12](https://www.python.org/downloads/) (centang "Add python.exe to PATH" saat memasang).
2. Ambil kodenya: `git clone https://github.com/Yudreamsky/deskmirror.git`, atau unduh ZIP dari GitHub lalu ekstrak.
3. Klik dua kali `setup.bat`. Ini membuat `.venv` dan memasang dependensi (PySide6, RapidOCR, ONNX Runtime, dan
   lainnya; perlu koneksi internet).
4. Klik dua kali `start.bat`. Model pengenalan teks ikut terpasang bersama paketnya; model bahasa Korea (sekitar
   14 MB) diunduh saat pertama kali Anda memilih "Original: Korean".
5. Untuk membuat exe sendiri: `.venv\Scripts\python -m pip install -r requirements-build.txt`, lalu
   `.venv\Scripts\python packaging\build.py`.

Untuk memakai layanan cloud: pilih "Cloud service" di langkah 3 panduan memulai, atau klik ⚙ di tab cermin →
Translation service, pilih "OpenAI-compatible API", isi alamat, model, dan kunci API, lalu klik "Test connection".

Pengenalan teks secara bawaan memakai kartu grafis (DirectML, kartu apa pun yang mendukung DirectX 12) dan otomatis
beralih ke CPU bila tidak tersedia.

## Cara pakai

Panduan memulai terbuka saat pertama kali dijalankan (langkah 1 menanyakan bahasa ibu Anda; panduan ini bisa dibuka
lagi kapan saja dari menu baki sistem). Lihat [panduan singkat](docs/QUICKSTART.en.md) dan
[panduan pengguna](docs/GUIDE.en.md). Tindakan yang sering dipakai:

| Yang ingin dilakukan | Caranya |
|---|---|
| Memindahkan atau mengubah ukuran cermin | Seret tab di atas cermin; seret bingkai biru |
| Melihat teks asli sebentar | Tahan Ctrl+Alt+O |
| Menyembunyikan / menampilkan cermin | Ctrl+Alt+H |
| Melihat lagi subtitel dan dialog barusan | Ctrl+Alt+Y membuka panel riwayat |
| Jeda (bingkai tetap ada; tidak mengenali, tidak menerjemahkan) | Klik "Pause" di tab |
| Memilih bahasa (misalnya EN→ID, ZH→ID, JA→ID) | Klik tombol bahasa di tab |
| Menerjemahkan aplikasi obrolan (saat mengobrol dengan teman dari luar negeri) | Klik kanan tab atau ikon baki → "Translate chat apps" |
| Terjemahan gambar (komik, huruf dekoratif, teks di dalam gambar) | Ctrl+Alt+V, atau klik "Image" di tab |
| Pengaturan | Klik ⚙ di tab, atau klik kanan ikon baki |

## Privasi

- Dengan layanan terjemahan cloud, teks yang dikenali di layar dan judul jendela dikirim ke layanan tersebut. Jika itu
  penting bagi Anda, pakai Ollama di PC Anda sendiri, atau persempit cakupan terjemahan awal dan tambahkan program ke
  daftar yang tidak diterjemahkan di Settings.
- Kunci API dienkripsi dengan akun Windows Anda (DPAPI) dan disimpan di PC ini dalam `deskmirror.json`.
- Log hanya mencatat waktu dan jumlah, tidak pernah teks di layar. "Remember translations" mati secara bawaan; bila
  dinyalakan, terjemahan disimpan terenkripsi di PC ini.
- Terjemahan gambar mengirim tangkapan layar isi bingkai ke model gambar yang diatur di Settings. Secara bawaan itu
  Ollama di PC Anda, jadi gambarnya tidak keluar; dengan layanan cloud, Anda selalu ditanya dulu sebelum gambar dikirim.

## Keterbatasan yang diketahui

- Sejauh ini baru diuji di satu PC (Windows 11, 3840×2160 dengan skala 100%, RTX 4090).
- Gim layar penuh eksklusif dan video yang dilindungi hak cipta tidak bisa ditimpa atau ditangkap; mainkan gim dalam
  mode tanpa bingkai (borderless) atau mode jendela.
- Huruf dekoratif, huruf piksel, dan teks yang sangat kecil bisa salah dibaca. Teks vertikal terbaca baik bila
  kolomnya rapi seperti di balon kata komik; untuk efek suara yang ditulis miring, pakai terjemahan gambar. Untuk teks
  bahasa Korea, pilih "Original: Korean" lewat tombol bahasa (beralih ke model pengenalan bahasa Korea).
- Selengkapnya di [panduan pengguna](docs/GUIDE.en.md#known-limitations).

## Pengembangan

```bat
:: Uji unit (tidak perlu layar maupun model)
.venv\Scripts\python.exe -m unittest discover -s tests -t .

:: Jalankan dengan jendela konsol untuk melihat log
start.bat debug
```

## Lisensi

[GPL-3.0](LICENSE). Copyright © 2026 Yudreamsky.

Komponen pihak ketiga dan lisensinya: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Kontak

a885187@gmail.com

DeskMirror gratis dan sumber terbuka, dan semua fiturnya bisa dipakai. Jika bermanfaat bagi Anda, Anda bisa
[mentraktir saya kopi di Ko-fi](https://ko-fi.com/dreamskyu) (juga lewat About → Support the author di aplikasi).
