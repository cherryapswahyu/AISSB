import cv2
import json
import sqlite3
import numpy as np
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List

# Library FastAPI
from fastapi import FastAPI, HTTPException, Depends, status, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
import os
import asyncio
from collections import defaultdict

# Library Security
from jose import JWTError, jwt

# Import passlib dengan patch untuk bypass detect_wrap_bug
# Error terjadi saat passlib mencoba detect bug dengan password panjang (>72 bytes)
# Solusi: Patch detect_wrap_bug SEBELUM CryptContext digunakan
try:
    import passlib.handlers.bcrypt as bcrypt_module
    # Patch detect_wrap_bug untuk selalu return False (skip bug detection)
    # Ini harus dilakukan sebelum backend di-set
    if hasattr(bcrypt_module, 'detect_wrap_bug'):
        bcrypt_module.detect_wrap_bug = lambda ident: False
except:
    pass

# Import CryptContext setelah patch
from passlib.context import CryptContext

# Patch lagi setelah import untuk memastikan
try:
    import passlib.handlers.bcrypt as bcrypt_module
    bcrypt_module.detect_wrap_bug = lambda ident: False
except:
    pass

# Import Database Lokal
from database import get_db_connection, init_db
import threading

# ==========================================
# 0. SHARED FRAME CACHE (Untuk Streaming & Analysis)
# ==========================================
# Cache untuk menyimpan frame terakhir dari setiap kamera
# Streaming endpoint akan update cache ini, analysis endpoint akan membaca dari sini
frame_cache = {}  # {cam_id: {"frame": np.array, "timestamp": float}}
frame_cache_lock = threading.Lock()  # Thread-safe access

# ==========================================
# 0.4. WEBSOCKET CONNECTION MANAGER (Untuk Real-time Detection)
# ==========================================
# Manager untuk menyimpan koneksi WebSocket aktif per kamera
websocket_connections = defaultdict(set)  # {cam_id: set(websocket_connections)}
websocket_lock = threading.Lock()

# Cache untuk deteksi terakhir per kamera (untuk WebSocket)
detection_cache = {}  # {cam_id: detection_data}
detection_cache_lock = threading.Lock()

# Cache untuk zone states, billing, dan alerts per kamera (untuk WebSocket)
zone_states_cache = {}  # {cam_id: zone_states_data}
billing_cache = {}  # {cam_id: billing_data}
alerts_cache = {}  # {cam_id: alerts_data}
data_cache_lock = threading.Lock()

# ==========================================
# 0.3. BACKGROUND CAMERA THREADS (Auto Detection)
# ==========================================
# Thread untuk setiap kamera yang membaca frame secara kontinyu di background
camera_threads = {}  # {cam_id: threading.Thread}
camera_threads_lock = threading.Lock()
camera_threads_running = {}  # {cam_id: bool} - Flag untuk stop thread
background_service_enabled = True  # Flag untuk enable/disable background service
background_service_lock = threading.Lock()  # Lock untuk thread-safe access

# ==========================================
# 0.1. GLOBAL STATE MANAGEMENT (Untuk Zone States)
# ==========================================
# Global Memory untuk Timer Meja Kotor & Status Antrian
# Format: { "Meja 1": 5, "Kasir": 3 } -> Meja 1 kotor sdh 5 detik
global_zone_states = {}  # {zone_name: state_value}
state_lock = threading.Lock()  # Thread-safe access

# ==========================================
# 0.1.1. TRACKING DURASI (Untuk Laporan)
# ==========================================
# Tracking start time untuk meja terisi dan antrian penuh
table_occupancy_tracking = {}  # {zone_name: {"start_time": datetime, "camera_id": int, "person_count": int}}
queue_tracking = {}  # {zone_name: {"start_time": datetime, "camera_id": int, "queue_count": int}}
tracking_lock = threading.Lock()  # Thread-safe access

# ==========================================
# 0.2. AI ENGINE (Shared Instance)
# ==========================================
# Load AI Engine sekali saat startup untuk digunakan oleh semua endpoint
_ai_engine = None
_ai_engine_lock = threading.Lock()

def get_ai_engine():
    """Get or create AI engine instance (singleton)"""
    global _ai_engine
    if _ai_engine is None:
        with _ai_engine_lock:
            if _ai_engine is None:
                from ai_core import SuperAIEngine
                print("⏳ [API] Loading AI Engine...")
                _ai_engine = SuperAIEngine()
                print("✅ [API] AI Engine ready!")
    return _ai_engine

# ==========================================
# 1. KONFIGURASI KEAMANAN (SECURITY CONFIG)
# ==========================================
SECRET_KEY = "rahasia_soto_cloud_super_aman_jangan_disebar" # Ganti string ini di production!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # Token berlaku 24 Jam

# Setup Password Hashing (Bcrypt)
# Environment variable sudah di-set di atas sebelum import passlib
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Setup OAuth2 (Endpoint untuk login adalah /token)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Init App
app = FastAPI(title="Soto Cloud SaaS API V6.0")

# Setup CORS (Agar React bisa akses)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Di production, ganti "*" dengan "http://localhost:3000"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Init Database saat server nyala
@app.on_event("startup")
def startup_event():
    # Pastikan patch detect_wrap_bug diterapkan sebelum backend di-set
    try:
        import passlib.handlers.bcrypt as bcrypt_module
        bcrypt_module.detect_wrap_bug = lambda ident: False
    except:
        pass
    
    try:
        init_db()
        print("[Startup] Database initialized")
    except Exception as e:
        print(f"[Startup] Error initializing database: {e}")
    
    # Start background detection service
    try:
        start_background_detection_service()
        print("[Startup] Background detection service started")
    except Exception as e:
        print(f"[Startup] Error starting background service: {e}")
        import traceback
        traceback.print_exc()
    
    print("[Startup] ✅ Server startup completed!")

@app.on_event("shutdown")
def shutdown_event():
    # Stop semua background threads saat server shutdown
    stop_all_camera_threads()

# ==========================================
# 2. MODEL DATA (PYDANTIC SCHEMAS)
# ==========================================

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    username: str
    password: str
    role: str       # 'admin' atau 'staff'
    branch_id: Optional[int] = None # Wajib diisi jika role='staff'

class BranchInput(BaseModel):
    name: str
    address: Optional[str] = None
    phone: Optional[str] = None

class CameraInput(BaseModel):
    branch_id: int  # ID dari tabel branches
    rtsp_url: str

class ZoneInput(BaseModel):
    camera_id: int
    name: str
    type: str       # 'table', 'kasir', 'gorengan', 'refill', 'queue', 'restricted'
    coords: list[float] # [x1, y1, x2, y2]

# ==========================================
# 3. FUNGSI BANTUAN (HELPER FUNCTIONS)
# ==========================================

def verify_password(plain_password, hashed_password):
    """
    Verify password dengan bcrypt.
    Konsisten dengan get_password_hash - jika password > 72 bytes, hash dengan SHA256 dulu.
    """
    password_bytes = plain_password.encode('utf-8')
    
    # Jika password lebih dari 72 bytes, hash dengan SHA256 dulu (konsisten dengan get_password_hash)
    if len(password_bytes) > 72:
        plain_password = hashlib.sha256(password_bytes).hexdigest()
    
    # Gunakan try-except untuk menangani error detect_wrap_bug
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError as e:
        # Jika error karena detect_wrap_bug, coba patch dan retry
        if "cannot be longer than 72 bytes" in str(e) or "detect_wrap_bug" in str(e):
            try:
                # Patch detect_wrap_bug
                import passlib.handlers.bcrypt as bcrypt_module
                bcrypt_module.detect_wrap_bug = lambda ident: False
                # Retry verify
                return pwd_context.verify(plain_password, hashed_password)
            except:
                # Jika masih error, gunakan bcrypt langsung sebagai fallback
                import bcrypt
                try:
                    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
                except:
                    # Jika hash tidak valid, return False
                    return False
        raise

