# Panduan Deteksi Gorengan

## Overview

Sistem deteksi gorengan mendukung deteksi berbagai jenis gorengan secara spesifik menggunakan custom YOLO model.

## Setup

### 1. Persiapan Custom Model

#### Opsi A: Menggunakan Custom YOLO Model (Recommended)

1. Latih custom YOLO model untuk deteksi gorengan spesifik
2. Simpan model di `backend/models/gorengan_model.pt`
3. Update `config_gorengan.py` dengan class mapping yang sesuai

#### Opsi B: Menggunakan Deteksi Umum (Fallback)

- Jika tidak ada custom model, sistem akan menggunakan deteksi wadah (mangkok/gelas) sebagai indikator stock
- Kurang akurat tapi tetap berfungsi

### 2. Konfigurasi

Edit file `backend/config_gorengan.py`:

```python
# Mapping class ID dari model ke nama gorengan
GORENGAN_CLASS_MAPPING = {
    0: "bakwan",
    1: "tahu_goreng",
    2: "tempe_goreng",
    # ... tambahkan sesuai model Anda
}

# Path ke model
GORENGAN_MODEL_PATH = "models/gorengan_model.pt"

# Threshold confidence
GORENGAN_CONFIDENCE_THRESHOLD = 0.4

# Minimum stock untuk alert
MIN_STOCK_THRESHOLD = 3
```

### 3. Struktur Folder

```
backend/
├── models/
│   └── gorengan_model.pt  # Custom YOLO model (optional)
├── config_gorengan.py     # Konfigurasi mapping
└── ai_core.py             # AI engine
```

## Cara Kerja

### Deteksi Gorengan Spesifik

1. Jika custom model tersedia, sistem akan:
   - Mendeteksi berbagai jenis gorengan secara spesifik
   - Tracking stock per jenis gorengan
   - Alert jika stock habis atau rendah

### Deteksi Umum (Fallback)

2. Jika custom model tidak ada:
   - Menggunakan deteksi wadah (mangkok/gelas) sebagai proxy
   - Tetap bisa tracking stock secara umum
   - Alert jika tidak ada wadah terdeteksi

## Output

### Zone State

```json
{
  "total": 5,
  "detail": {
    "bakwan": 2,
    "tahu_goreng": 1,
    "tempe_goreng": 2
  }
}
```

### Billing Events

Setiap jenis gorengan akan di-log terpisah:

```json
[
  { "zone_name": "Gorengan 1", "item_name": "GORENGAN_BAKWAN", "qty": 2 },
  { "zone_name": "Gorengan 1", "item_name": "GORENGAN_TAHU_GORENG", "qty": 1 },
  { "zone_name": "Gorengan 1", "item_name": "GORENGAN_TOTAL_STOCK", "qty": 5 }
]
```

### Alerts

- `low_stock`: Stock habis atau di bawah threshold
- `SEDANG_DIAMBIL`: Ada aktivitas mengambil (tangan terdeteksi)

## Training Custom Model

### 1. Persiapan Dataset

- Kumpulkan gambar berbagai jenis gorengan
- Label menggunakan format YOLO (class_id x y w h)
- Minimal 100-200 gambar per jenis untuk hasil yang baik

### 2. Training

```bash
# Contoh training dengan YOLOv8
yolo detect train data=gorengan_dataset.yaml model=yolov8n.pt epochs=100 imgsz=640
```

### 3. Export Model

```bash
# Export model untuk production
yolo export model=runs/detect/train/weights/best.pt format=torchscript
```

### 4. Deploy

- Copy model ke `backend/models/gorengan_model.pt`
- Update `config_gorengan.py` dengan class mapping

## Troubleshooting

### Model tidak terdeteksi

- Pastikan file ada di `backend/models/gorengan_model.pt`
- Cek path di `config_gorengan.py`
- Pastikan format model compatible dengan Ultralytics YOLO

### Deteksi tidak akurat

- Turunkan `GORENGAN_CONFIDENCE_THRESHOLD` (misalnya 0.3)
- Latih ulang model dengan dataset yang lebih banyak
- Pastikan lighting dan angle kamera sesuai dengan training data

### Stock tidak terdeteksi

- Pastikan zona gorengan sudah di-set dengan benar
- Cek apakah objek berada dalam batas zona
- Jika menggunakan fallback, pastikan ada wadah (mangkok/gelas) di zona

## Catatan

- Custom model bersifat optional
- Sistem akan otomatis fallback ke deteksi umum jika model tidak ada
- Untuk hasil terbaik, gunakan custom model yang sudah dilatih dengan dataset lokal
