import sqlite3
from datetime import datetime

DB_NAME = "soto_cloud.db"

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    
    # 1. Tabel Master Cabang
    conn.execute('''CREATE TABLE IF NOT EXISTS branches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        address TEXT,
        phone TEXT,
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 2. Tabel User & Auth (Tetap dari Engine 1)
    conn.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT,
        branch_id INTEGER,
        FOREIGN KEY(branch_id) REFERENCES branches(id)
    )''')
    
    # 3. Tabel Kamera & Zona (Tetap dari Engine 1)
    conn.execute('''CREATE TABLE IF NOT EXISTS cameras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch_id INTEGER,
        branch_name TEXT,
        rtsp_url TEXT,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(branch_id) REFERENCES branches(id)
    )''')
    
    conn.execute('''CREATE TABLE IF NOT EXISTS zones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER,
        name TEXT,
        type TEXT, -- 'table', 'queue', 'refill', 'restricted'
        coords TEXT, -- JSON String
        FOREIGN KEY(camera_id) REFERENCES cameras(id)
    )''')

    # 3. Tabel Billing (Update Logic)
    conn.execute('''CREATE TABLE IF NOT EXISTS billing_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER,
        zone_name TEXT,
        item_name TEXT,
        qty INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # --- BARU: TABEL EVENTS (Dari Engine 2) ---
    # Menyimpan data 'long_queue', 'intruder', 'dirty_table'
    conn.execute('''CREATE TABLE IF NOT EXISTS events_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER,
        type TEXT, 
        message TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')

    # --- BARU: TABEL STAFF (Dari Engine 2 InsightFace) ---
    # Menyimpan log kehadiran staff di area tertentu
    conn.execute('''CREATE TABLE IF NOT EXISTS staff_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER,
        staff_name TEXT,
        zone_name TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # --- BARU: TABEL TABLE OCCUPANCY LOG (Tracking Durasi Meja Terisi) ---
    # Menyimpan log durasi meja terisi (start time, end time, duration)
    conn.execute('''CREATE TABLE IF NOT EXISTS table_occupancy_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER,
        zone_name TEXT,
        start_time DATETIME NOT NULL,
        end_time DATETIME,
        duration_seconds INTEGER,
        person_count INTEGER DEFAULT 1,
        status TEXT DEFAULT 'completed',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # --- BARU: TABEL QUEUE LOG (Tracking Durasi Antrian Penuh) ---
    # Menyimpan log durasi antrian penuh (start time, end time, duration)
    conn.execute('''CREATE TABLE IF NOT EXISTS queue_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        camera_id INTEGER,
        zone_name TEXT,
        start_time DATETIME NOT NULL,
        end_time DATETIME,
        duration_seconds INTEGER,
        max_queue_count INTEGER,
        status TEXT DEFAULT 'completed',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 4. Tabel Master Cabang (Baru)
    conn.execute('''CREATE TABLE IF NOT EXISTS branches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        address TEXT,
        phone TEXT,
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Update tabel cameras untuk menambahkan branch_id jika belum ada
    cursor = conn.execute("PRAGMA table_info(cameras)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'branch_id' not in columns:
        try:
            conn.execute("ALTER TABLE cameras ADD COLUMN branch_id INTEGER")
        except:
            pass  # Kolom mungkin sudah ada
    
    conn.commit()
    conn.close()
    print("✅ Database initialized with V6.0 Schema (Merged + Branches)")