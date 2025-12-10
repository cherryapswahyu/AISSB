import cv2
import numpy as np
import os
import json
import hashlib
import threading
import time
import sqlite3
from datetime import datetime
import insightface
from ultralytics import YOLO
from database import get_db_connection, get_wib_datetime, get_wib_datetime_offset

# Import konfigurasi gorengan (optional)
try:
    from config_gorengan import (
        GORENGAN_CLASS_MAPPING,
        GORENGAN_MODEL_PATH,
        GORENGAN_CONFIDENCE_THRESHOLD,
        MIN_STOCK_THRESHOLD
    )
except ImportError:
    # Default jika config tidak ada
    GORENGAN_CLASS_MAPPING = {}
    GORENGAN_MODEL_PATH = "models/gorengan_model.pt"
    GORENGAN_CONFIDENCE_THRESHOLD = 0.4
    MIN_STOCK_THRESHOLD = 3

class SuperAIEngine:
    def __init__(self):
        print("⏳ [AI CORE] Initializing Super Engine (Soto Cloud x InsightFace)...")
        
        # In-memory cache untuk tracking face yang baru terdeteksi (mencegah duplikasi)
        # Format: {face_hash: {
        #   "last_seen": timestamp,
        #   "visit_count": int,
        #   "customer_type": str,
        #   "embeddings": [np.array],  # Multiple embeddings untuk averaging
        #   "avg_embedding": np.array  # Average embedding untuk matching yang lebih stabil
        # }}
        self.face_cache = {}
        self.face_cache_lock = threading.Lock()
        
        # =====================================================
        # 1. LOAD MODELS (The Brains)
        # =====================================================
        
        # A. YOLO Object Detection (From Engine 1 & 2)
        # Detects: Person, Bowl, Cup, Bottle
        print("    + Loading YOLOv8 Object Detection...")
        self.model_object = YOLO('yolov8s.pt')
        
        # A.1. Custom YOLO Model untuk Gorengan (Optional)
        # Jika ada custom model untuk deteksi gorengan spesifik
        self.model_gorengan = None
        if os.path.exists(GORENGAN_MODEL_PATH):
            try:
                print("    + Loading Custom Gorengan Detection Model...")
                self.model_gorengan = YOLO(GORENGAN_MODEL_PATH)
                print("      > Custom gorengan model loaded successfully")
            except Exception as e:
                print(f"      > Failed to load custom gorengan model: {e}")
                print("      > Will use standard object detection as fallback")
        else:
            print("    + Custom gorengan model not found, using standard detection") 
        
        # B. YOLO Pose Estimation (From Engine 1)
        # Detects: Hands/Wrists for Gorengan Zone (deteksi aktivitas mengambil)
        print("    + Loading YOLOv8 Pose Estimation...")
        self.model_pose = YOLO('yolov8n-pose.pt') # 'n' version is faster for real-time
        
        # C. InsightFace (From Engine 2)
        # Detects: Staff Identity vs Strangers
        print("    + Loading InsightFace...")
        try:
            # Try GPU first (CUDA)
            self.face_app = insightface.app.FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider'])
            self.face_app.prepare(ctx_id=0, det_size=(640, 640))
            print("      > InsightFace running on GPU")
        except Exception as e:
            # Fallback to CPU
            print(f"      > InsightFace running on CPU (Warning: Slower). Error: {e}")
            self.face_app = insightface.app.FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
            self.face_app.prepare(ctx_id=0, det_size=(640, 640))

        # =====================================================
        # 2. LOAD KNOWLEDGE (Known Faces)
        # =====================================================
        self.known_faces_path = "known_faces"
        self.known_embeds, self.known_names = self._load_known_faces()
        
        # =====================================================
        # 3. CLASS MAPPING (Standard COCO)
        # =====================================================
        # Only track dining related objects + Person
        self.DINING_OBJECTS = [39, 41, 42, 43, 44, 45] # Bottle, Cup, Fork, Knife, Spoon, Bowl
        self.CLASS_MAP = {
            39: "botol", 41: "gelas", 42: "garpu", 
            43: "pisau", 44: "sendok", 45: "mangkok",
            0: "orang"
        }
        
        # =====================================================
        # 4. GORENGAN CLASS MAPPING (Custom)
        # =====================================================
        # Mapping untuk berbagai jenis gorengan dari config
        self.GORENGAN_CLASSES = GORENGAN_CLASS_MAPPING.copy()
        if len(self.GORENGAN_CLASSES) > 0:
            print(f"    + Loaded {len(self.GORENGAN_CLASSES)} gorengan types from config")
        
        # Jika tidak ada custom model, gunakan deteksi umum berdasarkan bentuk/warna
        # Mapping objek COCO yang bisa mewakili gorengan
        self.GORENGAN_PROXY_OBJECTS = {
            45: "mangkok",  # Bowl bisa mewakili wadah gorengan
            41: "gelas",    # Cup bisa mewakili wadah kecil
            # Tambahkan mapping lain jika perlu
        }
        
        print("✅ [AI CORE] Ready to process!")

    def _load_known_faces(self):
        """
        Scans the 'known_faces' folder and creates embeddings.
        (Logic ported from Engine 2)
        """
        embeds, names = [], []
        if not os.path.exists(self.known_faces_path):
            os.makedirs(self.known_faces_path)
            return np.array(embeds), names
            
        print(f"    + Scanning known faces in '{self.known_faces_path}'...")
        for file in os.listdir(self.known_faces_path):
            if file.lower().endswith(('jpg', 'png', 'jpeg')):
                try:
                    path = os.path.join(self.known_faces_path, file)
                    img = cv2.imread(path)
                    faces = self.face_app.get(img)
                    if faces:
                        embeds.append(faces[0].normed_embedding)
                        # Filename "Budi.jpg" atau "Budi_Santoso.jpg" -> ambil semua sebelum ekstensi
                        # Jika ada underscore, ambil bagian pertama saja untuk backward compatibility
                        # Tapi lebih baik gunakan semua nama sebelum ekstensi
                        file_base = os.path.splitext(file)[0]
                        # Jika ada underscore, ambil bagian pertama (untuk backward compatibility)
                        # Tapi jika tidak ada underscore, gunakan semua nama
                        if '_' in file_base:
                            clean_name = file_base.split('_')[0].title()
                        else:
                            clean_name = file_base.title()
                        names.append(clean_name)
                        print(f"      - Registered: {clean_name}")
                except Exception as e:
                    print(f"      ! Failed to load {file}: {e}")
        return np.array(embeds), names

    def _is_point_in_zone(self, point, zone_coords, w, h):
        """Checks if (x,y) is inside a percentage-based box [x1, y1, x2, y2]"""
        px, py = point
        zx1, zy1 = zone_coords[0] * w, zone_coords[1] * h
        zx2, zy2 = zone_coords[2] * w, zone_coords[3] * h
        return (zx1 < px < zx2) and (zy1 < py < zy2)

    def _get_face_hash(self, embedding):
        """Generate hash dari face embedding untuk identifikasi unik"""
        embedding_bytes = embedding.tobytes()
        return hashlib.sha256(embedding_bytes).hexdigest()[:16]
    
    def _find_similar_face_in_db(self, embedding, threshold=0.6):
        """
        Cari wajah yang mirip di database menggunakan cosine similarity.
        Mengembalikan customer data jika similarity > threshold, None jika tidak ada.
        """
        try:
            conn = get_db_connection()
            # Ambil semua face_hash dari database (dalam 30 hari terakhir)
            thirty_days_ago = get_wib_datetime_offset(days=-30)
            customers = conn.execute('''
                SELECT face_embedding_hash, visit_count, customer_type, last_seen
                FROM customer_log
                WHERE last_seen > ?
            ''', (thirty_days_ago,)).fetchall()
            conn.close()
            
            if len(customers) == 0:
                return None
            
            # Load semua embeddings dari database (kita perlu simpan embedding, bukan hanya hash)
            # Untuk sekarang, kita gunakan hash matching + similarity check di cache
            # Tapi karena kita tidak simpan embedding di DB, kita gunakan cache saja
            return None
        except Exception as e:
            print(f"      ! Error finding similar face: {e}")
            return None
    
    def _get_customer_type(self, visit_count):
        """Tentukan tipe customer: regular (>=5 visits) atau new (<5)"""
        return 'regular' if visit_count >= 5 else 'new'

    def analyze_frame(self, frame, zones_config, previous_states={}, camera_id=None):
        """
        THE MAIN BRAIN.
        Inputs:
          - frame: Image array
          - zones_config: List of dicts from DB (coords, type, name)
          - previous_states: Dict containing timers (e.g., {'Table 1': 5})
          
        Returns:
          - analysis: Dict containing 'billing', 'alerts', 'new_states'
        """
        if frame is None: return None
        h, w = frame.shape[:2]
        
        # Output Containers
        final_result = {
            "billing_events": [], # For billing_log (Engine 1)
            "security_alerts": [], # For events_log (Engine 2)
            "zone_states": {},    # Updated timers/status
            "visual_debug": []    # Coordinates for drawing on frontend
        }

        # =====================================================
        # TAHAP 1: GLOBAL INFERENCE (Run Models Once)
        # =====================================================
        
        # 1. Object Detection (Standard)
        res_obj = self.model_object(frame, verbose=False, conf=0.35)[0]
        detected_items = []
        detected_people = [] # Centroids of people
        detected_gorengan = [] # Deteksi gorengan spesifik
        
        for box in res_obj.boxes:
            cls_id = int(box.cls[0])
            xyxy = box.xyxy[0].cpu().numpy()
            cx, cy = (xyxy[0]+xyxy[2])/2, (xyxy[1]+xyxy[3])/2
            conf = float(box.conf[0])
            
            if cls_id == 0: # Person
                detected_people.append((cx, cy))
            elif cls_id in self.DINING_OBJECTS:
                detected_items.append({
                    "name": self.CLASS_MAP.get(cls_id, "unknown"),
                    "centroid": (cx, cy),
                    "confidence": conf
                })
        
        # 1.1. Custom Gorengan Detection (Jika ada model khusus)
        if self.model_gorengan is not None:
            try:
                res_gorengan = self.model_gorengan(frame, verbose=False, conf=GORENGAN_CONFIDENCE_THRESHOLD)[0]
                for box in res_gorengan.boxes:
                    cls_id = int(box.cls[0])
                    xyxy = box.xyxy[0].cpu().numpy()
                    cx, cy = (xyxy[0]+xyxy[2])/2, (xyxy[1]+xyxy[3])/2
                    conf = float(box.conf[0])
                    
                    gorengan_name = self.GORENGAN_CLASSES.get(cls_id, f"gorengan_{cls_id}")
                    detected_gorengan.append({
                        "name": gorengan_name,
                        "centroid": (cx, cy),
                        "confidence": conf,
                        "bbox": xyxy
                    })
            except Exception as e:
                print(f"      ! Error in gorengan detection: {e}")

        # 2. Pose Estimation (Hands)
        res_pose = self.model_pose(frame, verbose=False, conf=0.5)[0]
        detected_hands = []
        if res_pose.keypoints:
            for kps in res_pose.keypoints.xy.cpu().numpy():
                if len(kps) > 10:
                    detected_hands.append(kps[9])  # Left Wrist
                    detected_hands.append(kps[10]) # Right Wrist

        # 3. Face Recognition dengan Customer Tracking (GLOBAL)
        # Run InsightFace on the whole frame
        from database import get_db_connection
        faces = self.face_app.get(frame)
        detected_faces = []
        
        for face in faces:
            bbox = face.bbox.astype(int)
            cx, cy = (bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2
            
            # Identity Check
            name = "Unknown"
            customer_type = "new"  # Default: pengunjung baru
            face_hash = None
            visit_count = 0
            is_staff = False
            
            # Cek apakah ini staff (dari known_faces)
            if len(self.known_embeds) > 0:
                sims = np.dot(self.known_embeds, face.normed_embedding.T)
                best_idx = np.argmax(sims)
                if sims[best_idx] > 0.45:  # Threshold dari Engine 2
                    name = self.known_names[best_idx]
                    customer_type = "staff"
                    is_staff = True
            
            # Jika bukan staff, cek history pengunjung (GLOBAL tracking)
            if not is_staff:
                try:
                    face_hash = self._get_face_hash(face.normed_embedding)
                    current_time = time.time()
                    
                    # 1. Cek in-memory cache dulu (untuk deduplication cepat tanpa query DB)
                    matched_hash = None
                    if self.face_cache_lock:
                        with self.face_cache_lock:
                            # Cek similarity dengan semua face di cache (dalam 60 detik terakhir)
                            best_similarity = 0.6  # Minimum threshold (turunkan dari 0.7)
                            best_match = None
                            
                            for cached_hash, cache_data in self.face_cache.items():
                                if current_time - cache_data['last_seen'] < 60:  # Perpanjang window ke 60 detik
                                    try:
                                        # Gunakan average embedding untuk matching yang lebih stabil
                                        avg_embedding = cache_data.get('avg_embedding')
                                        if avg_embedding is not None:
                                            similarity = np.dot(face.normed_embedding, avg_embedding)
                                            if similarity > best_similarity:
                                                best_similarity = similarity
                                                best_match = cached_hash
                                                matched_hash = cached_hash
                                                
                                                # Update dengan moving average (70% old, 30% new) untuk stabilitas
                                                new_avg = 0.7 * avg_embedding + 0.3 * face.normed_embedding
                                                cache_data['last_seen'] = current_time
                                                cache_data['avg_embedding'] = new_avg
                                                
                                                # Simpan embedding baru ke list untuk averaging
                                                if 'embeddings' not in cache_data:
                                                    cache_data['embeddings'] = []
                                                cache_data['embeddings'].append(face.normed_embedding.copy())
                                                
                                                # Keep only last 5 embeddings untuk menghindari memory leak
                                                if len(cache_data['embeddings']) > 5:
                                                    cache_data['embeddings'].pop(0)
                                                
                                                # Recalculate average dari semua embeddings untuk akurasi lebih baik
                                                if len(cache_data['embeddings']) > 0:
                                                    cache_data['avg_embedding'] = np.mean(cache_data['embeddings'], axis=0)
                                                
                                                visit_count = cache_data['visit_count']
                                                customer_type = cache_data['customer_type']
                                                break
                                    except Exception as e:
                                        pass
                            
                            # Jika tidak ada match dengan similarity, cek exact hash
                            if matched_hash is None and face_hash in self.face_cache:
                                cache_data = self.face_cache[face_hash]
                                if current_time - cache_data['last_seen'] < 60:
                                    # Masih dalam window waktu, gunakan data cache
                                    cache_data['last_seen'] = current_time
                                    
                                    # Update average embedding dengan moving average
                                    if 'avg_embedding' in cache_data and cache_data['avg_embedding'] is not None:
                                        cache_data['avg_embedding'] = 0.7 * cache_data['avg_embedding'] + 0.3 * face.normed_embedding
                                    else:
                                        cache_data['avg_embedding'] = face.normed_embedding.copy()
                                    
                                    # Simpan embedding baru
                                    if 'embeddings' not in cache_data:
                                        cache_data['embeddings'] = []
                                    cache_data['embeddings'].append(face.normed_embedding.copy())
                                    if len(cache_data['embeddings']) > 5:
                                        cache_data['embeddings'].pop(0)
                                    
                                    # Recalculate average
                                    if len(cache_data['embeddings']) > 0:
                                        cache_data['avg_embedding'] = np.mean(cache_data['embeddings'], axis=0)
                                    
                                    visit_count = cache_data['visit_count']
                                    customer_type = cache_data['customer_type']
                                    matched_hash = face_hash
                    
                    # 2. Jika tidak ada di cache, query database dengan retry logic
                    if matched_hash is None:
                        max_retries = 3
                        retry_count = 0
                        customer = None
                        
                        while retry_count < max_retries:
                            try:
                                conn = get_db_connection()
                                conn.execute("PRAGMA busy_timeout = 5000")  # Set timeout 5 detik
                                
                                # Ambil branch_id dari camera_id jika tersedia
                                branch_id = None
                                if camera_id:
                                    cam_info = conn.execute("SELECT branch_id FROM cameras WHERE id = ?", (camera_id,)).fetchone()
                                    if cam_info:
                                        branch_id = cam_info['branch_id']
                                
                                # Cari customer dengan face_hash yang sama (dalam 30 hari terakhir)
                                thirty_days_ago = get_wib_datetime_offset(days=-30)
                                customer = conn.execute('''
                                    SELECT face_embedding_hash, visit_count, customer_type, last_seen, camera_id, branch_id
                                    FROM customer_log
                                    WHERE face_embedding_hash = ?
                                    AND last_seen > ?
                                    ORDER BY last_seen DESC
                                    LIMIT 1
                                ''', (face_hash, thirty_days_ago)).fetchone()
                                
                                if customer:
                                    # Cek apakah last_seen masih sangat baru (kurang dari 10 detik)
                                    last_seen_str = customer['last_seen']
                                    try:
                                        last_seen_dt = datetime.strptime(last_seen_str, '%Y-%m-%d %H:%M:%S')
                                        time_diff = (datetime.now() - last_seen_dt).total_seconds()
                                        
                                        if time_diff < 10:  # Kurang dari 10 detik, hanya update timestamp dan camera/branch
                                            conn.execute('''
                                                UPDATE customer_log
                                                SET last_seen = ?, camera_id = ?, branch_id = ?
                                                WHERE face_embedding_hash = ?
                                            ''', (get_wib_datetime(), camera_id, branch_id, face_hash))
                                            conn.commit()
                                            visit_count = customer['visit_count']
                                            customer_type = customer['customer_type']
                                        else:
                                            # Lebih dari 10 detik, increment visit_count
                                            visit_count = customer['visit_count'] + 1
                                            old_customer_type = customer['customer_type']
                                            customer_type = self._get_customer_type(visit_count)
                                            
                                            conn.execute('''
                                                UPDATE customer_log
                                                SET visit_count = ?,
                                                    last_seen = ?,
                                                    customer_type = ?,
                                                    camera_id = ?,
                                                    branch_id = ?
                                                WHERE face_embedding_hash = ?
                                            ''', (visit_count, get_wib_datetime(), customer_type, camera_id, branch_id, face_hash))
                                            conn.commit()
                                            
                                            if old_customer_type == 'new' and customer_type == 'regular':
                                                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                                print(f"⭐ [PENGUNJUNG REGULAR] Face Hash: {face_hash[:8]}... | Visit: {visit_count} | Time: {timestamp}")
                                    except Exception as e:
                                        # Jika parsing error, tetap increment visit_count
                                        visit_count = customer['visit_count'] + 1
                                        old_customer_type = customer['customer_type']
                                        customer_type = self._get_customer_type(visit_count)
                                        
                                        conn.execute('''
                                            UPDATE customer_log
                                            SET visit_count = ?,
                                                last_seen = ?,
                                                customer_type = ?,
                                                camera_id = ?,
                                                branch_id = ?
                                            WHERE face_embedding_hash = ?
                                        ''', (visit_count, get_wib_datetime(), customer_type, camera_id, branch_id, face_hash))
                                        conn.commit()
                                        
                                        if old_customer_type == 'new' and customer_type == 'regular':
                                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                            print(f"⭐ [PENGUNJUNG REGULAR] Face Hash: {face_hash[:8]}... | Visit: {visit_count} | Time: {timestamp}")
                                    
                                    # Update cache dengan format baru (multiple embeddings)
                                    if self.face_cache_lock:
                                        with self.face_cache_lock:
                                            self.face_cache[face_hash] = {
                                                'last_seen': current_time,
                                                'visit_count': visit_count,
                                                'customer_type': customer_type,
                                                'embeddings': [face.normed_embedding.copy()],
                                                'avg_embedding': face.normed_embedding.copy()
                                            }
                                    
                                    conn.close()
                                    break
                                else:
                                    # Cek apakah ada entry dengan face_hash yang sama yang baru saja dibuat (dalam 10 detik)
                                    ten_seconds_ago = get_wib_datetime_offset(seconds=-10)
                                    recent_customer = conn.execute('''
                                        SELECT face_embedding_hash, visit_count, customer_type, last_seen
                                        FROM customer_log
                                        WHERE face_embedding_hash = ?
                                        AND last_seen > ?
                                        ORDER BY last_seen DESC
                                        LIMIT 1
                                    ''', (face_hash, ten_seconds_ago)).fetchone()
                                    
                                    if recent_customer:
                                        # Sudah ada entry baru, hanya update timestamp
                                        conn.execute('''
                                            UPDATE customer_log
                                            SET last_seen = ?, camera_id = ?, branch_id = ?
                                            WHERE face_embedding_hash = ?
                                        ''', (get_wib_datetime(), camera_id, branch_id, face_hash))
                                        conn.commit()
                                        visit_count = recent_customer['visit_count']
                                        customer_type = recent_customer['customer_type']
                                        
                                        # Update cache dengan format baru (multiple embeddings)
                                        if self.face_cache_lock:
                                            with self.face_cache_lock:
                                                self.face_cache[face_hash] = {
                                                    'last_seen': current_time,
                                                    'visit_count': visit_count,
                                                    'customer_type': customer_type,
                                                    'embeddings': [face.normed_embedding.copy()],
                                                    'avg_embedding': face.normed_embedding.copy()
                                                }
                                        
                                        conn.close()
                                        break
                                    else:
                                        # Customer baru, insert ke database
                                        try:
                                            wib_time = get_wib_datetime()
                                            conn.execute('''
                                                INSERT INTO customer_log 
                                                (face_embedding_hash, visit_count, customer_type, first_seen, last_seen, camera_id, branch_id)
                                                VALUES (?, 1, 'new', ?, ?, ?, ?)
                                            ''', (face_hash, wib_time, wib_time, camera_id, branch_id))
                                            conn.commit()
                                            visit_count = 1
                                            customer_type = 'new'
                                            
                                            # Update cache dengan format baru (multiple embeddings)
                                            if self.face_cache_lock:
                                                with self.face_cache_lock:
                                                    self.face_cache[face_hash] = {
                                                        'last_seen': current_time,
                                                        'visit_count': visit_count,
                                                        'customer_type': customer_type,
                                                        'embeddings': [face.normed_embedding.copy()],
                                                        'avg_embedding': face.normed_embedding.copy()
                                                    }
                                            
                                            # Print notification untuk pengunjung baru
                                            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                            print(f"🆕 [PENGUNJUNG BARU] Face Hash: {face_hash[:8]}... | Visit: 1 | Time: {timestamp}")
                                            
                                            conn.close()
                                            break
                                        except sqlite3.IntegrityError:
                                            # Hash sudah ada (race condition), query lagi
                                            conn.close()
                                            retry_count += 1
                                            time.sleep(0.1)
                                            continue
                                    
                            except sqlite3.OperationalError as e:
                                if "database is locked" in str(e):
                                    conn.close()
                                    retry_count += 1
                                    if retry_count < max_retries:
                                        time.sleep(0.2 * retry_count)  # Exponential backoff
                                        continue
                                    else:
                                        # Fallback: gunakan cache atau default
                                        if self.face_cache_lock:
                                            with self.face_cache_lock:
                                                if face_hash in self.face_cache:
                                                    cache_data = self.face_cache[face_hash]
                                                    visit_count = cache_data['visit_count']
                                                    customer_type = cache_data['customer_type']
                                                else:
                                                    visit_count = 1
                                                    customer_type = 'new'
                                        else:
                                            visit_count = 1
                                            customer_type = 'new'
                                        break
                                else:
                                    conn.close()
                                    raise
                            except Exception as e:
                                if conn:
                                    conn.close()
                                print(f"      ! Error tracking customer: {e}")
                                # Fallback: gunakan cache atau default
                                if self.face_cache_lock:
                                    with self.face_cache_lock:
                                        if face_hash in self.face_cache:
                                            cache_data = self.face_cache[face_hash]
                                            visit_count = cache_data['visit_count']
                                            customer_type = cache_data['customer_type']
                                        else:
                                            visit_count = 1
                                            customer_type = 'new'
                                else:
                                    visit_count = 1
                                    customer_type = 'new'
                                break
                    
                    # Cleanup cache lama (lebih dari 5 menit)
                    if self.face_cache_lock:
                        with self.face_cache_lock:
                            expired_keys = [k for k, v in self.face_cache.items() 
                                          if current_time - v['last_seen'] > 300]
                            for key in expired_keys:
                                del self.face_cache[key]
                                
                except Exception as e:
                    print(f"      ! Error tracking customer: {e}")
                    # Fallback: tetap unknown jika error
                    visit_count = 0
                    customer_type = 'new'
            
            detected_faces.append({
                "name": name,
                "centroid": (cx, cy),
                "customer_type": customer_type,  # 'staff', 'regular', 'new'
                "visit_count": visit_count,
                "is_staff": is_staff
            })

        # =====================================================
        # TAHAP 2: ZONE LOGIC (The Merger)
        # =====================================================
        
        for zone in zones_config:
            z_name = zone['name']
            z_type = zone['type'] # 'table', 'kasir', 'gorengan', 'queue', 'dapur'
            
            # Parse JSON coords from DB
            try:
                z_coords = json.loads(zone['coords'])
            except:
                z_coords = zone['coords'] # Handle if already list

            # --- LOGIC A: TABLE (Billing & Dirty Detection) ---
            if z_type == 'table':
                # Count Items in Zone
                item_counts = {}
                for item in detected_items:
                    if self._is_point_in_zone(item['centroid'], z_coords, w, h):
                        item_counts[item['name']] = item_counts.get(item['name'], 0) + 1
                
                # Check Occupancy (Is there a person?)
                is_occupied = False
                person_count = 0
                for p_loc in detected_people:
                    if self._is_point_in_zone(p_loc, z_coords, w, h):
                        is_occupied = True
                        person_count += 1
                
                # Customer tracking untuk zona meja (dari global tracking)
                regular_count = 0
                new_count = 0
                staff_count = 0
                for face_info in detected_faces:
                    if self._is_point_in_zone(face_info['centroid'], z_coords, w, h):
                        if face_info['is_staff']:
                            staff_count += 1
                        elif face_info['customer_type'] == 'regular':
                            regular_count += 1
                        elif face_info['customer_type'] == 'new':
                            new_count += 1
                
                # 1. Billing Logic (Engine 1)
                for iname, iqty in item_counts.items():
                    final_result["billing_events"].append({
                        "zone_name": z_name,
                        "item_name": iname,
                        "qty": iqty
                    })

                # 2. Dirty Table Logic (Engine 2)
                # State logic: Simpan status lengkap dengan informasi detail
                current_state = previous_states.get(z_name, {})
                if isinstance(current_state, dict):
                    current_timer_value = current_state.get('timer', 0)
                else:
                    # Backward compatibility: jika state masih integer
                    current_timer_value = current_state if isinstance(current_state, (int, float)) else 0
                
                if is_occupied:
                    # Meja TERISI (ada customer)
                    new_state = {
                        "status": "TERISI",
                        "timer": 0,
                        "person_count": person_count,
                        "item_count": len(item_counts),
                        "items": item_counts,
                        "customer_info": {
                            "regular_count": regular_count,
                            "new_count": new_count,
                            "staff_count": staff_count,
                            "total_customers": regular_count + new_count
                        }
                    }
                elif len(item_counts) > 0:
                    # Meja KOSONG tapi ada items → KOTOR
                    new_timer = current_timer_value + 1
                    if new_timer > 3:  # 15 detik threshold (3 * 5 detik interval)
                        new_state = {
                            "status": "KOTOR",
                            "timer": new_timer,
                            "person_count": 0,
                            "item_count": len(item_counts),
                            "items": item_counts,
                            "needs_cleaning": True,
                            "customer_info": {
                                "regular_count": 0,
                                "new_count": 0,
                                "staff_count": 0,
                                "total_customers": 0
                            }
                        }
                        final_result["security_alerts"].append({
                            "type": "dirty_table",
                            "msg": f"{z_name} perlu dibersihkan (Items: {len(item_counts)})"
                        })
                    else:
                        new_state = {
                            "status": "KOTOR",
                            "timer": new_timer,
                            "person_count": 0,
                            "item_count": len(item_counts),
                            "items": item_counts,
                            "needs_cleaning": False,
                            "customer_info": {
                                "regular_count": 0,
                                "new_count": 0,
                                "staff_count": 0,
                                "total_customers": 0
                            }
                        }
                else:
                    # Meja BERSIH (tidak ada orang, tidak ada items)
                    new_state = {
                        "status": "BERSIH",
                        "timer": 0,
                        "person_count": 0,
                        "item_count": 0,
                        "items": {},
                        "customer_info": {
                            "regular_count": 0,
                            "new_count": 0,
                            "staff_count": 0,
                            "total_customers": 0
                        }
                    }
                
                new_state["zone_type"] = z_type
                final_result["zone_states"][z_name] = new_state

            # --- LOGIC B: KASIR / QUEUE (Crowd Control) ---
            elif z_type == 'kasir' or z_type == 'queue':
                queue_count = 0
                for p_loc in detected_people:
                    if self._is_point_in_zone(p_loc, z_coords, w, h):
                        queue_count += 1
                
                # Customer tracking untuk antrian (dari global tracking)
                regular_count = 0
                new_count = 0
                staff_count = 0
                for face_info in detected_faces:
                    if self._is_point_in_zone(face_info['centroid'], z_coords, w, h):
                        if face_info['is_staff']:
                            staff_count += 1
                        elif face_info['customer_type'] == 'regular':
                            regular_count += 1
                        elif face_info['customer_type'] == 'new':
                            new_count += 1
                
                # Threshold check (Engine 2)
                QUEUE_LIMIT = 4 
                if queue_count > QUEUE_LIMIT:
                    final_result["security_alerts"].append({
                        "type": "long_queue",
                        "msg": f"Antrian {z_name} Penuh ({queue_count} orang)"
                    })
                
                final_result["zone_states"][z_name] = {
                    "person_count": queue_count,
                    "customer_info": {
                        "regular_count": regular_count,
                        "new_count": new_count,
                        "staff_count": staff_count,
                        "total_customers": regular_count + new_count
                    },
                    "zone_type": z_type
                }

            # --- LOGIC C: GORENGAN (Tempat Gorengan) ---
            elif z_type == 'gorengan':
                # Check for Hands (Deteksi aktivitas mengambil)
                is_blocked = False
                for hand in detected_hands:
                    if self._is_point_in_zone(hand, z_coords, w, h):
                        is_blocked = True
                        break
                
                # Count stock gorengan per jenis
                gorengan_stock = {}  # {jenis: jumlah}
                total_stock = 0
                
                # 1. Deteksi gorengan spesifik (jika ada custom model)
                if len(detected_gorengan) > 0:
                    for gorengan in detected_gorengan:
                        if self._is_point_in_zone(gorengan['centroid'], z_coords, w, h):
                            jenis = gorengan['name']
                            gorengan_stock[jenis] = gorengan_stock.get(jenis, 0) + 1
                            total_stock += 1
                
                # 2. Fallback: Deteksi wadah (mangkok/piring) sebagai indikator stock
                # Jika tidak ada custom model atau tidak terdeteksi gorengan spesifik
                if total_stock == 0:
                    for item in detected_items:
                        if self._is_point_in_zone(item['centroid'], z_coords, w, h):
                            # Gunakan wadah sebagai proxy untuk stock
                            if item['name'] in self.GORENGAN_PROXY_OBJECTS.values():
                                proxy_name = f"wadah_{item['name']}"
                                gorengan_stock[proxy_name] = gorengan_stock.get(proxy_name, 0) + 1
                                total_stock += 1
                
                # State management
                if is_blocked:
                    final_result["zone_states"][z_name] = {
                        "status": "SEDANG_DIAMBIL",
                        "zone_type": z_type
                    }
                elif total_stock == 0:
                    final_result["zone_states"][z_name] = {
                        "status": "HABIS",
                        "zone_type": z_type
                    }
                    # Alert jika stock habis
                    final_result["security_alerts"].append({
                        "type": "low_stock",
                        "msg": f"Tempat Gorengan {z_name} perlu diisi ulang (Stock: 0)"
                    })
                elif total_stock < MIN_STOCK_THRESHOLD:
                    # Alert jika stock rendah
                    final_result["zone_states"][z_name] = {
                        "total": total_stock,
                        "detail": gorengan_stock,
                        "zone_type": z_type
                    }
                    final_result["security_alerts"].append({
                        "type": "low_stock",
                        "msg": f"Tempat Gorengan {z_name} stock rendah (Stock: {total_stock}, Min: {MIN_STOCK_THRESHOLD})"
                    })
                else:
                    # Simpan detail stock per jenis
                    final_result["zone_states"][z_name] = {
                        "total": total_stock,
                        "detail": gorengan_stock,
                        "zone_type": z_type
                    }
                
                # Log stock untuk monitoring (per jenis)
                for jenis, jumlah in gorengan_stock.items():
                    final_result["billing_events"].append({
                        "zone_name": z_name,
                        "item_name": f"GORENGAN_{jenis.upper()}",
                        "qty": jumlah
                    })
                
                # Log total stock juga
                final_result["billing_events"].append({
                    "zone_name": z_name,
                    "item_name": "GORENGAN_TOTAL_STOCK",
                    "qty": total_stock
                })

            # --- LOGIC D: DAPUR (Kitchen Security) ---
            elif z_type == 'dapur':
                # Hanya staff yang boleh masuk dapur
                non_staff_detected = False
                staff_detected = False
                
                for face_info in detected_faces:
                    if self._is_point_in_zone(face_info['centroid'], z_coords, w, h):
                        if face_info['is_staff']:
                            staff_detected = True
                            # Log Staff Attendance
                            final_result["security_alerts"].append({
                                "type": "staff_tracking",
                                "msg": f"Staff {face_info['name']} di {z_name}"
                            })
                        else:
                            # Semua yang bukan staff dianggap tidak diizinkan
                            non_staff_detected = True

                if non_staff_detected:
                    final_result["security_alerts"].append({
                        "type": "intruder",
                        "msg": f"⚠️ ORANG ASING di {z_name}!"
                    })

        return final_result