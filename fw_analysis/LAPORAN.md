# Analisis statis — PXN-V10 Firmware Update V0.47

Berkas: `pxn-v10-firmware-update-v0.47_1\PXN-V10 Firmware UpdateV0.47.exe` (3.597.312 B,
SHA-256 `135f2ef44089549a11852620f44c9cc2c5ccabcab24b100c4c96e20333617055`, PE32 GUI, MFC statis, timestamp build 2024-03-08).

**Metode:** hanya analisis statis (parser PE, Capstone, pembacaan byte). EXE **tidak pernah dijalankan** dan **tidak ada** paket
yang dikirim ke setir. Semua angka alamat di bawah dapat diperiksa ulang dengan `xref.py` / `hidparse.py` di folder ini.
Tanda: **[pasti]** = terbaca langsung dari byte/kode; **[inferensi]** = kesimpulan dari pola, belum diuji pada perangkat.

## 1. Isi EXE (hasil bongkar)

| Bagian | Isi |
|---|---|
| `.rsrc` (1,38 MB) | Hampir seluruhnya aset skin MFC Office-2007 (553 PNG, 5 style XML, bitmap, ikon) + string MFC standar Tionghoa. **Tidak ada firmware di sini.** |
| `.rdata` @ `0x5B0E30` | **Image firmware A** — 54.284 B (`0xD40C`) |
| `.rdata` @ `0x5BE240` | **Image firmware B** — 109.375 B (`0x1AB3F`) |
| Kode updater | `0x403300–0x403E00`; memakai `HID.DLL` + `SETUPAPI` + `CreateFileW/WriteFile/ReadFile` (tanpa driver khusus) |

Ukuran kedua image diambil dari konstanta di kode updater (`mov esi,0xD40C` / `mov esi,0x1AB3F`), bukan ditebak.
Hasil ekstraksi: `extracted/imageA_54284.bin` (SHA-256 `8a5017e3…deb1`), `extracted/imageB_109375.bin` (`2e699d39…6c53`),
beserta deskriptor HID terurai (`hid_descriptor_*.bin/.txt`). Tidak ada enkripsi atau kompresi **[pasti]**.

## 2. Dua image firmware

* **Pemilihan [pasti]:** updater menjalankan `wcsstr(path_perangkat, "vid_11ff&pid_0020")`. Bila cocok → image **A**,
  selain itu → image **B**. (`vid_11ff&pid_0020` adalah ID HID bootloader.)
* **Image A** — STM32F103-class (periferal USB `0x40005C00`, RCC `0x40021000`, TIM1 `0x40012C00`), di-link di `0x08002400`
  (di belakang bootloader ±9 KB); Reset_Handler = startup Cortex-M standar. Berisi string `Microsoft.Xbox.Input.Wheel`.
  Deskriptor USB/HID-nya disimpan dalam bentuk yang tidak lazim (byte descriptor tercampur dengan kode) sehingga **tidak dapat
  saya urai penuh**. **[inferensi]** hardware generasi lama.
* **Image B** — Cortex-M4F (kode memakai instruksi FPU `vstr s0`), SP awal `0x200031F8`, vektor reset `0x406F5`. Memuat string
  produk UTF-16 `PXN-V10 Wheel`, `MSFT100` (descriptor Microsoft OS), `Windows.Xbox.Input.Wheel`. Ini firmware yang cocok dengan
  setir yang diuji (11FF:3245).

## 3. Identitas USB di image B [pasti]

| VID:PID | Kelas | Mode |
|---|---|---|
| `11FF:3245` | HID | **D-Input** (PXN-V10 Wheel), bcdDevice `0x002D` |
| `046D:C260` | HID | meniru **Logitech G29 (mode PS4)** |
| `11FF:F201` | vendor FF/FF/FF | Xbox One wheel (GIP) |
| `11FF:A408` | vendor FF/FF/FF | mode konsol/vendor lain |
| config X-Input | `FF/5D/01` | Xbox 360 class, EP IN 4 ms / OUT 8 ms |

**Konfigurasi D-Input (11FF:3245)** — 2 antarmuka HID:
* **#0 Game controller** (deskriptor 1347 B): input report ID 1 = 18 B → `X`,`Y` (16-bit bertanda ±32767), `Z,Rx,Ry,Rz,Slider`
  (16-bit), hat, 24 tombol. Ini persis 7 sumbu + 24 tombol yang terbaca di PC. FFB = **USB PID standar**: 14 slot efek,
  efek Constant/Ramp/Square/Sine/Triangle/SawUp/SawDown/Spring/Damper/Inertia/Friction; output report ID 1–14 (terbesar 17 B),
  feature report 5/6/7 (create-effect, block-load, pool). EP IN 0x81 **bInterval 2 ms**, EP OUT 0x01 **1 ms**.
* **#1 Keyboard + Mouse** (61 B + 56 B = 117 B): inilah mekanisme remap tombol ke Keyboard/Mouse di aplikasi.

**Kesimpulan penting untuk konfigurasi USB:** deskriptor D-Input tidak punya report vendor-defined untuk konfigurasi.
Protokol konfigurasi (`0x50–0x54`) tidak lewat antarmuka USB D-Input; ia hanya tersedia lewat Bluetooth. Ini menjawab
pertanyaan sebelumnya: aplikasi desktop tidak akan menemukan "antarmuka konfigurasi USB" pada setir ini.

