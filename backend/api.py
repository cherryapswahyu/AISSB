import cv2
import json
import sqlite3
import numpy as np
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List

# Library FastAPI
from fastapi import FastAPI, HTTPException, Depends, status, Response, WebSocket, WebSocketDisconnect, UploadFile, File, Form
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
from database import get_db_connection, init_db, get_wib_datetime, get_wib_datetime_offset
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
    type: str       # 'table', 'kasir', 'gorengan', 'queue', 'dapur'
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
        max_consecutive_errors = 10  # Kurangi threshold untuk lebih responsif
        
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
                        
                        # Gunakan frame yang masih fresh (kurang dari 3 detik untuk lebih toleran)
                        # Tapi skip jika frame terlalu lama untuk menghindari lag
                        if frame_age < 3.0:
                            # Skip frame jika sudah pernah dikirim (untuk menghindari duplikasi)
                            if frame_timestamp != last_timestamp:
                                frame = cached_data["frame"].copy()
                                last_timestamp = frame_timestamp
                
                if frame is None:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        # Kirim error frame jika tidak ada frame dari cache
                        error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(error_frame, "Waiting for camera...", (50, 220), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
                        cv2.putText(error_frame, "Background service starting", (50, 260), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                        success, img_encoded = cv2.imencode(".jpg", error_frame, [
                            cv2.IMWRITE_JPEG_QUALITY, 30  # Lower quality untuk error frame
                        ])
                        if success:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + 
                                   img_encoded.tobytes() + b'\r\n')
                    # Tunggu lebih singkat untuk lebih responsif
                    time.sleep(0.01)
                    continue
                
                # Reset error count jika dapat frame
                consecutive_errors = 0
                
                # Encode dan kirim frame dengan kualitas lebih rendah untuk encoding lebih cepat
                # Kualitas 35 sudah cukup untuk streaming dan jauh lebih cepat dari 50
                success, img_encoded = cv2.imencode(".jpg", frame, [
                    cv2.IMWRITE_JPEG_QUALITY, 35,  # Turunkan quality untuk encoding lebih cepat
                    cv2.IMWRITE_JPEG_OPTIMIZE, 1
                ])
                if success:
                    # Format MJPEG: multipart boundary
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + 
                           img_encoded.tobytes() + b'\r\n')
                
                # Kurangi delay untuk frame rate lebih tinggi (sekitar 30 FPS)
                # Delay lebih pendek untuk streaming lebih smooth
                time.sleep(0.033)  # ~30 FPS
                
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
    
    # Deteksi wajah untuk mendapatkan informasi customer (regular/new/staff)
    face_info_map = {}  # Map centroid face ke customer info
    try:
        faces = engine.face_app.get(frame)
        
        for face in faces:
            try:
                if not hasattr(face, 'bbox') or not hasattr(face, 'normed_embedding'):
                    continue
                    
                bbox = face.bbox.astype(int)
                face_cx = (bbox[0] + bbox[2]) / 2
                face_cy = (bbox[1] + bbox[3]) / 2
                
                # Cek apakah ini staff
                customer_type = "new"
                customer_name = "Pengunjung"
                is_staff = False
                
                if len(engine.known_embeds) > 0 and hasattr(face, 'normed_embedding'):
                    try:
                        embedding = face.normed_embedding
                        if embedding is not None and len(embedding) > 0:
                            sims = np.dot(engine.known_embeds, embedding.T)
                            best_idx = np.argmax(sims)
                            if sims[best_idx] > 0.45:
                                customer_name = engine.known_names[best_idx]
                                customer_type = "staff"
                                is_staff = True
                    except Exception as e:
                        print(f"      ! Error matching staff: {e}")
                
                # Jika bukan staff, cek history pengunjung
                if not is_staff:
                    try:
                        if hasattr(face, 'normed_embedding') and face.normed_embedding is not None:
                            face_hash = engine._get_face_hash(face.normed_embedding)
                            conn = get_db_connection()
                            thirty_days_ago = get_wib_datetime_offset(days=-30)
                            customer = conn.execute('''
                                SELECT visit_count, customer_type, last_seen
                                FROM customer_log
                                WHERE face_embedding_hash = ?
                                AND last_seen > ?
                                ORDER BY last_seen DESC
                                LIMIT 1
                            ''', (face_hash, thirty_days_ago)).fetchone()
                            
                            if customer:
                                customer_type = customer['customer_type']
                                if customer_type == 'regular':
                                    customer_name = "Pengunjung Regular"
                                else:
                                    customer_name = "Pengunjung Baru"
                            else:
                                customer_name = "Pengunjung Baru"
                            
                            conn.close()
                    except Exception as e:
                        print(f"      ! Error getting customer info: {e}")
                        # Fallback ke default
                        customer_name = "Pengunjung Baru"
                
                # Simpan info face dengan key berdasarkan posisi (untuk matching dengan person detection)
                face_info_map[(face_cx, face_cy)] = {
                    "customer_type": customer_type,
                    "customer_name": customer_name,
                    "is_staff": is_staff
                }
            except Exception as e:
                print(f"      ! Error processing face: {e}")
                continue
    except Exception as e:
        print(f"      ! Error in face detection: {e}")
        # Continue tanpa face info jika error
    
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
                "zone": None,  # Akan diisi jika objek ada di zona
                "customer_type": None,
                "customer_name": None
            }
            
            # Jika ini adalah deteksi "orang", coba match dengan face recognition
            if cls_id == 0 and engine.CLASS_MAP.get(cls_id) == "orang":  # Person detection
                try:
                    # Cari face yang paling dekat dengan centroid person
                    min_distance = float('inf')
                    matched_face_info = None
                    
                    for (face_cx, face_cy), face_info in face_info_map.items():
                        try:
                            # Hitung jarak antara centroid person dengan centroid face
                            distance = ((cx - face_cx) ** 2 + (cy - face_cy) ** 2) ** 0.5
                            # Cek apakah face berada di dalam bounding box person
                            if (x1 <= face_cx <= x2 and y1 <= face_cy <= y2) and distance < min_distance:
                                min_distance = distance
                                matched_face_info = face_info
                        except Exception as e:
                            continue
                    
                    # Jika ada match, tambahkan info customer
                    if matched_face_info:
                        detection["customer_type"] = matched_face_info.get("customer_type")
                        detection["customer_name"] = matched_face_info.get("customer_name")
                        # Update name untuk menampilkan info customer
                        if matched_face_info.get("is_staff"):
                            detection["name"] = f"Staff: {matched_face_info.get('customer_name', 'Unknown')}"
                        else:
                            detection["name"] = matched_face_info.get("customer_name", "Pengunjung")
                except Exception as e:
                    print(f"      ! Error matching face with person: {e}")
                    # Continue tanpa customer info jika error
            
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
            cap.set(cv2.CAP_PROP_FPS, 30)  # Set FPS target ke 30 untuk lebih smooth
            # Buang beberapa frame pertama untuk clear buffer lama
            for _ in range(3):  # Kurangi jumlah frame yang dibuang
                cap.grab()
            
            print(f"[Background] Camera {cam_id} connected, reading frames...")
            
            while camera_threads_running.get(cam_id, True):
                ret, frame = cap.read()
                
                if not ret:
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"[Background] Camera {cam_id} disconnected, attempting reconnect...")
                        break
                    # Tunggu lebih singkat untuk lebih responsif
                    time.sleep(0.01)
                    continue
                
                consecutive_errors = 0
                
                # Resize frame untuk mempercepat encoding dan mengurangi bandwidth
                # Resize ke maksimal 800x450 untuk encoding lebih cepat (lebih kecil dari sebelumnya)
                h, w = frame.shape[:2]
                if w > 800 or h > 450:
                    scale = min(800.0 / w, 450.0 / h)
                    new_w = int(w * scale)
                    new_h = int(h * scale)
                    # Gunakan INTER_AREA untuk resize down (lebih cepat dan lebih baik untuk downsampling)
                    frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                
                # Update frame cache (dengan timestamp yang lebih presisi)
                current_time = time.time()
                with frame_cache_lock:
                    # Hanya update jika frame baru (untuk menghindari overwrite dengan frame lama)
                    if cam_id not in frame_cache or (current_time - frame_cache[cam_id]["timestamp"]) > 0.01:
                        frame_cache[cam_id] = {
                            "frame": frame.copy(),
                            "timestamp": current_time
                        }
                
                # Kurangi sleep untuk frame rate lebih tinggi (sekitar 30 FPS)
                # Hapus sleep jika memungkinkan untuk update lebih cepat
                time.sleep(0.01)  # Minimal sleep untuk tidak membebani CPU
            
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
                    import traceback
                    error_msg = str(e)
                    print(f"[Realtime] Exception during detection for camera {cam_id}: {error_msg}")
                    print(f"[Realtime] Traceback: {traceback.format_exc()}")
            
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
    result = engine.analyze_frame(frame, zones_config, current_states, camera_id=cam_id)
    
    if not result:
        conn.close()
        return {"status": "error", "error": "Analysis failed"}
    
    # Update global state dan tracking durasi
    previous_states_copy = {}
    with state_lock:
        previous_states_copy = global_zone_states.copy()
        global_zone_states.update(result["zone_states"])
    
    # Tracking durasi meja terisi dan antrian penuh
    # Gunakan WIB timezone untuk semua timestamp
    from datetime import timezone, timedelta
    wib_tz = timezone(timedelta(hours=7))
    current_time = datetime.now(wib_tz)
    
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
                        # Konversi datetime ke string format WIB
                        start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(start_time, datetime) else str(start_time)
                        end_time_str = current_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(current_time, datetime) else str(current_time)
                        conn.execute('''
                            INSERT INTO table_occupancy_log 
                            (camera_id, zone_name, start_time, end_time, duration_seconds, person_count, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'completed')
                        ''', (cam_id, zone_name, start_time_str, end_time_str, int(duration), tracking_data["person_count"]))
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
                        # Konversi datetime ke string format WIB
                        start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(start_time, datetime) else str(start_time)
                        end_time_str = current_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(current_time, datetime) else str(current_time)
                        conn.execute('''
                            INSERT INTO queue_log 
                            (camera_id, zone_name, start_time, end_time, duration_seconds, max_queue_count, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'completed')
                        ''', (cam_id, zone_name, start_time_str, end_time_str, int(duration), tracking_data["queue_count"]))
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
            two_minutes_ago = get_wib_datetime_offset(minutes=-2)
            exist = conn.execute('''
                SELECT id, qty FROM billing_log 
                WHERE camera_id=? AND zone_name=? AND item_name=? 
                AND timestamp > ?
            ''', (cam_id, bill['zone_name'], bill['item_name'], two_minutes_ago)).fetchone()
            
            if exist:
                new_qty = exist['qty'] + bill['qty']
                conn.execute("UPDATE billing_log SET qty=?, timestamp=? WHERE id=?", 
                           (new_qty, get_wib_datetime(), exist['id']))
            else:
                conn.execute("INSERT INTO billing_log (camera_id, zone_name, item_name, qty, timestamp) VALUES (?,?,?,?,?)",
                           (cam_id, bill['zone_name'], bill['item_name'], bill['qty'], get_wib_datetime()))
        
        # B. Simpan Security Alerts
        for alert in result["security_alerts"]:
            one_minute_ago = get_wib_datetime_offset(minutes=-1)
            last_alert = conn.execute('''
                SELECT id FROM events_log 
                WHERE camera_id=? AND type=? AND timestamp > ?
            ''', (cam_id, alert['type'], one_minute_ago)).fetchone()
            
            if not last_alert:
                conn.execute("INSERT INTO events_log (camera_id, type, message, timestamp) VALUES (?,?,?,?)",
                           (cam_id, alert['type'], alert['msg'], get_wib_datetime()))
        
        # Ambil data terbaru untuk cache sebelum commit
        ten_minutes_ago = get_wib_datetime_offset(minutes=-10)
        billing_rows = conn.execute('''
            SELECT zone_name, item_name, qty, timestamp
            FROM (
                SELECT zone_name, item_name, qty, timestamp,
                       ROW_NUMBER() OVER (PARTITION BY zone_name, item_name ORDER BY timestamp DESC) as rn
                FROM billing_log 
                WHERE camera_id = ? AND timestamp > ?
            ) 
            WHERE rn = 1
            ORDER BY timestamp DESC
            LIMIT 20
        ''', (cam_id, ten_minutes_ago)).fetchall()
        
        alerts_rows = conn.execute('''
            SELECT type, message, timestamp 
            FROM events_log 
            WHERE camera_id = ? 
            AND timestamp > ?
            ORDER BY timestamp DESC
            LIMIT 20
        ''', (cam_id, ten_minutes_ago)).fetchall()
        
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
    ten_minutes_ago = get_wib_datetime_offset(minutes=-10)
    rows = conn.execute('''
        SELECT zone_name, item_name, qty, timestamp
        FROM (
            SELECT zone_name, item_name, qty, timestamp,
                   ROW_NUMBER() OVER (PARTITION BY zone_name, item_name ORDER BY timestamp DESC) as rn
            FROM billing_log 
            WHERE camera_id = ? AND timestamp > ?
        ) 
        WHERE rn = 1
        ORDER BY timestamp DESC
        LIMIT 20
    ''', (cam_id, ten_minutes_ago)).fetchall()
    
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
    ten_minutes_ago = get_wib_datetime_offset(minutes=-10)
    events = conn.execute('''
        SELECT type, message, timestamp 
        FROM events_log 
        WHERE camera_id = ? 
        AND timestamp > ?
        ORDER BY timestamp DESC
        LIMIT 20
    ''', (cam_id, ten_minutes_ago)).fetchall()
    conn.close()
    
    results = []
    for event in events:
        results.append({
            "type": event['type'],
            "message": event['message'],
            "timestamp": event['timestamp']
        })
    
    return results

