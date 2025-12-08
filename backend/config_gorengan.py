"""
Konfigurasi untuk deteksi berbagai jenis gorengan
Sesuaikan dengan custom YOLO model yang Anda gunakan
"""

# Mapping class ID dari custom YOLO model ke nama gorengan
# Format: {class_id: "nama_gorengan"}
# Contoh jika model Anda memiliki 10 class gorengan:
GORENGAN_CLASS_MAPPING = {
    0: "bakwan",
    1: "tahu_goreng",
    2: "tempe_goreng",
    3: "pisang_goreng",
    4: "lumpia",
    5: "risol",
    6: "pastel",
    7: "cireng",
    8: "gehu",
    9: "combro",
    10: "molen",
    11: "tahu_isi",
    12: "tempe_mendoan",
    13: "bakwan_sayur",
    14: "perkedel"
}

# Nama-nama gorengan yang didukung (untuk validasi)
SUPPORTED_GORENGAN_TYPES = list(GORENGAN_CLASS_MAPPING.values())

# Threshold confidence untuk deteksi gorengan
GORENGAN_CONFIDENCE_THRESHOLD = 0.4

# Path ke custom model (relatif dari folder backend)
GORENGAN_MODEL_PATH = "models/gorengan_model.pt"

# Minimum stock untuk alert "low stock"
MIN_STOCK_THRESHOLD = 3

