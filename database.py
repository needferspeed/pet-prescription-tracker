import sqlite3
from contextlib import contextmanager

DB_NAME = "pet_tracker.db"


def get_connection():
    """Open a new SQLite connection with row access by column name."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    # Foreign keys are off by default in SQLite; without this, the
    # cascading deletes in delete_pet() would silently leave orphaned rows.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    """Yield a connection and guarantee it's closed even if a query raises.

    Every model function used to do `conn = get_connection()` ... `conn.close()`
    by hand, which leaked the connection if any statement in between raised
    an exception. Wrapping access in this context manager means the `finally`
    block always runs, so `with get_db() as conn:` is the pattern used
    throughout models.py.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


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

    # Indexes on every foreign key used in a WHERE or JOIN clause elsewhere
    # in the app (see get_pets_for_owner, get_prescriptions_for_pet, the
    # alerts dashboard query in app.py, and the refill/dispense checks in
    # alerts.py). SQLite doesn't index FK columns automatically, and without
    # these every such lookup does a full table scan as data grows.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pets_owner_id ON pets(owner_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_prescriptions_pet_id ON prescriptions(pet_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_prescriptions_medication_id ON prescriptions(medication_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dosage_logs_prescription_id ON dosage_logs(prescription_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_alerts_prescription_id ON alerts(prescription_id)")

    conn.commit()
    conn.close()
