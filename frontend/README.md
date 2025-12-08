# CCTV Analytics - Frontend ReactJS

Frontend aplikasi SaaS CCTV Analytics yang dibangun dengan ReactJS, menggunakan Vite sebagai build tool.

## Fitur

- **Authentication**: Login dengan JWT (OAuth2PasswordBearer)
- **Role-based Access**:
  - Admin: Akses penuh (tambah kamera, atur zona)
  - Staff: Hanya melihat kamera sesuai branch_id
- **Camera Management**:
  - Lihat daftar kamera
  - Tambah kamera baru (Admin only)
- **Zone Management**:
  - Atur zona area meja dengan canvas drawing (Admin only)
  - Tipe zona: Table (Meja) dan Refill
- **Snapshot Viewer**:
  - Lihat snapshot real-time dari kamera
  - Auto refresh setiap 5 detik

## Teknologi

- **React 19.2.0**
- **React Router DOM** - Routing dan navigation
- **Axios** - HTTP client untuk API calls
- **JWT Decode** - Decode JWT token
- **Vite** - Build tool dan dev server

## Instalasi

1. Install dependencies:

```bash
npm install
```

2. Pastikan backend FastAPI sudah berjalan di `http://localhost:8000`

3. Jalankan development server:

```bash
npm run dev
```

4. Buka browser di `http://localhost:5173` (atau port yang ditampilkan)

## Struktur Folder

```
src/
├── components/          # Komponen React
│   ├── Login.jsx       # Halaman login
│   ├── Dashboard.jsx  # Dashboard utama
│   ├── CameraList.jsx # Daftar dan manajemen kamera
│   ├── ZoneEditor.jsx # Editor zona dengan canvas
│   └── SnapshotViewer.jsx # Viewer snapshot kamera
├── contexts/           # React Context
│   └── AuthContext.jsx # Context untuk authentication
├── services/           # API services
│   └── api.js         # Konfigurasi axios dan API functions
├── utils/             # Utility functions
│   └── ProtectedRoute.jsx # Protected route component
├── App.jsx            # Root component dengan routing
└── main.jsx           # Entry point

```

## Konfigurasi

### API Base URL

Edit `src/services/api.js` untuk mengubah base URL backend:

```javascript
const API_BASE_URL = 'http://localhost:8000';
```

## Penggunaan

### Login

1. Buka aplikasi di browser
2. Login dengan username dan password
3. Default admin: `admin` / `admin123` (jika sudah di-seed)

### Dashboard

Setelah login, Anda akan diarahkan ke dashboard yang menampilkan:

- Daftar kamera yang dapat diakses
- Tombol untuk melihat snapshot
- Tombol untuk atur zona (Admin only)

### Menambah Kamera (Admin)

1. Klik tombol "+ Tambah Kamera"
2. Isi form:
   - Nama Cabang
   - RTSP URL (atau `0` untuk webcam)
3. Klik "Simpan"

### Mengatur Zona (Admin)

1. Klik "Atur Zona" pada kamera yang diinginkan
2. Klik dan drag pada gambar untuk membuat rectangle zona
3. Isi nama zona dan pilih tipe (Table atau Refill)
4. Klik "Simpan"

### Melihat Snapshot

1. Klik "Lihat Snapshot" pada kamera yang diinginkan
2. Snapshot akan otomatis refresh setiap 5 detik
3. Klik "Refresh" untuk manual refresh

## Build untuk Production

```bash
npm run build
```

File hasil build akan berada di folder `dist/`.

## Catatan

- Pastikan backend FastAPI sudah berjalan sebelum menggunakan frontend
- Token JWT disimpan di localStorage
- Token akan otomatis expire setelah 24 jam
- Jika token expired, user akan otomatis diarahkan ke halaman login
