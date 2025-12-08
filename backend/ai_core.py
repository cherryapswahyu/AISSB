import cv2
import numpy as np
import os
import json
import insightface
from ultralytics import YOLO

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
        # Detects: Hands/Wrists for Refill Logic
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
                        # Filename "Budi_Staff.jpg" -> "Budi"
                        clean_name = os.path.splitext(file)[0].split('_')[0].title()
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

    def analyze_frame(self, frame, zones_config, previous_states={}):
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

        # 3. Face Recognition
        # Run InsightFace on the whole frame
        faces = self.face_app.get(frame)
        detected_faces = []
        
        for face in faces:
            bbox = face.bbox.astype(int)
            cx, cy = (bbox[0]+bbox[2])/2, (bbox[1]+bbox[3])/2
            
            # Identity Check
            name = "Unknown"
            if len(self.known_embeds) > 0:
                sims = np.dot(self.known_embeds, face.normed_embedding.T)
                best_idx = np.argmax(sims)
                if sims[best_idx] > 0.45: # Threshold from Engine 2
                    name = self.known_names[best_idx]
            
            detected_faces.append({"name": name, "centroid": (cx, cy)})

        # =====================================================
        # TAHAP 2: ZONE LOGIC (The Merger)
        # =====================================================
        
        for zone in zones_config:
            z_name = zone['name']
            z_type = zone['type'] # 'table', 'kasir', 'gorengan', 'refill', 'queue', 'restricted'
            
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
                        "items": item_counts
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
                            "needs_cleaning": True
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
                            "needs_cleaning": False
                        }
                else:
                    # Meja BERSIH (tidak ada orang, tidak ada items)
                    new_state = {
                        "status": "BERSIH",
                        "timer": 0,
                        "person_count": 0,
                        "item_count": 0,
                        "items": {}
                    }
                
                final_result["zone_states"][z_name] = new_state

            # --- LOGIC B: KASIR / QUEUE (Crowd Control) ---
            elif z_type == 'kasir' or z_type == 'queue':
                queue_count = 0
                for p_loc in detected_people:
                    if self._is_point_in_zone(p_loc, z_coords, w, h):
                        queue_count += 1
                
                # Threshold check (Engine 2)
                QUEUE_LIMIT = 4 
                if queue_count > QUEUE_LIMIT:
                    final_result["security_alerts"].append({
                        "type": "long_queue",
                        "msg": f"Antrian {z_name} Penuh ({queue_count} orang)"
                    })
                
                final_result["zone_states"][z_name] = queue_count

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
                    final_result["zone_states"][z_name] = "SEDANG_DIAMBIL"
                elif total_stock == 0:
                    final_result["zone_states"][z_name] = "HABIS"
                    # Alert jika stock habis
                    final_result["security_alerts"].append({
                        "type": "low_stock",
                        "msg": f"Tempat Gorengan {z_name} perlu diisi ulang (Stock: 0)"
                    })
                elif total_stock < MIN_STOCK_THRESHOLD:
                    # Alert jika stock rendah
                    final_result["zone_states"][z_name] = {
                        "total": total_stock,
                        "detail": gorengan_stock
                    }
                    final_result["security_alerts"].append({
                        "type": "low_stock",
                        "msg": f"Tempat Gorengan {z_name} stock rendah (Stock: {total_stock}, Min: {MIN_STOCK_THRESHOLD})"
                    })
                else:
                    # Simpan detail stock per jenis
                    final_result["zone_states"][z_name] = {
                        "total": total_stock,
                        "detail": gorengan_stock
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

            # --- LOGIC D: REFILL (Self Service/Refill Station) ---
            elif z_type == 'refill':
                # Check for Hands (Anti-Galau Logic)
                is_blocked = False
                for hand in detected_hands:
                    if self._is_point_in_zone(hand, z_coords, w, h):
                        is_blocked = True
                        break
                
                if is_blocked:
                    final_result["zone_states"][z_name] = "BLOCKED_BY_HAND"
                else:
                    # Count stock (assuming 'mangkok' represents stock/plate for now)
                    # You can add custom logic here for specific food items
                    stock_count = 0
                    for item in detected_items:
                        if self._is_point_in_zone(item['centroid'], z_coords, w, h):
                            stock_count += 1
                    
                    final_result["zone_states"][z_name] = stock_count
                    final_result["billing_events"].append({
                        "zone_name": z_name,
                        "item_name": "STOCK_REPORT",
                        "qty": stock_count
                    })

            # --- LOGIC E: RESTRICTED (Kitchen Security) ---
            elif z_type == 'restricted':
                unknown_intruder = False
                staff_detected = False
                
                for face in detected_faces:
                    if self._is_point_in_zone(face['centroid'], z_coords, w, h):
                        if face['name'] == "Unknown":
                            unknown_intruder = True
                        else:
                            staff_detected = True
                            # Log Staff Attendance
                            final_result["security_alerts"].append({
                                "type": "staff_tracking",
                                "msg": f"Staff {face['name']} di {z_name}"
                            })

                if unknown_intruder:
                    final_result["security_alerts"].append({
                        "type": "intruder",
                        "msg": f"⚠️ ORANG ASING di {z_name}!"
                    })

        return final_result