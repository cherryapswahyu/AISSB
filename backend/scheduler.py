import time
import schedule
import threading
import requests
import numpy as np
import cv2
from datetime import datetime
from database import get_db_connection

# Import Engine Baru
from ai_core import SuperAIEngine

# Global Memory untuk Timer Meja Kotor & Status Antrian
# Format: { "Meja 1": 5, "Kasir": 3 } -> Meja 1 kotor sdh 5 detik
global_zone_states = {} 
state_lock = threading.Lock()

print("⏳ Memuat Super AI Engine...")
engine = SuperAIEngine() 

def process_one_camera(cam):
    cam_id = cam['id']
    branch = cam['branch_name']
    
    # Koneksi DB Per-Thread
    conn = get_db_connection()
    
    try:
        # 1. Ambil Config Zona dari DB
        zones = conn.execute("SELECT * FROM zones WHERE camera_id=?", (cam_id,)).fetchall()
        if not zones: return

        # Format zona untuk AI
        zones_config = []
        for z in zones:
            zones_config.append({
                "name": z["name"],
                "type": z["type"],
                "coords": z["coords"] # String JSON
            })

        # 2. Ambil Frame dari API Cache
        # (Sesuai solusi Conflict B: Engine tidak akses kamera langsung)
        try:
            resp = requests.get(f"http://localhost:8000/frame-cache/{cam_id}", timeout=2)
            if resp.status_code != 200: return
            arr = np.frombuffer(resp.content, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except:
            return

        # 3. PROSES AI (Menggunakan Global State)
        with state_lock:
            # Kirim state sebelumnya ke AI untuk dihitung (increment timer)
            current_states = global_zone_states.copy()
        
        # === RUN SUPER ENGINE ===
        # Return format: { "billing_events": [], "security_alerts": [], "zone_states": {} }
        result = engine.analyze_frame(frame, zones_config, current_states)
        
        if not result: return

        # 4. UPDATE MEMORY (STATE)
        with state_lock:
            # Update global state dengan hasil terbaru dari AI
            # Contoh: Timer meja bertambah, atau di-reset jadi 0
            global_zone_states.update(result["zone_states"])

        # 5. SIMPAN DATA KE DATABASE
        
        # A. Simpan Billing (Logic Increment Engine 1)
        for bill in result["billing_events"]:
            # Cek duplikat 2 menit terakhir
            exist = conn.execute('''
                SELECT id, qty FROM billing_log 
                WHERE camera_id=? AND zone_name=? AND item_name=? 
                AND timestamp > datetime('now', '-2 minutes')
            ''', (cam_id, bill['zone_name'], bill['item_name'])).fetchone()
            
            if exist:
                new_qty = exist['qty'] + bill['qty'] # Accumulate
                conn.execute("UPDATE billing_log SET qty=?, timestamp=datetime('now') WHERE id=?", (new_qty, exist['id']))
            else:
                conn.execute("INSERT INTO billing_log (camera_id, zone_name, item_name, qty) VALUES (?,?,?,?)",
                             (cam_id, bill['zone_name'], bill['item_name'], bill['qty']))

        # B. Simpan Security Alerts (Logic Baru Engine 2)
        for alert in result["security_alerts"]:
            # alert format: { "type": "intruder", "msg": "..." }
            
            # Anti-Spam: Cek apakah alert yang sama sudah masuk 1 menit terakhir
            last_alert = conn.execute('''
                SELECT id FROM events_log 
                WHERE camera_id=? AND type=? AND timestamp > datetime('now', '-1 minutes')
            ''', (cam_id, alert['type'])).fetchone()
            
            if not last_alert:
                conn.execute("INSERT INTO events_log (camera_id, type, message) VALUES (?,?,?)",
                             (cam_id, alert['type'], alert['msg']))
                print(f"   🚨 ALERT [{branch}]: {alert['msg']}")

        conn.commit()

    except Exception as e:
        print(f"Error thread {branch}: {e}")
    finally:
        conn.close()

def patrol_all_cameras():
    # Sama seperti Engine 1 lama
    conn = get_db_connection()
    cameras = conn.execute("SELECT * FROM cameras WHERE is_active=1").fetchall()
    conn.close()
    
    threads = []
    for cam in cameras:
        t = threading.Thread(target=process_one_camera, args=(cam,))
        t.start()
        threads.append(t)
    for t in threads: t.join()

if __name__ == "__main__":
    print(">>> SOTO CLOUD SUPER-SCHEDULER V6.0 <<<")
    schedule.every(5).seconds.do(patrol_all_cameras)
    while True:
        schedule.run_pending()
        time.sleep(1)