## 4. Protokol updater (bootloader) [pasti dari disassembly; arti nama perintah = inferensi]

1. Tahan HOME, colok USB → setir menjadi HID `vid_11ff&pid_0020` (sesuai `Installation instruction.txt`).
2. Updater membuka perangkat (`CreateFileW`, `HidD_SetNumInputBuffers(200)`).
3. Handshake: kirim `01 81 00 00 00` (ID 1, perintah `0x81`), lalu `ReadFile` berulang + `Sleep` sampai ada jawaban.
4. Data: paket `[01][80][38][seq_lo][seq_hi][56 byte data]` per blok (blok terakhir diisi nol), progres = `offset*100/ukuran`.
5. Selesai: perintah `0x83`, `Sleep(500 ms)`, satu paket penutup.

Tidak ada CRC/penandatanganan di sisi PC, tidak ada baca-ulang untuk verifikasi, dan trailer kedua image tidak berisi checksum yang
terlihat **[pasti]**. Validasi, bila ada, ada di bootloader (tidak ada di EXE ini).

## 5. Yang bisa dioptimalkan (diurutkan menurut bukti)

1. **Kurva pedal nol di setir Anda — kandidat bug firmware** *(kode [pasti], akibat [inferensi])*.
   Rutin init (`B+0x2EA…0x4AC`) menangani **4 slot kurva** (4 × 48 B = `0xC0`). Logikanya: bila satu *magic* di blok setelan
   valid → salin 0xC0 B tersimpan ke RAM; **kalau tidak** isi keempat slot dengan kurva linear default `(1365,21845)(2730,43690)(4095,65535)`.
   Hanya ada **satu** pemeriksaan magic, tanpa validasi per slot. Setir yang diuji (fw 0.46) punya kurva Gas normal tetapi Rem & Kopling
   nol → konsisten dengan blok setelan lama yang valid tetapi slot 2–3 belum pernah diisi.
   *Usulan:* validasi tiap slot saat load (semua nol / tidak monoton → reinit default) atau naikkan versi magic saat layout berubah.
   *Solusi sisi aplikasi (sudah ada):* tombol "Reset kurva" menulis default.
2. **Latency input D-Input:** EP IN 2 ms (500 Hz) sementara EP OUT (FFB) 1 ms. Menyamakan IN ke 1 ms bisa memangkas rata-rata ±0,5 ms.
   *Perlu verifikasi* laju update sensor/kontrol internal; manfaat kecil. Mode X-Input (4/8 ms) dan PS4 (4 ms) meniru perangkat asli — jangan diubah.
3. **Deskriptor HID, cacat kecil [pasti]:** selector *Effect Type* mendaftar **13 usage** (`0x28` ganda) padahal rentang logis 1–12;
   hat switch pada deskriptor D-Input `Input(0x02)` tanpa flag Null-State (`0x42`, seperti yang benar di deskriptor PS4). Dampak praktis rendah di Windows.
4. **`bcdDevice` basi:** tetap `0x002D` (0.45) pada paket v0.47. Windows/diagnostik tidak bisa membedakan versi; versi asli hanya terbaca lewat protokol konfigurasi (setir Anda: 0.46).
5. **Updater:** tambahkan verifikasi (CRC/baca-ulang), pesan error spesifik, dan tanda tangan image. Saat ini bootloader menerima blok 56 B tanpa autentikasi yang terlihat dari sisi PC — risiko rantai pasok/penyalahgunaan.
   Ukuran EXE 3,5 MB sebagian besar aset UI yang tidak terpakai (tidak berpengaruh ke setir).
6. **Opcode tak terdokumentasi:** rantai dispatch di B (`B+0x15A94…0x15B1E`) menangani ID `0x47–0x4B`, `0x50–0x57`, `0x60–0x69` dan
   mengembalikan nilai float. **Bukan** protokol konfigurasi PRD (itu hanya kebetulan angkanya mirip) — kemungkinan pembaca parameter internal.
   Artinya tidak diketahui; jangan dikirim ke setir.

## 6. Batasan dan hal yang tidak dilakukan

* Tidak membandingkan v0.46 dengan v0.47 (hanya v0.47 yang ada). Jika EXE v0.46 diberikan, perbedaannya bisa di-diff untuk melihat apa yang berubah.
* Image A tidak terurai penuh; peran tepatnya (generasi hardware) adalah dugaan.
* Tidak ada firmware yang dimodifikasi, dan tidak ada alur flash yang dibuat atau diuji. Memodifikasi image lalu mem-flash berisiko membuat setir tidak bisa menyala
  (bootloader menerima blok tanpa validasi yang terlihat, sehingga satu image rusak bisa menimpa seluruh aplikasi). Perbaikan nomor 1–3 sebaiknya disampaikan ke PXN.
* Setir yang diuji melapor fw **0.46**; v0.47 tersedia. Isi perubahan v0.47 tidak diketahui — tidak ada jaminan ia memperbaiki masalah kurva.