@app.get("/customers/stats")
def get_customer_stats(current_user: dict = Depends(get_current_user)):
    """Get customer statistics (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh melihat statistik")
    
    conn = get_db_connection()
    
    # Total customers
    total = conn.execute("SELECT COUNT(DISTINCT face_embedding_hash) as total FROM customer_log").fetchone()
    
    # Regular customers (visit >= 5)
    regular = conn.execute("""
        SELECT COUNT(DISTINCT face_embedding_hash) as total 
        FROM customer_log 
        WHERE customer_type = 'regular'
    """).fetchone()
    
    # New customers (visit < 5)
    new = conn.execute("""
        SELECT COUNT(DISTINCT face_embedding_hash) as total 
        FROM customer_log 
        WHERE customer_type = 'new'
    """).fetchone()
    
    # Recent visits (hari ini)
    today = conn.execute("""
        SELECT COUNT(*) as total 
        FROM customer_log 
        WHERE DATE(last_seen) = DATE('now')
    """).fetchone()
    
    conn.close()
    
    return {
        "total_customers": total['total'],
        "regular_customers": regular['total'],
        "new_customers": new['total'],
        "visits_today": today['total']
    }

# ==========================================
# 11. ENDPOINTS: REPORTS
# ==========================================

@app.get("/reports/table-occupancy")
def get_table_occupancy_report(
    camera_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    group_by: str = 'day',
    current_user: dict = Depends(get_current_user)
):
    """Get table occupancy report dengan group by day/month"""
    conn = get_db_connection()
    
    # Build query conditions
    conditions = []
    params = []
    
    # Filter berdasarkan role
    if current_user['role'] == 'staff':
        # Staff hanya bisa lihat cabang mereka sendiri
        staff_branch_id = current_user.get('branch_id')
        if staff_branch_id:
            conditions.append("t.camera_id IN (SELECT id FROM cameras WHERE branch_id = ?)")
            params.append(staff_branch_id)
    elif current_user['role'] == 'admin':
        # Admin bisa filter berdasarkan branch_id jika diberikan
        if branch_id:
            conditions.append("t.camera_id IN (SELECT id FROM cameras WHERE branch_id = ?)")
            params.append(branch_id)
    
    if camera_id:
        conditions.append("t.camera_id = ?")
        params.append(camera_id)
    
    if start_date:
        conditions.append("DATE(start_time) >= ?")
        params.append(start_date)
    
    if end_date:
        conditions.append("DATE(start_time) <= ?")
        params.append(end_date)
    
    if start_date:
        conditions.append("DATE(t.start_time) >= ?")
        params.append(start_date)
    
    if end_date:
        conditions.append("DATE(t.start_time) <= ?")
        params.append(end_date)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Determine date grouping
    if group_by == 'month':
        date_group = "strftime('%Y-%m', t.start_time)"
        date_format = "strftime('%Y-%m', t.start_time) as date"
    else:  # day
        date_group = "DATE(t.start_time)"
        date_format = "DATE(t.start_time) as date"
    
    # Summary query dengan JOIN ke cameras untuk filter branch
    summary_query = f"""
        SELECT 
            COUNT(*) as total_sessions,
            SUM(t.duration_seconds) as total_duration_seconds,
            AVG(t.duration_seconds) as avg_duration_seconds,
            COUNT(DISTINCT t.zone_name) as total_tables_occupied
        FROM table_occupancy_log t
        LEFT JOIN cameras c ON t.camera_id = c.id
        WHERE {where_clause}
    """
    summary = conn.execute(summary_query, params).fetchone()
    
    # Daily/Monthly summary
    daily_summary_query = f"""
        SELECT 
            {date_format},
            COUNT(*) as total_sessions,
            SUM(t.duration_seconds) as total_duration_seconds,
            AVG(t.duration_seconds) as avg_duration_seconds,
            COUNT(DISTINCT t.zone_name) as total_tables_occupied
        FROM table_occupancy_log t
        LEFT JOIN cameras c ON t.camera_id = c.id
        WHERE {where_clause}
        GROUP BY {date_group}
        ORDER BY date DESC
    """
    daily_summary_rows = conn.execute(daily_summary_query, params).fetchall()
    
    # Table summary (per zone)
    table_summary_query = f"""
        SELECT 
            t.zone_name,
            COUNT(*) as total_sessions,
            SUM(t.duration_seconds) as total_duration_seconds,
            AVG(t.duration_seconds) as avg_duration_seconds
        FROM table_occupancy_log t
        LEFT JOIN cameras c ON t.camera_id = c.id
        WHERE {where_clause}
        GROUP BY t.zone_name
        ORDER BY total_sessions DESC
    """
    table_summary_rows = conn.execute(table_summary_query, params).fetchall()
    
    # Details
    details_query = f"""
        SELECT 
            t.zone_name,
            t.start_time,
            t.end_time,
            t.duration_seconds,
            t.person_count
        FROM table_occupancy_log t
        LEFT JOIN cameras c ON t.camera_id = c.id
        WHERE {where_clause}
        ORDER BY t.start_time DESC
        LIMIT 1000
    """
    details_rows = conn.execute(details_query, params).fetchall()
    
    conn.close()
    
    # Format response
    def format_duration(seconds):
        if not seconds:
            return "0 detik"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours} jam {minutes} menit"
        elif minutes > 0:
            return f"{minutes} menit {secs} detik"
        return f"{secs} detik"
    
    # Build response with correct key name
    response = {
        "summary": {
            "total_sessions": summary['total_sessions'] or 0,
            "total_duration_seconds": summary['total_duration_seconds'] or 0,
            "avg_duration_seconds": float(summary['avg_duration_seconds'] or 0),
            "total_tables_occupied": summary['total_tables_occupied'] or 0,
            "total_duration_formatted": format_duration(summary['total_duration_seconds'] or 0),
            "avg_duration_formatted": format_duration(int(summary['avg_duration_seconds'] or 0))
        },
        "table_summary": [
            {
                "zone_name": row['zone_name'],
                "total_sessions": row['total_sessions'],
                "total_duration_seconds": row['total_duration_seconds'] or 0,
                "avg_duration_seconds": float(row['avg_duration_seconds'] or 0),
                "total_duration_formatted": format_duration(row['total_duration_seconds'] or 0),
                "avg_duration_formatted": format_duration(int(row['avg_duration_seconds'] or 0))
            }
            for row in table_summary_rows
        ],
        "details": [
            {
                "zone_name": row['zone_name'],
                "start_time": row['start_time'],
                "end_time": row['end_time'],
                "duration_seconds": row['duration_seconds'] or 0,
                "person_count": row['person_count'],
                "duration_formatted": format_duration(row['duration_seconds'] or 0)
            }
            for row in details_rows
        ]
    }
    
    # Add daily or monthly summary based on group_by
    summary_key = "daily_summary" if group_by == 'day' else "monthly_summary"
    response[summary_key] = [
            {
                "date": row['date'],
                "total_sessions": row['total_sessions'],
                "total_duration_seconds": row['total_duration_seconds'] or 0,
                "avg_duration_seconds": float(row['avg_duration_seconds'] or 0),
                "total_tables_occupied": row['total_tables_occupied'],
                "total_duration_formatted": format_duration(row['total_duration_seconds'] or 0),
                "avg_duration_formatted": format_duration(int(row['avg_duration_seconds'] or 0))
            }
            for row in daily_summary_rows
    ]
    
    return response

@app.get("/reports/queue")
def get_queue_report(
    camera_id: Optional[int] = None,
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    group_by: str = 'day',
    current_user: dict = Depends(get_current_user)
):
    """Get queue report dengan group by day/month"""
    conn = get_db_connection()
    
    # Build query conditions
    conditions = []
    params = []
    
    # Filter berdasarkan role
    if current_user['role'] == 'staff':
        # Staff hanya bisa lihat cabang mereka sendiri
        staff_branch_id = current_user.get('branch_id')
        if staff_branch_id:
            conditions.append("q.camera_id IN (SELECT id FROM cameras WHERE branch_id = ?)")
            params.append(staff_branch_id)
    elif current_user['role'] == 'admin':
        # Admin bisa filter berdasarkan branch_id jika diberikan
        if branch_id:
            conditions.append("q.camera_id IN (SELECT id FROM cameras WHERE branch_id = ?)")
            params.append(branch_id)
    
    if camera_id:
        conditions.append("q.camera_id = ?")
        params.append(camera_id)
    
    if start_date:
        conditions.append("DATE(q.start_time) >= ?")
        params.append(start_date)
    
    if end_date:
        conditions.append("DATE(q.start_time) <= ?")
        params.append(end_date)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Determine date grouping
    if group_by == 'month':
        date_group = "strftime('%Y-%m', q.start_time)"
        date_format = "strftime('%Y-%m', q.start_time) as date"
    else:  # day
        date_group = "DATE(q.start_time)"
        date_format = "DATE(q.start_time) as date"
    
    # Summary query dengan JOIN ke cameras untuk filter branch
    summary_query = f"""
        SELECT 
            COUNT(*) as total_sessions,
            SUM(q.duration_seconds) as total_duration_seconds,
            AVG(q.duration_seconds) as avg_duration_seconds,
            MAX(q.duration_seconds) as max_duration_seconds
        FROM queue_log q
        LEFT JOIN cameras c ON q.camera_id = c.id
        WHERE {where_clause}
    """
    summary = conn.execute(summary_query, params).fetchone()
    
    # Daily/Monthly summary
    daily_summary_query = f"""
        SELECT 
            {date_format},
            COUNT(*) as total_sessions,
            SUM(q.duration_seconds) as total_duration_seconds,
            AVG(q.duration_seconds) as avg_duration_seconds,
            MAX(q.duration_seconds) as max_duration_seconds
        FROM queue_log q
        LEFT JOIN cameras c ON q.camera_id = c.id
        WHERE {where_clause}
        GROUP BY {date_group}
        ORDER BY date DESC
    """
    daily_summary_rows = conn.execute(daily_summary_query, params).fetchall()
    
    # Zone summary
    zone_summary_query = f"""
        SELECT 
            q.zone_name,
            COUNT(*) as total_sessions,
            SUM(q.duration_seconds) as total_duration_seconds,
            AVG(q.duration_seconds) as avg_duration_seconds
        FROM queue_log q
        LEFT JOIN cameras c ON q.camera_id = c.id
        WHERE {where_clause}
        GROUP BY q.zone_name
        ORDER BY total_sessions DESC
    """
    zone_summary_rows = conn.execute(zone_summary_query, params).fetchall()
    
    # Details
    details_query = f"""
        SELECT 
            q.zone_name,
            q.start_time,
            q.end_time,
            q.duration_seconds,
            q.max_queue_count
        FROM queue_log q
        LEFT JOIN cameras c ON q.camera_id = c.id
        WHERE {where_clause}
        ORDER BY q.start_time DESC
        LIMIT 1000
    """
    details_rows = conn.execute(details_query, params).fetchall()
    
    # Count distinct zones (sebelum close connection)
    zone_count_query = f"""
        SELECT COUNT(DISTINCT q.zone_name) as total_zones
        FROM queue_log q
        LEFT JOIN cameras c ON q.camera_id = c.id
        WHERE {where_clause}
    """
    zone_count = conn.execute(zone_count_query, params).fetchone()
    
    conn.close()
    
    # Format response
    def format_duration(seconds):
        if not seconds:
            return "0 detik"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours} jam {minutes} menit"
        elif minutes > 0:
            return f"{minutes} menit {secs} detik"
        return f"{secs} detik"
    
    # Build response with correct key name
    response = {
        "summary": {
            "total_sessions": summary['total_sessions'] or 0,
            "total_duration_seconds": summary['total_duration_seconds'] or 0,
            "avg_duration_seconds": float(summary['avg_duration_seconds'] or 0),
            "max_duration_seconds": summary['max_duration_seconds'] or 0,
            "total_zones_affected": zone_count['total_zones'] or 0,
            "total_duration_formatted": format_duration(summary['total_duration_seconds'] or 0),
            "avg_duration_formatted": format_duration(int(summary['avg_duration_seconds'] or 0)),
            "max_duration_formatted": format_duration(summary['max_duration_seconds'] or 0)
        },
        "zone_summary": [
            {
                "zone_name": row['zone_name'],
                "total_sessions": row['total_sessions'],
                "total_duration_seconds": row['total_duration_seconds'] or 0,
                "avg_duration_seconds": float(row['avg_duration_seconds'] or 0),
                "total_duration_formatted": format_duration(row['total_duration_seconds'] or 0),
                "avg_duration_formatted": format_duration(int(row['avg_duration_seconds'] or 0))
            }
            for row in zone_summary_rows
        ],
        "details": [
            {
                "zone_name": row['zone_name'],
                "start_time": row['start_time'],
                "end_time": row['end_time'],
                "duration_seconds": row['duration_seconds'] or 0,
                "max_queue_count": row['max_queue_count'],
                "duration_formatted": format_duration(row['duration_seconds'] or 0)
            }
            for row in details_rows
        ]
    }
    
    # Add daily or monthly summary based on group_by
    summary_key = "daily_summary" if group_by == 'day' else "monthly_summary"
    response[summary_key] = [
            {
                "date": row['date'],
                "total_sessions": row['total_sessions'],
                "total_duration_seconds": row['total_duration_seconds'] or 0,
                "avg_duration_seconds": float(row['avg_duration_seconds'] or 0),
                "max_duration_seconds": row['max_duration_seconds'] or 0,
                "total_duration_formatted": format_duration(row['total_duration_seconds'] or 0),
                "avg_duration_formatted": format_duration(int(row['avg_duration_seconds'] or 0)),
                "max_duration_formatted": format_duration(row['max_duration_seconds'] or 0)
            }
            for row in daily_summary_rows
    ]
    
    return response

@app.get("/reports/customers")
def get_customer_report(
    branch_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    group_by: str = 'day',
    current_user: dict = Depends(get_current_user)
):
    """Get customer report dengan group by day/month"""
    conn = get_db_connection()
    
    # Build query conditions
    conditions = []
    params = []
    
    # Filter berdasarkan role
    if current_user['role'] == 'staff':
        # Staff hanya bisa lihat cabang mereka sendiri
        staff_branch_id = current_user.get('branch_id')
        if staff_branch_id:
            conditions.append("(cl.branch_id = ? OR cl.camera_id IN (SELECT id FROM cameras WHERE branch_id = ?))")
            params.append(staff_branch_id)
            params.append(staff_branch_id)
    elif current_user['role'] == 'admin':
        # Admin bisa filter berdasarkan branch_id jika diberikan
        if branch_id:
            conditions.append("(cl.branch_id = ? OR cl.camera_id IN (SELECT id FROM cameras WHERE branch_id = ?))")
            params.append(branch_id)
            params.append(branch_id)
    
    if start_date:
        conditions.append("DATE(cl.last_seen) >= ?")
        params.append(start_date)
    
    if end_date:
        conditions.append("DATE(cl.last_seen) <= ?")
        params.append(end_date)
    
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    
    # Determine date grouping
    if group_by == 'month':
        date_group = "strftime('%Y-%m', cl.last_seen)"
        date_format = "strftime('%Y-%m', cl.last_seen) as date"
    else:  # day
        date_group = "DATE(cl.last_seen)"
        date_format = "DATE(cl.last_seen) as date"
    
    # Build JOIN clause (tidak diperlukan karena kita menggunakan subquery)
    join_clause = ""
    
    # Summary query dengan conditional JOIN
    summary_query = f"""
        SELECT 
            COUNT(DISTINCT cl.face_embedding_hash) as total_customers,
            SUM(CASE WHEN cl.customer_type = 'regular' THEN 1 ELSE 0 END) as regular_customers,
            SUM(CASE WHEN cl.customer_type = 'new' THEN 1 ELSE 0 END) as new_customers,
            SUM(cl.visit_count) as total_visits
        FROM customer_log cl
        {join_clause}
        WHERE {where_clause}
    """
    summary = conn.execute(summary_query, params).fetchone()
    
    # Daily/Monthly summary
    daily_summary_query = f"""
        SELECT 
            {date_format},
            COUNT(DISTINCT cl.face_embedding_hash) as total_customers,
            SUM(CASE WHEN cl.customer_type = 'regular' THEN 1 ELSE 0 END) as regular_customers,
            SUM(CASE WHEN cl.customer_type = 'new' THEN 1 ELSE 0 END) as new_customers,
            SUM(cl.visit_count) as visits
        FROM customer_log cl
        {join_clause}
        WHERE {where_clause}
        GROUP BY {date_group}
        ORDER BY date DESC
    """
    daily_summary_rows = conn.execute(daily_summary_query, params).fetchall()
    
    # Details
    details_query = f"""
        SELECT 
            DATE(cl.last_seen) as date,
            cl.face_embedding_hash as customer_hash,
            cl.customer_type,
            cl.visit_count,
            cl.first_seen,
            cl.last_seen
        FROM customer_log cl
        {join_clause}
        WHERE {where_clause}
        ORDER BY cl.last_seen DESC
        LIMIT 1000
    """
    details_rows = conn.execute(details_query, params).fetchall()
    
    conn.close()
    
    # Build response with correct key name
    response = {
        "summary": {
            "total_customers": summary['total_customers'] or 0,
            "regular_customers": summary['regular_customers'] or 0,
            "new_customers": summary['new_customers'] or 0,
            "total_visits": summary['total_visits'] or 0
        },
        "details": [
            {
                "date": row['date'],
                "customer_hash": row['customer_hash'],
                "customer_type": row['customer_type'],
                "visit_count": row['visit_count'],
                "first_seen": row['first_seen'],
                "last_seen": row['last_seen']
            }
            for row in details_rows
        ]
    }
    
    # Add daily or monthly summary based on group_by
    summary_key = "daily_summary" if group_by == 'day' else "monthly_summary"
    response[summary_key] = [
        {
            "date": row['date'],
            "total_customers": row['total_customers'],
            "regular_customers": row['regular_customers'],
            "new_customers": row['new_customers'],
            "visits": row['visits']
        }
        for row in daily_summary_rows
    ]
    
    return response

# ==========================================
# 12. ENDPOINTS: STAFF FACE MANAGEMENT
# ==========================================

@app.post("/staff-faces/upload")
def upload_staff_face(
    file: UploadFile = File(...),
    staff_name: str = Form(None),
    current_user: dict = Depends(get_current_user)
):
    """Upload foto staff untuk face recognition (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh upload foto staff")
    
    # Validasi file
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename tidak valid")
    
    # Validasi ekstensi
    allowed_extensions = {'.jpg', '.jpeg', '.png'}
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400, 
            detail=f"Format file tidak didukung. Gunakan: {', '.join(allowed_extensions)}"
        )
    
    # Pastikan folder known_faces ada
    known_faces_path = "known_faces"
    if not os.path.exists(known_faces_path):
        os.makedirs(known_faces_path)
    
    # Simpan file
    file_path = None
    try:
        # Gunakan staff_name jika diberikan, jika tidak gunakan dari filename
        if staff_name and staff_name.strip():
            # Generate nama file dari staff_name + ekstensi asli
            safe_staff_name = "".join(c for c in staff_name.strip() if c.isalnum() or c in (' ', '-', '_')).strip()
            file_ext = os.path.splitext(file.filename)[1].lower()
            safe_filename = f"{safe_staff_name}{file_ext}"
        else:
            # Fallback ke filename asli (untuk backward compatibility)
            safe_filename = "".join(c for c in file.filename if c.isalnum() or c in (' ', '-', '_', '.')).strip()
        
        file_path = os.path.join(known_faces_path, safe_filename)
        
        # Baca dan simpan file
        contents = file.file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        
        # Validasi bahwa file berisi wajah
        engine = get_ai_engine()
        img = cv2.imread(file_path)
        if img is None:
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=400, detail="File gambar tidak valid")
        
        faces = engine.face_app.get(img)
        if not faces or len(faces) == 0:
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=400, detail="Tidak ada wajah terdeteksi di foto. Pastikan foto menampilkan wajah dengan jelas.")
        
        if len(faces) > 1:
            if os.path.exists(file_path):
                os.remove(file_path)
            raise HTTPException(status_code=400, detail="Terlalu banyak wajah di foto. Gunakan foto dengan satu wajah saja.")
        
        # Reload known faces
        engine.known_embeds, engine.known_names = engine._load_known_faces()
        
        # Ambil staff_name yang digunakan (dari input atau dari filename)
        final_staff_name = staff_name.strip() if staff_name and staff_name.strip() else os.path.splitext(safe_filename)[0].split('_')[0].title()
        
        return {
            "status": "success",
            "message": f"Foto staff '{final_staff_name}' berhasil diupload",
            "filename": safe_filename,
            "staff_name": final_staff_name,
            "total_staff": len(engine.known_names)
        }
    except HTTPException:
        raise
    except Exception as e:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")

