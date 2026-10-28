# Nexora AIoT

Proyek ESP32-S3 untuk memantau perangkat dan mengendalikan LED RGB melalui backend Python dan dashboard web lokal. Perintah bisa dikirim lewat tombol dashboard atau teks bahasa Indonesia. Parser lokal tetap tersedia tanpa API AI.

## Isi repository

- `firmware/esp32_aiot.ino` — firmware ESP32-S3, heartbeat, polling perintah, dan efek LED.
- `server/main.py` — API FastAPI, antrean perintah, autentikasi token, dan status perangkat.
- `dashboard/index.html` — antarmuka web untuk status dan kontrol perangkat.
- `server/.env.example` — contoh konfigurasi tanpa kredensial asli.
- `docs/setup.md` — langkah instalasi dan koneksi.

## Status

Proyek masih dikembangkan. Firmware pada salinan ini menggunakan LED RGB addressable pada GPIO 48 (umum pada beberapa ESP32-S3 DevKit); pastikan cocok dengan board yang dipakai.

## Mulai

Lihat [panduan setup](docs/setup.md). Jangan unggah file `server/.env`, password Wi-Fi, token asli, atau API key.

## Batasan yang diketahui

- Backend menyimpan status dan antrean di memori; restart server akan menghapus data sementara.
- Contoh ini ditujukan untuk LAN tepercaya, bukan server publik.
- HTTP lokal tidak mengenkripsi lalu lintas. Jangan membuka port backend langsung ke internet.
- Token yang dimasukkan ke dashboard browser dapat dilihat oleh orang yang punya akses ke browser/file tersebut.
- Dukungan LED bergantung pada board dan pin RGB yang tersedia.

## Lisensi

Belum ada lisensi yang ditambahkan. Jika repository dipublikasikan, tentukan lisensi yang sesuai sebelum mengizinkan penggunaan ulang oleh pihak lain.