def get_password_hash(password):
    """
    Hash password dengan bcrypt.
    Bcrypt memiliki batasan maksimal 72 bytes.
    Jika password lebih panjang, hash dulu dengan SHA256 untuk mendapatkan fixed-length (64 chars).
    """
    password_bytes = password.encode('utf-8')
    
    # Jika password lebih dari 72 bytes, hash dengan SHA256 dulu
    # SHA256 menghasilkan 64 karakter hex (32 bytes), jadi aman untuk bcrypt
    if len(password_bytes) > 72:
        password = hashlib.sha256(password_bytes).hexdigest()
    
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Dependency untuk memproteksi endpoint.
    Mengecek token valid atau tidak, lalu mengembalikan data user.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        branch_id: int = payload.get("branch_id")
        
        if username is None:
            raise credentials_exception
            
        return {"username": username, "role": role, "branch_id": branch_id}
        
    except JWTError:
        raise credentials_exception

# ==========================================
# 4. ENDPOINTS: AUTHENTICATION
# ==========================================

# ==========================================
# 10. ENDPOINTS: BACKGROUND SERVICE CONTROL
# ==========================================

@app.get("/background-service/status")
def get_background_service_status(current_user: dict = Depends(get_current_user)):
    """Get status background detection service (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh melihat status service")
    
    with background_service_lock:
        enabled = background_service_enabled
    
    # Hitung jumlah thread yang aktif
    with camera_threads_lock:
        active_threads = sum(1 for t in camera_threads.values() if t.is_alive())
        total_threads = len(camera_threads)
    
    return {
        "enabled": enabled,
        "active_threads": active_threads,
        "total_threads": total_threads,
        "status": "running" if enabled else "stopped"
    }

@app.post("/background-service/enable")
def enable_background_service(current_user: dict = Depends(get_current_user)):
    """Enable background detection service (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh mengaktifkan service")
    
    global background_service_enabled
    with background_service_lock:
        if background_service_enabled:
            return {"status": "already_enabled", "message": "Background service sudah aktif"}
        
        background_service_enabled = True
        print("[Background] Service enabled by admin")
    
    # Restart camera threads jika belum berjalan
    start_background_detection_service()
    
    return {
        "status": "enabled",
        "message": "Background detection service diaktifkan"
    }

@app.post("/background-service/disable")
def disable_background_service(current_user: dict = Depends(get_current_user)):
    """Disable background detection service (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh menonaktifkan service")
    
    global background_service_enabled
    with background_service_lock:
        if not background_service_enabled:
            return {"status": "already_disabled", "message": "Background service sudah nonaktif"}
        
        background_service_enabled = False
        print("[Background] Service disabled by admin")
    
    # Stop semua camera threads
    stop_all_camera_threads()
    
    return {
        "status": "disabled",
        "message": "Background detection service dinonaktifkan"
    }

@app.post("/token", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE username=?", (form_data.username,)).fetchone()
    conn.close()

    # Validasi User & Password
    if not user or not verify_password(form_data.password, user['password_hash']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Buat Token
    access_token = create_access_token(
        data={
            "sub": user['username'], 
            "role": user['role'],
            "branch_id": user['branch_id']
        }
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/users/")
def create_user(user: UserCreate, current_user: dict = Depends(get_current_user)):
    # Proteksi: Hanya admin yang boleh buat user baru
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh menambah user")

    hashed_pw = get_password_hash(user.password)
    
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, branch_id) VALUES (?, ?, ?, ?)",
            (user.username, hashed_pw, user.role, user.branch_id)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Username sudah terdaftar")
    
    conn.close()
    return {"status": "User created successfully"}

@app.get("/seed_admin")
def seed_admin_user():
    """Jalankan URL ini sekali saja untuk membuat user admin pertama kali"""
    conn = get_db_connection()
    exist = conn.execute("SELECT * FROM users WHERE username='admin'").fetchone()
    if not exist:
        pw = get_password_hash("admin123")
        conn.execute("INSERT INTO users (username, password_hash, role) VALUES ('admin', ?, 'admin')", (pw,))
        conn.commit()
        conn.close()
        return {"msg": "User 'admin' created. Password: 'admin123'"}
    conn.close()
    return {"msg": "Admin already exists"}

@app.get("/users/me")
def read_users_me(current_user: dict = Depends(get_current_user)):
    return current_user

@app.get("/users/")
def get_all_users(current_user: dict = Depends(get_current_user)):
    """Get all users (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh melihat daftar user")
    
    conn = get_db_connection()
    users = conn.execute("SELECT id, username, role, branch_id FROM users ORDER BY id").fetchall()
    conn.close()
    
    return [dict(u) for u in users]

@app.delete("/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    """Delete user (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh menghapus user")
    
    # Jangan biarkan user menghapus dirinya sendiri
    if current_user.get('username'):
        conn = get_db_connection()
        user = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        if user and user['username'] == current_user['username']:
            raise HTTPException(status_code=400, detail="Tidak dapat menghapus akun sendiri")
    
    conn = get_db_connection()
    
    # Cek apakah user ada
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    
    # Hapus user
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    
    return {"status": "User deleted successfully"}

# ==========================================
# 4.5. ENDPOINTS: BRANCH MANAGEMENT
# ==========================================

@app.get("/branches/")
def get_branches(current_user: dict = Depends(get_current_user)):
    """Get all branches (master data)"""
    conn = get_db_connection()
    branches = conn.execute("SELECT * FROM branches WHERE is_active=1 ORDER BY name").fetchall()
    conn.close()
    return [dict(b) for b in branches]

@app.post("/branches/")
def create_branch(branch: BranchInput, current_user: dict = Depends(get_current_user)):
    """Create new branch (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh menambah cabang")
    
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO branches (name, address, phone) VALUES (?, ?, ?)",
            (branch.name, branch.address, branch.phone)
        )
        conn.commit()
        branch_id = conn.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="Nama cabang sudah terdaftar")
    finally:
        conn.close()
    
    return {"status": "Branch created successfully", "id": branch_id}

@app.get("/branches/{branch_id}")
def get_branch(branch_id: int, current_user: dict = Depends(get_current_user)):
    """Get branch by ID"""
    conn = get_db_connection()
    branch = conn.execute("SELECT * FROM branches WHERE id=?", (branch_id,)).fetchone()
    conn.close()
    
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    
    return dict(branch)

@app.delete("/branches/{branch_id}")
def delete_branch(branch_id: int, current_user: dict = Depends(get_current_user)):
    """Delete branch (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh menghapus cabang")
    
    conn = get_db_connection()
    
    # Cek apakah cabang ada
    branch = conn.execute("SELECT * FROM branches WHERE id=?", (branch_id,)).fetchone()
    if not branch:
        conn.close()
        raise HTTPException(status_code=404, detail="Branch not found")
    
    # Cek apakah ada kamera yang menggunakan cabang ini
    cameras = conn.execute("SELECT COUNT(*) as count FROM cameras WHERE branch_id=?", (branch_id,)).fetchone()
    if cameras['count'] > 0:
        conn.close()
        raise HTTPException(
            status_code=400, 
            detail=f"Cabang tidak dapat dihapus karena masih digunakan oleh {cameras['count']} kamera"
        )
    
    # Soft delete (set is_active=0) atau hard delete
    conn.execute("UPDATE branches SET is_active=0 WHERE id=?", (branch_id,))
    conn.commit()
    conn.close()
    
    return {"status": "Branch deleted successfully"}

# ==========================================
# 5. ENDPOINTS: CAMERA MANAGEMENT
# ==========================================

@app.post("/cameras/")
def add_camera(cam: CameraInput, current_user: dict = Depends(get_current_user)):
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Forbidden")
    
    conn = get_db_connection()
    
    # Ambil nama cabang dari tabel branches
    branch = conn.execute("SELECT name FROM branches WHERE id=?", (cam.branch_id,)).fetchone()
    if not branch:
        conn.close()
        raise HTTPException(status_code=404, detail="Branch not found")
    
    branch_name = branch['name']
    
    # Insert kamera dengan branch_id dan branch_name (untuk backward compatibility)
    conn.execute("INSERT INTO cameras (branch_id, branch_name, rtsp_url) VALUES (?, ?, ?)", 
                 (cam.branch_id, branch_name, cam.rtsp_url))
    conn.commit()
    conn.close()
    return {"status": "Camera added"}

@app.get("/cameras/")
def get_cameras(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    
    # SAAS LOGIC:
    # Jika Admin -> Lihat semua kamera
    # Jika Staff -> Hanya lihat kamera sesuai branch_id user
    
    if current_user['role'] == 'admin':
        cams = conn.execute("SELECT * FROM cameras").fetchall()
    else:
        # Staff Logic
        branch_id = current_user['branch_id']
        # Asumsi: tabel cameras belum punya kolom branch_id yg eksplisit di versi simple ini,
        # tapi kita mapping berdasarkan ID kamera dulu atau logic sederhana.
        # Untuk V6.0 ini, kita anggap branch_id di user merujuk ke ID kamera (Satu cabang = 1 kamera dulu)
        # Atau idealnya tabel cameras punya kolom 'branch_group_id'.
        
        # Sesuai database.py sebelumnya, tabel users: FOREIGN KEY(branch_id) REFERENCES cameras(id)
        # Jadi staff hanya boleh lihat kamera yang ID-nya = user.branch_id
        cams = conn.execute("SELECT * FROM cameras WHERE id=?", (branch_id,)).fetchall()

    conn.close()
    return [dict(c) for c in cams]

@app.delete("/cameras/{camera_id}")
def delete_camera(camera_id: int, current_user: dict = Depends(get_current_user)):
    """Hapus kamera berdasarkan ID"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh menghapus kamera")
    
    conn = get_db_connection()
    
    # Cek apakah kamera ada
    cam = conn.execute("SELECT * FROM cameras WHERE id=?", (camera_id,)).fetchone()
    if not cam:
        conn.close()
        raise HTTPException(status_code=404, detail="Camera not found")
    
    # Hapus zona yang terkait dengan kamera ini
    conn.execute("DELETE FROM zones WHERE camera_id=?", (camera_id,))
    
    # Hapus kamera
    conn.execute("DELETE FROM cameras WHERE id=?", (camera_id,))
    conn.commit()
    conn.close()
    
    return {"status": "Camera deleted successfully"}

@app.delete("/cameras/cleanup/no-zones")
def delete_cameras_without_zones(current_user: dict = Depends(get_current_user)):
    """Hapus semua kamera yang belum memiliki zona"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh menghapus kamera")
    
    conn = get_db_connection()
    
    # Cari kamera yang tidak memiliki zona
    cameras_without_zones = conn.execute('''
        SELECT c.id 
        FROM cameras c
        LEFT JOIN zones z ON c.id = z.camera_id
        WHERE z.id IS NULL
    ''').fetchall()
    
    deleted_count = 0
    deleted_ids = []
    
    for cam in cameras_without_zones:
        cam_id = cam['id']
        # Hapus kamera
        conn.execute("DELETE FROM cameras WHERE id=?", (cam_id,))
        deleted_ids.append(cam_id)
        deleted_count += 1
    
    conn.commit()
    conn.close()
    
    return {
        "status": "Cleanup completed",
        "deleted_count": deleted_count,
        "deleted_camera_ids": deleted_ids
    }

# ==========================================
# 6. ENDPOINTS: ZONE & SNAPSHOT
# ==========================================

@app.get("/snapshot/{cam_id}")
def get_camera_snapshot(cam_id: int):
    # Endpoint ini Public (atau bisa diprotect Depends(get_current_user))
    # Digunakan oleh Frontend Canvas untuk menggambar zona
    
    conn = get_db_connection()
    cam = conn.execute("SELECT rtsp_url FROM cameras WHERE id=?", (cam_id,)).fetchone()
    conn.close()
    
    if not cam: raise HTTPException(404, "Camera not found")
    
    url = cam['rtsp_url']
    # Fix Webcam Laptop (String vs Int)
    if str(url).isdigit(): 
        url = int(url)
        # Coba DirectShow dulu untuk webcam Windows
        cap = cv2.VideoCapture(url, cv2.CAP_DSHOW)
        if not cap.isOpened():
            # Fallback ke default backend jika DirectShow gagal
            cap = cv2.VideoCapture(url)
    else:
        cap = cv2.VideoCapture(url)
    
    if not cap.isOpened():
        raise HTTPException(500, "Cannot connect to camera")
    
    # Buang buffer
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    for _ in range(3): cap.grab()
        
    ret, frame = cap.read()
    cap.release()
    
    if not ret: raise HTTPException(500, "Empty frame")
    
    # Encode ke JPEG
    success, img_encoded = cv2.imencode(".jpg", frame)
    return Response(content=img_encoded.tobytes(), media_type="image/jpeg")

@app.get("/stream/{cam_id}")
def stream_camera(cam_id: int):
    """
    MJPEG Streaming endpoint untuk Live Monitor.
    Menggunakan frame dari cache yang sudah dibaca oleh background service.
    TIDAK membuka kamera sendiri untuk menghindari konflik dengan background service.
    """
    conn = get_db_connection()
    cam = conn.execute("SELECT rtsp_url FROM cameras WHERE id=?", (cam_id,)).fetchone()
    conn.close()
    
    if not cam:
        raise HTTPException(404, "Camera not found")
    
    def generate_frames():
        last_timestamp = 0
        consecutive_errors = 0
        max_consecutive_errors = 30  # 30 frame tanpa update = 1 detik
        
        while True:
            try:
                # Ambil frame dari cache (yang sudah dibaca oleh background service)
                frame = None
                frame_timestamp = 0
                
                with frame_cache_lock:
                    if cam_id in frame_cache:
                        cached_data = frame_cache[cam_id]
                        frame_timestamp = cached_data["timestamp"]
                        frame_age = time.time() - frame_timestamp
                        
                        # Hanya gunakan frame yang masih fresh (kurang dari 2 detik untuk lebih responsif)
                        if frame_age < 2.0:
                            frame = cached_data["frame"].copy()
                
                if frame is None:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        # Kirim error frame jika tidak ada frame dari cache
                        error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(error_frame, "Waiting for camera...", (50, 220), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
                        cv2.putText(error_frame, "Background service starting", (50, 260), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                        success, img_encoded = cv2.imencode(".jpg", error_frame)
                        if success:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + 
                                   img_encoded.tobytes() + b'\r\n')
                    # Tunggu sebentar sebelum cek lagi (lebih cepat untuk responsif)
                    # Gunakan delay yang sama dengan frame rate untuk konsistensi
                    time.sleep(0.05)
                    continue
                
                # Reset error count jika dapat frame
                consecutive_errors = 0
                
                # Encode dan kirim frame (kirim setiap frame yang ada di cache untuk smooth streaming)
                # Tidak perlu cek timestamp karena cache sudah di-update dengan frame terbaru
                # Optimasi encoding: kurangi kualitas lebih agresif untuk encoding lebih cepat
                # Kualitas 50 sudah cukup untuk streaming dan jauh lebih cepat dari 65
                success, img_encoded = cv2.imencode(".jpg", frame, [
                    cv2.IMWRITE_JPEG_QUALITY, 50,
                    cv2.IMWRITE_JPEG_OPTIMIZE, 1  # Optimasi ukuran file
                ])
                if success:
                    # Format MJPEG: multipart boundary
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + 
                           img_encoded.tobytes() + b'\r\n')
                
                # Delay untuk frame rate (sekitar 20 FPS untuk stabilitas encoding)
                # Frame rate lebih rendah untuk memastikan encoding selesai sebelum frame berikutnya
                # 20 FPS sudah cukup smooth dan lebih stabil dari 30 FPS
                time.sleep(0.05)
                
            except Exception as e:
                print(f"[Stream {cam_id}] Error: {e}")
                # Kirim error frame
                try:
                    error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(error_frame, f"Stream Error: {str(e)[:30]}", (20, 220), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    success, img_encoded = cv2.imencode(".jpg", error_frame)
                    if success:
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + 
                               img_encoded.tobytes() + b'\r\n')
                except:
                    pass
                time.sleep(1)
    
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.post("/zones/")
def create_zone(zone: ZoneInput, current_user: dict = Depends(get_current_user)):
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admin can set zones")

    conn = get_db_connection()
    # Simpan koordinat sebagai string JSON
    coords_str = json.dumps(zone.coords)
    
    conn.execute("INSERT INTO zones (camera_id, name, type, coords) VALUES (?, ?, ?, ?)",
                 (zone.camera_id, zone.name, zone.type, coords_str))
    conn.commit()
    conn.close()
    return {"status": "Zone created"}

@app.get("/zones/{cam_id}")
def get_zones(cam_id: int):
    conn = get_db_connection()
    zones = conn.execute("SELECT * FROM zones WHERE camera_id=?", (cam_id,)).fetchall()
    conn.close()
    
    # Parse JSON coords balik ke List biar Frontend enak bacanya
    result = []
    for z in zones:
        z_dict = dict(z)
        z_dict['coords'] = json.loads(z['coords'])
        result.append(z_dict)
        
    return result

@app.delete("/zones/{zone_id}")
def delete_zone(zone_id: int, current_user: dict = Depends(get_current_user)):
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Only admin can delete zones")
    
    conn = get_db_connection()
    
    # Cek apakah zona ada
    zone = conn.execute("SELECT * FROM zones WHERE id=?", (zone_id,)).fetchone()
    if not zone:
        conn.close()
        raise HTTPException(status_code=404, detail="Zone not found")
    
    # Hapus zona
    conn.execute("DELETE FROM zones WHERE id=?", (zone_id,))
    conn.commit()
    conn.close()
    
    return {"status": "Zone deleted"}
    
@app.get("/frame-cache/{cam_id}")
def get_frame_from_cache(cam_id: int):
    """
    Endpoint untuk scheduler mengambil frame terakhir dari cache streaming.
    Frame ini di-update oleh streaming endpoint secara kontinyu.
    """
    with frame_cache_lock:
        if cam_id in frame_cache:
            cached_data = frame_cache[cam_id]
            # Cek apakah frame masih fresh (kurang dari 5 detik)
            if time.time() - cached_data["timestamp"] < 5.0:
                return Response(
                    content=cv2.imencode(".jpg", cached_data["frame"])[1].tobytes(),
                    media_type="image/jpeg"
                )
    
    # Jika tidak ada di cache atau sudah expired, return 404
    raise HTTPException(status_code=404, detail="Frame not available in cache. Start streaming first.")

def _get_detections_internal(cam_id: int):
    """
    Internal function untuk mendapatkan deteksi objek dari frame cache.
    Digunakan oleh endpoint HTTP dan WebSocket.
    Returns None jika frame tidak tersedia atau expired.
    """
    # Ambil frame dari cache
    with frame_cache_lock:
        if cam_id not in frame_cache:
            return None
        
        cached_data = frame_cache[cam_id]
        frame_age = time.time() - cached_data["timestamp"]
        if frame_age > 5.0:
            return None
        
        # Ambil frame terbaru (copy untuk thread safety)
        frame = cached_data["frame"].copy()
        frame_timestamp = cached_data["timestamp"]
    
    # Ambil zona untuk kamera ini
    conn = get_db_connection()
    zones = conn.execute("SELECT * FROM zones WHERE camera_id=?", (cam_id,)).fetchall()
    conn.close()
    
    # Konversi zones ke format yang dibutuhkan AI
    zones_list = []
    for z in zones:
        zones_list.append({
            "name": z["name"],
            "type": z["type"],
            "coords": z["coords"]  # String JSON
        })
    
    # Gunakan shared AI engine
    engine = get_ai_engine()
    
    # Jalankan deteksi objek
    h, w = frame.shape[:2]
    
    # Deteksi objek dengan YOLO - tingkatkan confidence threshold untuk mengurangi false positive
    # conf=0.6 berarti hanya deteksi dengan confidence >= 60% (lebih akurat, mengurangi false positive)
    results_obj = engine.model_object(frame, verbose=False, conf=0.6)[0]
    
    detections = []
    for box in results_obj.boxes:
        cls_id = int(box.cls[0])
        conf = float(box.conf[0])
        
        # Filter: hanya ambil deteksi dengan confidence >= 60% dan objek yang ada di CLASS_MAP
        # Ini mengurangi false positive (deteksi barang yang tidak ada)
        if cls_id in engine.CLASS_MAP and conf >= 0.6:
            xyxy = box.xyxy[0].cpu().numpy()
            x1, y1, x2, y2 = xyxy
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            
            # Konversi ke persentase untuk konsistensi dengan zona
            detection = {
                "name": engine.CLASS_MAP[cls_id],
                "confidence": round(conf, 2),
                "bbox": {
                    "x1": float(x1),
                    "y1": float(y1),
                    "x2": float(x2),
                    "y2": float(y2),
                    "x1_pct": float(x1 / w),
                    "y1_pct": float(y1 / h),
                    "x2_pct": float(x2 / w),
                    "y2_pct": float(y2 / h),
                },
                "centroid": {
                    "x": float(cx),
                    "y": float(cy),
                    "x_pct": float(cx / w),
                    "y_pct": float(cy / h),
                },
                "zone": None  # Akan diisi jika objek ada di zona
            }
            
            # Mapping objek ke zona
            for zone in zones_list:
                try:
                    zone_coords = json.loads(zone['coords'])
                    if engine._is_point_in_zone(
                        (cx, cy),
                        zone_coords,
                        w,
                        h
                    ):
                        detection['zone'] = zone['name']
                        break
                except:
                    continue
            
            detections.append(detection)
    
    result = {
        "camera_id": cam_id,
        "timestamp": time.time(),
        "frame_timestamp": frame_timestamp,
        "detections": detections,
        "frame_size": {"width": int(w), "height": int(h)},
        "detection_count": len(detections)
    }
    
    # Update detection cache
    with detection_cache_lock:
        detection_cache[cam_id] = result
    
    return result

@app.get("/detections/{cam_id}")
def get_detections(cam_id: int):
    """
    Endpoint untuk mendapatkan deteksi objek real-time dari frame cache.
    Mengembalikan koordinat dan informasi objek yang terdeteksi.
    """
    result = _get_detections_internal(cam_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Frame not available in cache. Start streaming first.")
    return result

@app.websocket("/ws/detections/{cam_id}")
async def websocket_detections(websocket: WebSocket, cam_id: int):
    """
    WebSocket endpoint untuk deteksi real-time.
    Client akan menerima update deteksi setiap 1-2 detik secara real-time.
    """
    await websocket.accept()
    
    # Tambahkan koneksi ke manager
    with websocket_lock:
        websocket_connections[cam_id].add(websocket)
    
    print(f"[WebSocket] Client connected for camera {cam_id}")
    
    try:
        # Kirim deteksi terakhir dari cache jika ada
        with detection_cache_lock:
            if cam_id in detection_cache:
                await websocket.send_json(detection_cache[cam_id])
        
        # Keep connection alive dan kirim update
        while True:
            # Kirim deteksi terbaru dari cache atau lakukan deteksi baru
            result = None
            with detection_cache_lock:
                if cam_id in detection_cache:
                    # Cek apakah cache masih fresh (kurang dari 2 detik)
                    cache_age = time.time() - detection_cache[cam_id].get("timestamp", 0)
                    if cache_age < 2.0:
                        result = detection_cache[cam_id]
            
            # Jika cache tidak fresh, lakukan deteksi baru
            if result is None:
                result = _get_detections_internal(cam_id)
            
            if result:
                try:
                    await websocket.send_json(result)
                except:
                    break
            
            # Tunggu ping dari client atau timeout
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1.5)
            except asyncio.TimeoutError:
                pass
            except:
                break
            
    except WebSocketDisconnect:
        print(f"[WebSocket] Client disconnected for camera {cam_id}")
    except Exception as e:
        print(f"[WebSocket] Error for camera {cam_id}: {e}")
    finally:
        # Hapus koneksi dari manager
        with websocket_lock:
            websocket_connections[cam_id].discard(websocket)
            if len(websocket_connections[cam_id]) == 0:
                del websocket_connections[cam_id]

@app.websocket("/ws/data/{cam_id}")
async def websocket_data(websocket: WebSocket, cam_id: int):
    """
    WebSocket endpoint untuk zone states, billing, dan alerts real-time.
    Client akan menerima update setiap 1-2 detik secara real-time.
    """
    await websocket.accept()
    
    print(f"[WebSocket] Client connected for data (zone states, billing, alerts) camera {cam_id}")
    
    try:
        # Initialize cache dengan data default jika belum ada
        with data_cache_lock:
            if cam_id not in zone_states_cache:
                # Ambil zones dari database dan buat default states
                conn = get_db_connection()
                zones = conn.execute("SELECT name, type FROM zones WHERE camera_id=?", (cam_id,)).fetchall()
                conn.close()
                
                default_zone_states = {}
                for z in zones:
                    default_zone_states[z['name']] = {
                        "status": "UNKNOWN",
                        "timer": 0,
                        "zone_type": z['type']
                    }
                
                zone_states_cache[cam_id] = {
                    "camera_id": cam_id,
                    "zone_states": default_zone_states,
                    "timestamp": time.time()
                }
        
        # Kirim data terakhir dari cache jika ada
        with data_cache_lock:
            # Pastikan selalu kirim zone_states yang ada, tidak peduli fresh atau tidak
            zone_states_data = {}
            if cam_id in zone_states_cache:
                cache_data = zone_states_cache[cam_id]
                zone_states_data = cache_data.get("zone_states", {})
            
            data = {
                "type": "data_update",
                "camera_id": cam_id,
                "zone_states": zone_states_data,
                "billing": billing_cache.get(cam_id, []),
                "alerts": alerts_cache.get(cam_id, []),
                "timestamp": time.time()
            }
            await websocket.send_json(data)
        
        # Keep connection alive dan kirim update
        while True:
            # Ambil data terbaru dari cache
            with data_cache_lock:
                # Ambil zone_states dari cache (selalu kirim data terakhir yang ada)
                # Ini mencegah status zona hilang-hilangan - tidak pernah kirim empty object
                zone_states_data = {}
                if cam_id in zone_states_cache:
                    cache_data = zone_states_cache[cam_id]
                    # Selalu ambil data terakhir yang ada, tidak peduli umur cache
                    # Ini memastikan status zona tidak pernah hilang
                    zone_states_data = cache_data.get("zone_states", {})
                
                data = {
                    "type": "data_update",
                    "camera_id": cam_id,
                    "zone_states": zone_states_data,
                    "billing": billing_cache.get(cam_id, []),
                    "alerts": alerts_cache.get(cam_id, []),
                    "timestamp": time.time()
                }
            
            try:
                await websocket.send_json(data)
            except:
                break
            
            # Tunggu ping dari client atau timeout
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1.5)
            except asyncio.TimeoutError:
                pass
            except:
                break
            
    except WebSocketDisconnect:
        print(f"[WebSocket] Client disconnected for data camera {cam_id}")
    except Exception as e:
        print(f"[WebSocket] Error for data camera {cam_id}: {e}")
    finally:
        pass

def _camera_frame_reader_thread(cam_id: int, rtsp_url: str):
    """
    Background thread untuk membaca frame dari kamera secara kontinyu.
    Frame akan disimpan ke cache untuk digunakan oleh deteksi AI.
    """
    print(f"[Background] Starting frame reader for camera {cam_id}")
    cap = None
    retry_count = 0
    max_retries = 3
    
    # Fix Webcam URL (String vs Int)
    url = rtsp_url
    if url.isdigit():
        url = int(url)
    
    while camera_threads_running.get(cam_id, True):
        try:
            # Coba buka kamera
            if isinstance(url, int):
                cap = cv2.VideoCapture(url, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(url)
            else:
                cap = cv2.VideoCapture(url)
            
            if not cap.isOpened():
                retry_count += 1
                if retry_count < max_retries:
                    print(f"[Background] Camera {cam_id} failed to open, retrying... ({retry_count}/{max_retries})")
                    time.sleep(2)
                    continue
                else:
                    print(f"[Background] Camera {cam_id} failed to open after {max_retries} retries")
                    # Simpan error frame ke cache
                    error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(error_frame, f"Camera {cam_id} Error", (20, 220), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                    with frame_cache_lock:
                        frame_cache[cam_id] = {
                            "frame": error_frame,
                            "timestamp": time.time()
                        }
                    time.sleep(5)  # Tunggu sebelum retry lagi
                    retry_count = 0
                    continue
            
            retry_count = 0
            consecutive_errors = 0
            max_consecutive_errors = 10
            
            # Optimasi kamera untuk low latency
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffer untuk mengurangi delay
            cap.set(cv2.CAP_PROP_FPS, 20)  # Set FPS target ke 20 untuk stabilitas
            # Buang beberapa frame pertama untuk clear buffer lama
            for _ in range(5):
                cap.grab()
            
            print(f"[Background] Camera {cam_id} connected, reading frames...")
            
            while camera_threads_running.get(cam_id, True):
                ret, frame = cap.read()
                
                if not ret:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"[Background] Camera {cam_id} disconnected, attempting reconnect...")
                        break
                    # Tunggu sebentar sebelum retry (lebih cepat untuk smooth streaming)
                    time.sleep(0.05)
                    continue
                
                consecutive_errors = 0
                
                # Resize frame untuk mempercepat encoding dan mengurangi bandwidth
                # Resize ke maksimal 960x540 untuk encoding lebih cepat dan bandwidth lebih efisien
                # Resolusi ini masih cukup untuk monitoring dan jauh lebih cepat dari 1280x720
                h, w = frame.shape[:2]
                if w > 960 or h > 540:
                    scale = min(960.0 / w, 540.0 / h)
                    new_w = int(w * scale)
                    new_h = int(h * scale)
                    # Gunakan INTER_AREA untuk resize down (lebih cepat dan lebih baik untuk downsampling)
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                
                # Update frame cache (dengan timestamp yang lebih presisi)
                current_time = time.time()
                with frame_cache_lock:
                    frame_cache[cam_id] = {
                        "frame": frame.copy(),
                        "timestamp": current_time
                    }
                
                # Frame rate control (sekitar 20 FPS untuk stabilitas)
                # Frame rate lebih rendah untuk memastikan encoding selesai sebelum frame berikutnya
                # 20 FPS sudah cukup smooth dan lebih stabil dari 30 FPS
                time.sleep(0.05)
            
            # Release dan reconnect
            if cap:
                cap.release()
                cap = None
            time.sleep(1)
            
        except Exception as e:
            print(f"[Background] Camera {cam_id} error: {e}")
            if cap:
                cap.release()
                cap = None
            time.sleep(2)
    
    print(f"[Background] Frame reader for camera {cam_id} stopped")
    if cap:
        cap.release()

def _detection_worker_thread():
    """
    Background worker thread yang menjalankan deteksi AI secara periodik
    untuk semua kamera aktif yang memiliki frame di cache.
    """
    print("[Background] Starting detection worker thread...")
    detection_interval = 1.5  # Deteksi setiap 1.5 detik untuk real-time (sebelumnya 5 detik)
    
    while True:
        try:
            # Check jika service disabled
            with background_service_lock:
                if not background_service_enabled:
                    time.sleep(1)  # Sleep pendek jika disabled
                    continue
            
            # Ambil semua kamera aktif dari database
            conn = get_db_connection()
            cameras = conn.execute(
                "SELECT id FROM cameras WHERE is_active = 1"
            ).fetchall()
            conn.close()
            
            # Jalankan deteksi untuk setiap kamera yang memiliki frame di cache
            with frame_cache_lock:
                available_cameras = list(frame_cache.keys())
            
            for cam_row in cameras:
                cam_id = cam_row['id']
                
                # Skip jika frame tidak tersedia
                if cam_id not in available_cameras:
                    continue
                
                # Cek apakah frame masih fresh (kurang dari 10 detik)
                with frame_cache_lock:
                    if cam_id not in frame_cache:
                        continue
                    cached_data = frame_cache[cam_id]
                    frame_age = time.time() - cached_data["timestamp"]
                    if frame_age > 10.0:
                        continue
                
                # Double check service masih enabled sebelum deteksi
                with background_service_lock:
                    if not background_service_enabled:
                        break
                
                # Jalankan deteksi (non-blocking, catch error agar tidak crash thread)
                try:
                    result = _analyze_camera_internal(cam_id)
                    if result.get("status") == "error":
                        print(f"[Background] Detection error for camera {cam_id}: {result.get('error')}")
                except Exception as e:
                    print(f"[Background] Exception during detection for camera {cam_id}: {e}")
            
            # Sleep sebelum deteksi berikutnya
            time.sleep(detection_interval)
            
        except Exception as e:
            print(f"[Background] Detection worker error: {e}")
            time.sleep(detection_interval)

def _realtime_detection_worker_thread():
    """
    Background thread untuk deteksi real-time yang update detection cache.
    Berjalan lebih cepat (1-2 detik) dibanding background detection worker (5 detik).
    Hanya berjalan untuk kamera yang memiliki WebSocket connections aktif.
    WebSocket endpoint akan membaca dari cache ini dan mengirim ke client.
    """
    print("[Realtime] Starting real-time detection worker thread...")
    detection_interval = 1.5  # Deteksi setiap 1.5 detik untuk real-time
    
    while True:
        try:
            # Check jika service disabled
            with background_service_lock:
                if not background_service_enabled:
                    time.sleep(1)
                    continue
            
            # Ambil semua kamera yang memiliki WebSocket connections
            with websocket_lock:
                active_cameras = list(websocket_connections.keys())
            
            if not active_cameras:
                time.sleep(2)  # Jika tidak ada koneksi, sleep lebih lama
                continue
            
            # Jalankan deteksi untuk setiap kamera yang memiliki WebSocket connection
            for cam_id in active_cameras:
                # Cek apakah frame tersedia
                with frame_cache_lock:
                    if cam_id not in frame_cache:
                        continue
                    cached_data = frame_cache[cam_id]
                    frame_age = time.time() - cached_data["timestamp"]
                    if frame_age > 5.0:
                        continue
                
                # Jalankan deteksi dan update cache
                # WebSocket endpoint akan membaca dari cache ini
                try:
                    result = _get_detections_internal(cam_id)
                    # _get_detections_internal sudah update detection_cache
                except Exception as e:
                    print(f"[Realtime] Exception during detection for camera {cam_id}: {e}")
            
            time.sleep(detection_interval)
            
        except Exception as e:
            print(f"[Realtime] Detection worker error: {e}")
            time.sleep(detection_interval)

def start_background_detection_service():
    """
    Start background service untuk deteksi otomatis.
    - Membaca frame dari semua kamera aktif secara kontinyu
    - Menjalankan deteksi AI secara periodik
    """
    try:
        print("[Background] Starting background detection service...")
        
        # Start detection worker thread
        try:
            detection_thread = threading.Thread(target=_detection_worker_thread, daemon=True)
            detection_thread.start()
            print("[Background] Detection worker thread started")
        except Exception as e:
            print(f"[Background] Error starting detection worker thread: {e}")
            import traceback
            traceback.print_exc()
        
        # Start real-time detection worker thread untuk WebSocket
        try:
            realtime_thread = threading.Thread(target=_realtime_detection_worker_thread, daemon=True)
            realtime_thread.start()
            print("[Background] Real-time detection worker thread started")
        except Exception as e:
            print(f"[Background] Error starting real-time detection worker thread: {e}")
            import traceback
            traceback.print_exc()
        
        # Start frame reader threads untuk semua kamera aktif
        def start_camera_threads():
            try:
                conn = get_db_connection()
                cameras = conn.execute(
                    "SELECT id, rtsp_url FROM cameras WHERE is_active = 1"
                ).fetchall()
                conn.close()
                
                print(f"[Background] Found {len(cameras)} active cameras")
                
                for cam in cameras:
                    try:
                        cam_id = cam['id']
                        rtsp_url = cam['rtsp_url']
                        
                        # Skip jika thread sudah berjalan
                        with camera_threads_lock:
                            if cam_id in camera_threads and camera_threads[cam_id].is_alive():
                                print(f"[Background] Camera {cam_id} thread already running, skipping")
                                continue
                            
                            # Set flag running
                            camera_threads_running[cam_id] = True
                            
                            # Start thread
                            thread = threading.Thread(
                                target=_camera_frame_reader_thread,
                                args=(cam_id, rtsp_url),
                                daemon=True
                            )
                            thread.start()
                            camera_threads[cam_id] = thread
                            print(f"[Background] Started frame reader thread for camera {cam_id}")
                    except Exception as e:
                        print(f"[Background] Error starting thread for camera {cam_id}: {e}")
                        import traceback
                        traceback.print_exc()
            except Exception as e:
                print(f"[Background] Error in start_camera_threads: {e}")
                import traceback
                traceback.print_exc()
        
        # Start camera threads
        start_camera_threads()
        
        # Start monitor thread untuk mengecek kamera baru yang ditambahkan
        def monitor_new_cameras():
            while True:
                time.sleep(30)  # Cek setiap 30 detik
                try:
                    conn = get_db_connection()
                    cameras = conn.execute(
                        "SELECT id, rtsp_url FROM cameras WHERE is_active = 1"
                    ).fetchall()
                    conn.close()
                    
                    for cam in cameras:
                        cam_id = cam['id']
                        with camera_threads_lock:
                            # Start thread jika belum ada atau sudah mati
                            if cam_id not in camera_threads or not camera_threads[cam_id].is_alive():
                                if cam_id not in camera_threads_running or not camera_threads_running.get(cam_id, False):
                                    camera_threads_running[cam_id] = True
                                    rtsp_url = cam['rtsp_url']
                                    thread = threading.Thread(
                                        target=_camera_frame_reader_thread,
                                        args=(cam_id, rtsp_url),
                                        daemon=True
                                    )
                                    thread.start()
                                    camera_threads[cam_id] = thread
                                    print(f"[Background] Started frame reader thread for new camera {cam_id}")
                except Exception as e:
                    print(f"[Background] Monitor error: {e}")
        
        try:
            monitor_thread = threading.Thread(target=monitor_new_cameras, daemon=True)
            monitor_thread.start()
            print("[Background] Camera monitor thread started")
        except Exception as e:
            print(f"[Background] Error starting monitor thread: {e}")
            import traceback
            traceback.print_exc()
        
        print("[Background] ✅ Background detection service started successfully!")
    except Exception as e:
        print(f"[Background] ❌ Fatal error starting background service: {e}")
        import traceback
        traceback.print_exc()

def stop_all_camera_threads():
    """Stop semua background camera threads"""
    print("[Background] Stopping all camera threads...")
    with camera_threads_lock:
        for cam_id in list(camera_threads_running.keys()):
            camera_threads_running[cam_id] = False
    print("[Background] All camera threads stopped")

def _analyze_camera_internal(cam_id: int):
    """
    Internal function untuk analyze camera tanpa auth check.
    Digunakan oleh analyze_all dan bisa dipanggil dari background task.
    """
    # Ambil frame dari cache
    with frame_cache_lock:
        if cam_id not in frame_cache:
            return {"status": "error", "error": "Frame not available in cache"}
        
        cached_data = frame_cache[cam_id]
        frame_age = time.time() - cached_data["timestamp"]
        if frame_age > 5.0:
            return {"status": "error", "error": f"Frame expired (age: {frame_age:.1f}s)"}
        
        frame = cached_data["frame"].copy()
    
    # Ambil zona untuk kamera ini
    conn = get_db_connection()
    zones = conn.execute("SELECT * FROM zones WHERE camera_id=?", (cam_id,)).fetchall()
    
    if not zones:
        conn.close()
        return {"status": "skipped", "message": "No zones configured"}
    
    # Format zona untuk AI
    zones_config = []
    for z in zones:
        zones_config.append({
            "name": z["name"],
            "type": z["type"],
            "coords": z["coords"]
        })
    
    # Ambil state sebelumnya
    with state_lock:
        current_states = global_zone_states.copy()
    
    # Get AI Engine
    engine = get_ai_engine()
    
    # === RUN FULL ANALYSIS ===
    result = engine.analyze_frame(frame, zones_config, current_states)
    
    if not result:
        conn.close()
        return {"status": "error", "error": "Analysis failed"}
    
    # Update global state dan tracking durasi
    previous_states_copy = {}
    with state_lock:
        previous_states_copy = global_zone_states.copy()
        global_zone_states.update(result["zone_states"])
    
    # Tracking durasi meja terisi dan antrian penuh
    current_time = datetime.now()
    
    with tracking_lock:
        # Track meja terisi
        for zone_name, new_state in result["zone_states"].items():
            # Cek apakah ini zone table
            zone_info = next((z for z in zones_config if z['name'] == zone_name), None)
            if not zone_info or zone_info.get('type') != 'table':
                continue
            
            prev_state = previous_states_copy.get(zone_name, {})
            prev_status = prev_state.get('status', 'UNKNOWN') if isinstance(prev_state, dict) else 'UNKNOWN'
            new_status = new_state.get('status', 'UNKNOWN') if isinstance(new_state, dict) else 'UNKNOWN'
            
            # Meja baru terisi (status berubah ke TERISI)
            if new_status == 'TERISI' and prev_status != 'TERISI':
                table_occupancy_tracking[zone_name] = {
                    "start_time": current_time,
                    "camera_id": cam_id,
                    "person_count": new_state.get('person_count', 1) if isinstance(new_state, dict) else 1
                }
            
            # Meja baru kosong (status berubah dari TERISI ke BERSIH/KOTOR)
            elif prev_status == 'TERISI' and new_status != 'TERISI':
                if zone_name in table_occupancy_tracking:
                    tracking_data = table_occupancy_tracking[zone_name]
                    start_time = tracking_data["start_time"]
                    duration = (current_time - start_time).total_seconds()
                    
                    # Simpan ke database (conn masih terbuka dari awal function)
                    try:
                        conn.execute('''
                            INSERT INTO table_occupancy_log 
                            (camera_id, zone_name, start_time, end_time, duration_seconds, person_count, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'completed')
                        ''', (cam_id, zone_name, start_time, current_time, int(duration), tracking_data["person_count"]))
                    except Exception as e:
                        print(f"[Tracking] Error saving table occupancy log: {e}")
                    
                    del table_occupancy_tracking[zone_name]
            
            # Update person_count jika masih terisi
            elif new_status == 'TERISI' and zone_name in table_occupancy_tracking:
                table_occupancy_tracking[zone_name]["person_count"] = new_state.get('person_count', 1) if isinstance(new_state, dict) else 1
        
        # Track antrian penuh
        for zone_name, new_state in result["zone_states"].items():
            # Cek apakah ini zone kasir/queue
            zone_info = next((z for z in zones_config if z['name'] == zone_name), None)
            if not zone_info or zone_info.get('type') not in ['kasir', 'queue']:
                continue
            
            # Get queue count
            queue_count = 0
            if isinstance(new_state, dict):
                queue_count = new_state.get('person_count', 0)
            elif isinstance(new_state, (int, float)):
                queue_count = int(new_state)
            
            prev_state = previous_states_copy.get(zone_name, {})
            prev_count = 0
            if isinstance(prev_state, dict):
                prev_count = prev_state.get('person_count', 0)
            elif isinstance(prev_state, (int, float)):
                prev_count = int(prev_state)
            
            QUEUE_LIMIT = 4
            
            # Antrian baru penuh (count > 4 dan sebelumnya <= 4)
            if queue_count > QUEUE_LIMIT and prev_count <= QUEUE_LIMIT:
                queue_tracking[zone_name] = {
                    "start_time": current_time,
                    "camera_id": cam_id,
                    "queue_count": queue_count
                }
            
            # Antrian tidak penuh lagi (count <= 4 dan sebelumnya > 4)
            elif queue_count <= QUEUE_LIMIT and prev_count > QUEUE_LIMIT:
                if zone_name in queue_tracking:
                    tracking_data = queue_tracking[zone_name]
                    start_time = tracking_data["start_time"]
                    duration = (current_time - start_time).total_seconds()
                    
                    # Simpan ke database (conn masih terbuka dari awal function)
                    try:
                        conn.execute('''
                            INSERT INTO queue_log 
                            (camera_id, zone_name, start_time, end_time, duration_seconds, max_queue_count, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'completed')
                        ''', (cam_id, zone_name, start_time, current_time, int(duration), tracking_data["queue_count"]))
                    except Exception as e:
                        print(f"[Tracking] Error saving queue log: {e}")
                    
                    del queue_tracking[zone_name]
            
            # Update queue_count jika masih penuh
            elif queue_count > QUEUE_LIMIT and zone_name in queue_tracking:
                queue_tracking[zone_name]["queue_count"] = max(queue_tracking[zone_name]["queue_count"], queue_count)
    
    # Simpan data ke database
    try:
        # A. Simpan Billing
        for bill in result["billing_events"]:
            exist = conn.execute('''
                SELECT id, qty FROM billing_log 
                WHERE camera_id=? AND zone_name=? AND item_name=? 
                AND timestamp > datetime('now', '-2 minutes')
            ''', (cam_id, bill['zone_name'], bill['item_name'])).fetchone()
            
            if exist:
                new_qty = exist['qty'] + bill['qty']
                conn.execute("UPDATE billing_log SET qty=?, timestamp=datetime('now') WHERE id=?", 
                           (new_qty, exist['id']))
            else:
                conn.execute("INSERT INTO billing_log (camera_id, zone_name, item_name, qty) VALUES (?,?,?,?)",
                           (cam_id, bill['zone_name'], bill['item_name'], bill['qty']))
        
        # B. Simpan Security Alerts
        for alert in result["security_alerts"]:
            last_alert = conn.execute('''
                SELECT id FROM events_log 
                WHERE camera_id=? AND type=? AND timestamp > datetime('now', '-1 minutes')
            ''', (cam_id, alert['type'])).fetchone()
            
            if not last_alert:
                conn.execute("INSERT INTO events_log (camera_id, type, message) VALUES (?,?,?)",
                           (cam_id, alert['type'], alert['msg']))
        
        # Ambil data terbaru untuk cache sebelum commit
        billing_rows = conn.execute('''
            SELECT zone_name, item_name, qty, timestamp
            FROM (
                SELECT zone_name, item_name, qty, timestamp,
                       ROW_NUMBER() OVER (PARTITION BY zone_name, item_name ORDER BY timestamp DESC) as rn
                FROM billing_log 
                WHERE camera_id = ? AND timestamp > datetime('now', '-10 minutes')
            ) 
            WHERE rn = 1
            ORDER BY timestamp DESC
            LIMIT 20
        ''', (cam_id,)).fetchall()
        
        alerts_rows = conn.execute('''
            SELECT type, message, timestamp 
            FROM events_log 
            WHERE camera_id = ? 
            AND timestamp > datetime('now', '-10 minutes')
            ORDER BY timestamp DESC
            LIMIT 20
        ''', (cam_id,)).fetchall()
        
        # Ambil zones untuk zone states cache
        zones = conn.execute("SELECT name, type FROM zones WHERE camera_id=?", (cam_id,)).fetchall()
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"status": "error", "error": f"Database error: {str(e)}"}
    
    conn.close()
    
    # Update cache untuk WebSocket real-time
    with data_cache_lock:
        # Update zone states cache (gunakan global_zone_states yang sudah di-update)
        with state_lock:
            camera_zone_states = {}
            zone_types = {z['name']: z['type'] for z in zones}
            
            for zone_name in [z['name'] for z in zones]:
                if zone_name in global_zone_states:
                    state = global_zone_states[zone_name]
                    if isinstance(state, dict):
                        camera_zone_states[zone_name] = {
                            **state,
                            "zone_type": zone_types.get(zone_name, "unknown")
                        }
                    else:
                        camera_zone_states[zone_name] = {
                            "status": "UNKNOWN",
                            "timer": state if isinstance(state, (int, float)) else 0,
                            "zone_type": zone_types.get(zone_name, "unknown")
                        }
                else:
                    camera_zone_states[zone_name] = {
                        "status": "UNKNOWN",
                        "timer": 0,
                        "zone_type": zone_types.get(zone_name, "unknown")
                    }
        
        zone_states_cache[cam_id] = {
            "camera_id": cam_id,
            "zone_states": camera_zone_states,
            "timestamp": time.time()
        }
        
        # Update billing cache
        billing_data = []
        for row in billing_rows:
            billing_data.append({
                "zone": row['zone_name'],
                "item": row['item_name'],
                "qty": row['qty'],
                "time": row['timestamp']
            })
        billing_cache[cam_id] = billing_data
        
        # Update alerts cache
        alerts_data = []
        for row in alerts_rows:
            alerts_data.append({
                "type": row['type'],
                "message": row['message'],
                "timestamp": row['timestamp']
            })
        alerts_cache[cam_id] = alerts_data
    
    return {
        "status": "completed",
        "billing_events_count": len(result["billing_events"]),
        "alerts_count": len(result["security_alerts"]),
        "zone_states": result["zone_states"]
    }

@app.post("/analyze/{cam_id}")
def analyze_camera(cam_id: int, current_user: dict = Depends(get_current_user)):
    """
    Endpoint untuk melakukan full analysis pada kamera tertentu.
    Menggantikan fungsi scheduler - melakukan analisis lengkap dan menyimpan ke database.
    
    Features:
    - Billing detection (menyimpan ke billing_log)
    - Security alerts (menyimpan ke events_log)
    - Zone state management (timer meja kotor, status antrian, dll)
    """
    result = _analyze_camera_internal(cam_id)
    
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("error", "Analysis failed"))
    
    return {
        "status": "Analysis completed",
        "camera_id": cam_id,
        **result
    }

@app.post("/analyze/all")
def analyze_all_cameras(current_user: dict = Depends(get_current_user)):
    """
    Endpoint untuk melakukan full analysis pada semua kamera aktif.
    Mirip dengan fungsi patrol_all_cameras() di scheduler.
    """
    conn = get_db_connection()
    cameras = conn.execute("SELECT * FROM cameras WHERE is_active=1").fetchall()
    conn.close()
    
    results = []
    for cam in cameras:
        result = _analyze_camera_internal(cam['id'])
        results.append({
            "camera_id": cam['id'],
            "branch_name": cam['branch_name'],
            **result
        })
    
    return {
        "status": "Batch analysis completed",
        "total_cameras": len(cameras),
        "results": results
    }

@app.get("/billing/live/{cam_id}")
def get_live_billing(cam_id: int):
    """
    Mengambil data log tagihan terbaru untuk ditampilkan di Live Monitor.
    Hanya menampilkan kombinasi unik (zone + item) terbaru untuk menghindari duplikasi.
    """
    conn = get_db_connection()
    
    # Ambil record terbaru untuk setiap kombinasi zone_name + item_name
    # Menggunakan window function untuk mendapatkan record terbaru per kombinasi
    rows = conn.execute('''
        SELECT zone_name, item_name, qty, timestamp
        FROM (
            SELECT zone_name, item_name, qty, timestamp,
                   ROW_NUMBER() OVER (PARTITION BY zone_name, item_name ORDER BY timestamp DESC) as rn
            FROM billing_log 
            WHERE camera_id = ? AND timestamp > datetime('now', '-10 minutes')
        ) 
        WHERE rn = 1
        ORDER BY timestamp DESC
        LIMIT 20
    ''', (cam_id,)).fetchall()
    
    conn.close()
    
    # Format data agar mudah dibaca React
    results = []
    for row in rows:
        results.append({
            "zone": row['zone_name'],     # Misal: "Meja 1"
            "item": row['item_name'],     # Misal: "Mangkok"
            "qty": row['qty'],            # Misal: 2
            "time": row['timestamp']      # Waktu
        })
        
    return results

@app.get("/zones/states/{cam_id}")
def get_zone_states(cam_id: int, current_user: dict = Depends(get_current_user)):
    """
    Get current zone states (dirty table timers, queue counts, gorengan stock, etc.)
    Returns status untuk setiap zone di kamera ini.
    """
    # Ambil daftar zones untuk kamera ini
    conn = get_db_connection()
    zones = conn.execute("SELECT name, type FROM zones WHERE camera_id=?", (cam_id,)).fetchall()
    conn.close()
    
    if not zones:
        return {
            "camera_id": cam_id,
            "zone_states": {},
            "timestamp": datetime.now().isoformat()
        }
    
    zone_names = [z['name'] for z in zones]
    zone_types = {z['name']: z['type'] for z in zones}
    
    # Ambil states dari global_zone_states
    with state_lock:
        camera_states = {}
        for zone_name in zone_names:
            if zone_name in global_zone_states:
                state = global_zone_states[zone_name]
                # Format state untuk frontend
                if isinstance(state, dict):
                    camera_states[zone_name] = {
                        **state,
                        "zone_type": zone_types.get(zone_name, "unknown")
                    }
                else:
                    # Backward compatibility: jika masih integer
                    camera_states[zone_name] = {
                        "status": "UNKNOWN",
                        "timer": state if isinstance(state, (int, float)) else 0,
                        "zone_type": zone_types.get(zone_name, "unknown")
                    }
            else:
                # Default state jika belum ada
                camera_states[zone_name] = {
                    "status": "UNKNOWN",
                    "timer": 0,
                    "zone_type": zone_types.get(zone_name, "unknown")
                }
    
    return {
        "camera_id": cam_id,
        "zone_states": camera_states,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/events/{cam_id}")
def get_events(cam_id: int, current_user: dict = Depends(get_current_user)):
    """
    Get recent events/alerts (dirty_table, long_queue, low_stock, intruder, etc.)
    Returns alerts dari 10 menit terakhir.
    """
    conn = get_db_connection()
    events = conn.execute('''
        SELECT type, message, timestamp 
        FROM events_log 
        WHERE camera_id = ? 
        AND timestamp > datetime('now', '-10 minutes')
        ORDER BY timestamp DESC
        LIMIT 20
    ''', (cam_id,)).fetchall()
    conn.close()
    
    results = []
    for event in events:
        results.append({
            "type": event['type'],
            "message": event['message'],
            "timestamp": event['timestamp']
        })
    
    return results