import sqlite3

DB_NAME = "pet_tracker.db"

def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            species TEXT,
            breed TEXT,
            weight_lbs REAL,
            age INTEGER,
            medical_issues TEXT,
            photo_filename TEXT,
            vet_name TEXT,
            vet_contact TEXT,
            FOREIGN KEY (owner_id) REFERENCES owners(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS medications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            unit TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS prescriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pet_id INTEGER NOT NULL,
            medication_id INTEGER NOT NULL,
            dosage_amount REAL NOT NULL,
            frequency_hours INTEGER NOT NULL,
            supply_on_hand REAL NOT NULL,
            refill_threshold REAL NOT NULL,
            start_date TEXT NOT NULL,
            FOREIGN KEY (pet_id) REFERENCES pets(id),
            FOREIGN KEY (medication_id) REFERENCES medications(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS dosage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prescription_id INTEGER NOT NULL,
            given_at TEXT NOT NULL,
            amount_given REAL NOT NULL,
            FOREIGN KEY (prescription_id) REFERENCES prescriptions(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prescription_id INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved INTEGER DEFAULT 0,
            FOREIGN KEY (prescription_id) REFERENCES prescriptions(id)
        )
    """)

    conn.commit()
    conn.close()