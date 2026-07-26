from database import get_connection
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# ---------- Owners / Accounts ----------

def create_owner(owner_name, email, password):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    password_hash = generate_password_hash(password)
    cur.execute(
        "INSERT INTO owners (owner_name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (owner_name, email, password_hash, now)
    )
    conn.commit()
    owner_id = cur.lastrowid
    conn.close()
    return owner_id

def get_owner(owner_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM owners WHERE id = ?", (owner_id,)).fetchone()
    conn.close()
    return row

def authenticate_owner(email, password):
    conn = get_connection()
    row = conn.execute("SELECT * FROM owners WHERE email = ?", (email,)).fetchone()
    conn.close()
    if row and check_password_hash(row["password_hash"], password):
        return row
    return None

def email_exists(email):
    conn = get_connection()
    row = conn.execute("SELECT id FROM owners WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row is not None

# ---------- Pets ----------

def add_pet(owner_id, name, species, breed, weight_lbs, age, medical_issues,
            photo_filename=None, vet_name=None, vet_contact=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO pets (owner_id, name, species, breed, weight_lbs, age,
                              medical_issues, photo_filename, vet_name, vet_contact)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (owner_id, name, species, breed, weight_lbs, age, medical_issues,
         photo_filename, vet_name, vet_contact)
    )
    conn.commit()
    pet_id = cur.lastrowid
    conn.close()
    return pet_id

def get_pets_for_owner(owner_id):
    conn = get_connection()
    rows = conn.execute("SELECT * FROM pets WHERE owner_id = ?", (owner_id,)).fetchall()
    conn.close()
    return rows

def get_pet(pet_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM pets WHERE id = ?", (pet_id,)).fetchone()
    conn.close()
    return row

def search_pets(owner_id, query):
    conn = get_connection()
    like_query = f"%{query}%"
    rows = conn.execute(
        """SELECT * FROM pets
           WHERE owner_id = ? AND (name LIKE ? OR CAST(id AS TEXT) = ?)""",
        (owner_id, like_query, query)
    ).fetchall()
    conn.close()
    return rows

def update_pet_photo(pet_id, photo_filename):
    conn = get_connection()
    conn.execute(
        "UPDATE pets SET photo_filename = ? WHERE id = ?",
        (photo_filename, pet_id)
    )
    conn.commit()
    conn.close()

# ---------- Medications ----------

def add_medication(name, unit):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO medications (name, unit) VALUES (?, ?)",
        (name, unit)
    )
    conn.commit()
    med_id = cur.lastrowid
    conn.close()
    return med_id

# ---------- Prescriptions ----------

def add_prescription(pet_id, medication_id, dosage_amount, frequency_hours,
                      supply_on_hand, refill_threshold, start_date):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO prescriptions
           (pet_id, medication_id, dosage_amount, frequency_hours, supply_on_hand, refill_threshold, start_date)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (pet_id, medication_id, dosage_amount, frequency_hours, supply_on_hand, refill_threshold, start_date)
    )
    conn.commit()
    conn.close()

def get_prescriptions_for_pet(pet_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM prescriptions WHERE pet_id = ?", (pet_id,)
    ).fetchall()
    conn.close()
    return rows

def get_prescription(prescription_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM prescriptions WHERE id = ?", (prescription_id,)
    ).fetchone()
    conn.close()
    return row

def refill_prescription(prescription_id, new_supply_amount):
    conn = get_connection()
    conn.execute(
        "UPDATE prescriptions SET supply_on_hand = ? WHERE id = ?",
        (new_supply_amount, prescription_id)
    )
    conn.commit()
    conn.close()

# ---------- Dosage Logs ----------

def log_dose(prescription_id, amount_given):
    conn = get_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO dosage_logs (prescription_id, given_at, amount_given) VALUES (?, ?, ?)",
        (prescription_id, now, amount_given)
    )
    cur.execute(
        "UPDATE prescriptions SET supply_on_hand = supply_on_hand - ? WHERE id = ?",
        (amount_given, prescription_id)
    )
    conn.commit()
    conn.close()