@app.get("/staff-faces/")
def list_staff_faces(current_user: dict = Depends(get_current_user)):
    """List semua foto staff yang terdaftar (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh melihat daftar staff")
    
    known_faces_path = "known_faces"
    if not os.path.exists(known_faces_path):
        return {"staff_faces": []}
    
    staff_faces = []
    for file in os.listdir(known_faces_path):
        if file.lower().endswith(('jpg', 'png', 'jpeg')):
            file_path = os.path.join(known_faces_path, file)
            if os.path.isfile(file_path):
                file_size = os.path.getsize(file_path)
                staff_name = os.path.splitext(file)[0].split('_')[0].title()
                staff_faces.append({
                    "filename": file,
                    "staff_name": staff_name,
                    "size": file_size,
                    "size_mb": round(file_size / (1024 * 1024), 2)
                })
    
    # Sort by filename
    staff_faces.sort(key=lambda x: x['filename'])
    
    return {
        "staff_faces": staff_faces,
        "total": len(staff_faces)
    }

@app.get("/staff-faces/{filename}")
def get_staff_face_image(filename: str):
    """Get staff face image file"""
    known_faces_path = "known_faces"
    file_path = os.path.join(known_faces_path, filename)
    
    # Validasi path untuk mencegah directory traversal
    if not os.path.abspath(file_path).startswith(os.path.abspath(known_faces_path)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    
    return Response(
        content=open(file_path, "rb").read(),
        media_type="image/jpeg" if filename.lower().endswith(('.jpg', '.jpeg')) else "image/png"
    )

@app.delete("/staff-faces/{filename}")
def delete_staff_face(
    filename: str,
    current_user: dict = Depends(get_current_user)
):
    """Hapus foto staff (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh menghapus foto staff")
    
    known_faces_path = "known_faces"
    file_path = os.path.join(known_faces_path, filename)
    
    # Validasi path untuk mencegah directory traversal
    if not os.path.abspath(file_path).startswith(os.path.abspath(known_faces_path)):
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File tidak ditemukan")
    
    try:
        os.remove(file_path)
        
        # Reload known faces
        engine = get_ai_engine()
        engine.known_embeds, engine.known_names = engine._load_known_faces()
        
        return {
            "status": "success",
            "message": f"Foto '{filename}' berhasil dihapus",
            "total_staff": len(engine.known_names)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting file: {str(e)}")

@app.post("/staff-faces/reload")
def reload_staff_faces(current_user: dict = Depends(get_current_user)):
    """Reload known faces tanpa restart server (hanya admin)"""
    if current_user['role'] != 'admin':
        raise HTTPException(status_code=403, detail="Hanya Admin boleh reload staff faces")
    
    try:
        engine = get_ai_engine()
        engine.known_embeds, engine.known_names = engine._load_known_faces()
        
        return {
            "status": "success",
            "message": f"Staff faces berhasil di-reload",
            "total_staff": len(engine.known_names),
            "staff_names": engine.known_names.tolist() if hasattr(engine.known_names, 'tolist') else list(engine.known_names)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reloading staff faces: {str(e)}")