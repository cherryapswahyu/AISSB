import cv2
import json
import sqlite3
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List

# Library FastAPI
from fastapi import FastAPI, HTTPException, Depends, status, Response
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time

# Library Security
from jose import JWTError, jwt
from passlib.context import CryptContext

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
# 0.1. GLOBAL STATE MANAGEMENT (Untuk Zone States)
# ==========================================
# Global Memory untuk Timer Meja Kotor & Status Antrian
# Format: { "Meja 1": 5, "Kasir": 3 } -> Meja 1 kotor sdh 5 detik
global_zone_states = {}  # {zone_name: state_value}
state_lock = threading.Lock()  # Thread-safe access

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
    init_db()

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
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
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
    Mengirim frames secara kontinyu dalam format multipart/x-mixed-replace.
    """
    conn = get_db_connection()
    cam = conn.execute("SELECT rtsp_url FROM cameras WHERE id=?", (cam_id,)).fetchone()
    conn.close()
    
    if not cam:
        raise HTTPException(404, "Camera not found")
    
    url = cam['rtsp_url']
    # Fix Webcam Laptop (String vs Int)
    if str(url).isdigit():
        url = int(url)
    
    def generate_frames():
        cap = None
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                # Coba buka kamera
                # Untuk webcam Windows, coba DirectShow dulu, jika gagal fallback ke default
                if isinstance(url, int):
                    # Coba DirectShow dulu
                    cap = cv2.VideoCapture(url, cv2.CAP_DSHOW)
                    if not cap.isOpened():
                        # Jika DirectShow gagal, coba default backend
                        cap = cv2.VideoCapture(url)
                else:
                    cap = cv2.VideoCapture(url)
                
                if not cap.isOpened():
                    retry_count += 1
                    if retry_count >= max_retries:
                        # Kirim error frame
                        error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(error_frame, "Camera not available", (50, 240), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                        success, img_encoded = cv2.imencode(".jpg", error_frame)
                        if success:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + 
                                   img_encoded.tobytes() + b'\r\n')
                        time.sleep(1)
                        continue
                    time.sleep(1)  # Tunggu sebelum retry
                    continue
                
                # Reset retry count jika berhasil
                retry_count = 0
                
                # Set buffer size kecil untuk mengurangi delay
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                
                # Buang beberapa frame pertama untuk clear buffer
                for _ in range(3):
                    cap.grab()
                
                consecutive_errors = 0
                max_consecutive_errors = 10
                
                while True:
                    ret, frame = cap.read()
                    
                    if not ret:
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            # Kamera terputus, coba reconnect
                            print(f"[Stream {cam_id}] Camera disconnected, attempting reconnect...")
                            break
                        time.sleep(0.1)
                        continue
                    
                    consecutive_errors = 0
                    
                    # Update shared frame cache untuk scheduler
                    with frame_cache_lock:
                        frame_cache[cam_id] = {
                            "frame": frame.copy(),  # Copy untuk thread safety
                            "timestamp": time.time()
                        }
                    
                    # Encode frame ke JPEG
                    success, img_encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if not success:
                        continue
                    
                    # Format MJPEG: multipart boundary
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + 
                           img_encoded.tobytes() + b'\r\n')
                    
                    # Delay untuk frame rate (sekitar 30 FPS)
                    time.sleep(0.033)
                
                # Jika keluar dari loop, release dan coba reconnect
                if cap:
                    cap.release()
                    cap = None
                time.sleep(1)  # Tunggu sebelum reconnect
                
            except Exception as e:
                print(f"[Stream {cam_id}] Error: {e}")
                if cap:
                    cap.release()
                    cap = None
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(2)  # Tunggu lebih lama sebelum retry
                else:
                    # Kirim error frame setelah semua retry gagal
                    try:
                        error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                        cv2.putText(error_frame, f"Camera Error: {str(e)[:30]}", (20, 220), 
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                        cv2.putText(error_frame, "Check camera connection", (20, 260), 
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

@app.get("/detections/{cam_id}")
def get_detections(cam_id: int):
    """
    Endpoint untuk mendapatkan deteksi objek real-time dari frame cache.
    Mengembalikan koordinat dan informasi objek yang terdeteksi.
    """
    
    # Ambil frame dari cache
    with frame_cache_lock:
        if cam_id not in frame_cache:
            raise HTTPException(status_code=404, detail="Frame not available in cache. Start streaming first.")
        
        cached_data = frame_cache[cam_id]
        frame_age = time.time() - cached_data["timestamp"]
        # Kurangi timeout menjadi 2 detik untuk memastikan frame lebih fresh (real-time)
        if frame_age > 2.0:
            raise HTTPException(status_code=404, detail=f"Frame expired (age: {frame_age:.1f}s). Start streaming first.")
        
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
    
    return {
        "camera_id": cam_id,
        "timestamp": time.time(),
        "frame_timestamp": cached_data["timestamp"],  # Timestamp frame yang digunakan
        "detections": detections,
        "frame_size": {"width": int(w), "height": int(h)},
        "detection_count": len(detections)
    }

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
    
    # Update global state
    with state_lock:
        global_zone_states.update(result["zone_states"])
    
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
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"status": "error", "error": f"Database error: {str(e)}"}
    
    conn.close()
    
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