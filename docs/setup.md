# Setup lokal (Windows + VSCodium)

## 1. Kebutuhan

- Python 3.11–3.13 disarankan untuk kompatibilitas paket.
- Arduino IDE dengan dukungan board ESP32.
- Library ArduinoJson dan Adafruit NeoPixel.
- ESP32-S3 dan PC berada di jaringan lokal yang sama.

## 2. Siapkan backend

Jalankan perintah dari folder utama repository:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
Copy-Item server\.env.example server\.env
```

Buka `server/.env` dan ganti `DEVICE_TOKEN` serta `DASHBOARD_TOKEN` dengan nilai acak yang panjang. Jangan commit file tersebut. Jika ingin memakai parsing berbasis OpenAI, pasang SDK dengan `..\.venv\Scripts\python.exe -m pip install openai` dari folder `server`, lalu isi `OPENAI_API_KEY` dan `OPENAI_MODEL`. Integrasi ini opsional.

Jalankan server dari folder utama:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --host 127.0.0.1 --port 8000
```

Tes `http://127.0.0.1:8000/api/health`. Untuk koneksi dari ESP32, jalankan server dengan `--host 0.0.0.0` dan gunakan alamat IPv4 PC di jaringan lokal. Izinkan akses firewall hanya untuk jaringan privat jika memang diperlukan.

## 3. Siapkan firmware

Buka `firmware/esp32_aiot.ino`. Ubah `WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_BASE`, dan `DEVICE_TOKEN`. `DEVICE_TOKEN` harus sama dengan nilai di `server/.env`. `SERVER_BASE` harus memakai IPv4 PC, bukan `127.0.0.1`, saat dipanggil dari ESP32.

Upload firmware ke board. Buka Serial Monitor pada 115200 baud untuk melihat koneksi Wi-Fi, heartbeat, dan hasil perintah. Jika board tidak menggunakan LED RGB addressable di GPIO 48, sesuaikan konfigurasi pin dan tipe LED.

## 4. Buka dashboard

Buka `dashboard/index.html` di browser. Masukkan alamat backend dan nilai `DASHBOARD_TOKEN`. Untuk browser di PC yang sama, gunakan `http://127.0.0.1:8000`.

Dashboard statis ini mengirim token dari browser. Gunakan hanya di perangkat pribadi dan jaringan tepercaya; jangan menerbitkan dashboard dengan token sungguhan. Jika browser menolak permintaan lintas-origin, gunakan server HTTP lokal untuk menyajikan dashboard atau sesuaikan kebijakan CORS backend dengan origin yang dipakai.

## 5. Perintah yang didukung

- `nyalakan LED`
- `matikan LED`
- `bikin LED kedip terus`
- `hentikan kedip LED`
- `cek status`

Perintah dimasukkan ke antrean dan dijalankan ketika ESP32 melakukan polling. Efek berkedip dijalankan tanpa `delay()` panjang agar loop tetap bisa mengirim heartbeat dan menerima perintah.
