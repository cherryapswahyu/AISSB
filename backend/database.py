import sqlite3
from datetime import datetime, timezone, timedelta

DB_NAME = "soto_cloud.db"

# Timezone WIB (UTC+7)
WIB_TZ = timezone(timedelta(hours=7))

def get_wib_datetime():
    """
    Mendapatkan waktu saat ini dalam timezone WIB (UTC+7)
    Returns: string format 'YYYY-MM-DD HH:MM:SS' dalam WIB
    """
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(WIB_TZ)
    return now_wib.strftime('%Y-%m-%d %H:%M:%S')

def get_wib_datetime_offset(days=0, seconds=0, minutes=0, hours=0):
    """
    Mendapatkan waktu dengan offset tertentu dalam timezone WIB (UTC+7)
    Args:
        days: offset dalam hari (bisa negatif)
        seconds: offset dalam detik (bisa negatif)
        minutes: offset dalam menit (bisa negatif)
        hours: offset dalam jam (bisa negatif)
    Returns: string format 'YYYY-MM-DD HH:MM:SS' dalam WIB
    """
    now_utc = datetime.now(timezone.utc)
    now_wib = now_utc.astimezone(WIB_TZ)
    offset_time = now_wib + timedelta(days=days, seconds=seconds, minutes=minutes, hours=hours)
    return offset_time.strftime('%Y-%m-%d %H:%M:%S')

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
        type TEXT, -- 'table', 'kasir', 'gorengan', 'queue', 'dapur'
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
    
    # --- BARU: TABEL CUSTOMER LOG (Tracking Pengunjung GLOBAL) ---
    # Menyimpan history pengunjung untuk membedakan lama vs baru (GLOBAL, tidak terpaut zone)
    conn.execute('''CREATE TABLE IF NOT EXISTS customer_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        face_embedding_hash TEXT NOT NULL UNIQUE,
        first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
        visit_count INTEGER DEFAULT 1,
        customer_type TEXT DEFAULT 'new',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Migrasi: Tambahkan kolom camera_id dan branch_id jika belum ada (untuk database existing)
    try:
        cursor = conn.execute("PRAGMA table_info(customer_log)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'camera_id' not in columns:
            conn.execute("ALTER TABLE customer_log ADD COLUMN camera_id INTEGER")
        if 'branch_id' not in columns:
            conn.execute("ALTER TABLE customer_log ADD COLUMN branch_id INTEGER")
        conn.commit()
    except Exception as e:
        print(f"Note: Migration for customer_log columns: {e}")
    
    # Buat index setelah kolom sudah ada
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_customer_hash 
                    ON customer_log(face_embedding_hash)''')
    
    conn.execute('''CREATE INDEX IF NOT EXISTS idx_customer_last_seen 
                    ON customer_log(last_seen)''')
    
    # Hanya buat index jika kolom sudah ada
    try:
        cursor = conn.execute("PRAGMA table_info(customer_log)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'camera_id' in columns:
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_customer_camera_id 
                            ON customer_log(camera_id)''')
        if 'branch_id' in columns:
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_customer_branch_id 
                            ON customer_log(branch_id)''')
    except Exception as e:
        print(f"Note: Error creating indexes: {e}")
    
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