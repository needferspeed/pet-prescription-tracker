from database import get_db
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# ---------- Owners / Accounts ----------

def create_owner(owner_name, email, password):
    now = datetime.now().isoformat()
    # Never store the raw password - only the salted hash. generate_password_hash
    # uses scrypt by default (werkzeug 2.3+), which is deliberately slow to
    # resist brute-force attacks even if the database is ever leaked.
    password_hash = generate_password_hash(password)
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO owners (owner_name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (owner_name, email, password_hash, now)
        )
        conn.commit()
        return cur.lastrowid


def get_owner(owner_id):
    with get_db() as conn:
        return conn.execute("SELECT * FROM owners WHERE id = ?", (owner_id,)).fetchone()


def authenticate_owner(email, password):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM owners WHERE email = ?", (email,)).fetchone()
    # check_password_hash re-derives the hash from the supplied password and
    # compares digests in constant time, so this is safe against timing attacks.
    if row and check_password_hash(row["password_hash"], password):
        return row
    return None


def email_exists(email):
    with get_db() as conn:
        row = conn.execute("SELECT id FROM owners WHERE email = ?", (email,)).fetchone()
    return row is not None

# ---------- Pets ----------

def add_pet(owner_id, name, species, breed, weight_lbs, age, medical_issues,
            photo_filename=None, vet_name=None, vet_contact=None):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO pets (owner_id, name, species, breed, weight_lbs, age,
                                  medical_issues, photo_filename, vet_name, vet_contact)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (owner_id, name, species, breed, weight_lbs, age, medical_issues,
             photo_filename, vet_name, vet_contact)
        )
        conn.commit()
        return cur.lastrowid


def get_pets_for_owner(owner_id):
    with get_db() as conn:
        return conn.execute("SELECT * FROM pets WHERE owner_id = ?", (owner_id,)).fetchall()


def get_pet(pet_id):
    with get_db() as conn:
        return conn.execute("SELECT * FROM pets WHERE id = ?", (pet_id,)).fetchone()


def search_pets(owner_id, query):
    # owner_id is always included in the WHERE clause so a search can never
    # surface another owner's pets, regardless of what the query string is.
    with get_db() as conn:
        like_query = f"%{query}%"
        return conn.execute(
            """SELECT * FROM pets
               WHERE owner_id = ? AND (name LIKE ? OR CAST(id AS TEXT) = ?)""",
            (owner_id, like_query, query)
        ).fetchall()


def update_pet_photo(pet_id, photo_filename):
    with get_db() as conn:
        conn.execute(
            "UPDATE pets SET photo_filename = ? WHERE id = ?",
            (photo_filename, pet_id)
        )
        conn.commit()


def update_pet(pet_id, name, species, breed, weight_lbs, age, medical_issues,
                vet_name=None, vet_contact=None):
    with get_db() as conn:
        conn.execute(
            """UPDATE pets
               SET name = ?, species = ?, breed = ?, weight_lbs = ?, age = ?,
                   medical_issues = ?, vet_name = ?, vet_contact = ?
               WHERE id = ?""",
            (name, species, breed, weight_lbs, age, medical_issues,
             vet_name, vet_contact, pet_id)
        )
        conn.commit()


def delete_pet(pet_id):
    with get_db() as conn:
        cur = conn.cursor()
        # Prescriptions reference pets via FK, and dosage_logs/alerts reference
        # prescriptions, so children must go first or the FK constraint will block this.
        prescription_ids = [
            row["id"] for row in
            cur.execute("SELECT id FROM prescriptions WHERE pet_id = ?", (pet_id,)).fetchall()
        ]
        for pid in prescription_ids:
            cur.execute("DELETE FROM alerts WHERE prescription_id = ?", (pid,))
            cur.execute("DELETE FROM dosage_logs WHERE prescription_id = ?", (pid,))
        cur.execute("DELETE FROM prescriptions WHERE pet_id = ?", (pet_id,))
        cur.execute("DELETE FROM pets WHERE id = ?", (pet_id,))
        conn.commit()

# ---------- Medications ----------

def add_medication(name, unit):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO medications (name, unit) VALUES (?, ?)",
            (name, unit)
        )
        conn.commit()
        return cur.lastrowid

# ---------- Prescriptions ----------

def add_prescription(pet_id, medication_id, dosage_amount, frequency_hours,
                      supply_on_hand, refill_threshold, start_date):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO prescriptions
               (pet_id, medication_id, dosage_amount, frequency_hours, supply_on_hand, refill_threshold, start_date)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pet_id, medication_id, dosage_amount, frequency_hours, supply_on_hand, refill_threshold, start_date)
        )
        conn.commit()


def get_prescriptions_for_pet(pet_id):
    with get_db() as conn:
        return conn.execute("""
            SELECT prescriptions.*, medications.name AS medication_name, medications.unit AS medication_unit
            FROM prescriptions
            JOIN medications ON prescriptions.medication_id = medications.id
            WHERE prescriptions.pet_id = ?
        """, (pet_id,)).fetchall()


def get_prescription(prescription_id):
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM prescriptions WHERE id = ?", (prescription_id,)
        ).fetchone()


def get_prescription_with_owner(prescription_id):
    """Fetch a prescription along with the owner_id of the pet it belongs to.

    Added so routes that only receive a prescription_id (give_dose, refill)
    can verify ownership in one query instead of trusting the ID blindly -
    without this, any logged-in user could log doses or refill supply on
    another owner's prescriptions just by guessing the ID (an IDOR bug).
    """
    with get_db() as conn:
        return conn.execute("""
            SELECT prescriptions.*, pets.owner_id AS owner_id
            FROM prescriptions
            JOIN pets ON prescriptions.pet_id = pets.id
            WHERE prescriptions.id = ?
        """, (prescription_id,)).fetchone()


def refill_prescription(prescription_id, new_supply_amount):
    with get_db() as conn:
        conn.execute(
            "UPDATE prescriptions SET supply_on_hand = ? WHERE id = ?",
            (new_supply_amount, prescription_id)
        )
        conn.commit()


def update_prescription(prescription_id, dosage_amount=None, frequency_hours=None,
                         supply_on_hand=None, refill_threshold=None, start_date=None):
    """Partial update for the REST API's PATCH endpoint.

    Only fields that were actually supplied (not None) are updated, using
    COALESCE so a client can PATCH a single field (e.g. just supply_on_hand
    for a refill) without needing to resend the whole prescription.
    """
    with get_db() as conn:
        conn.execute(
            """UPDATE prescriptions
               SET dosage_amount = COALESCE(?, dosage_amount),
                   frequency_hours = COALESCE(?, frequency_hours),
                   supply_on_hand = COALESCE(?, supply_on_hand),
                   refill_threshold = COALESCE(?, refill_threshold),
                   start_date = COALESCE(?, start_date)
               WHERE id = ?""",
            (dosage_amount, frequency_hours, supply_on_hand, refill_threshold,
             start_date, prescription_id)
        )
        conn.commit()


def delete_prescription(prescription_id):
    """Delete a prescription and its dependent rows (dosage_logs, alerts).

    Mirrors the child-before-parent ordering used in delete_pet() - the FK
    constraints would otherwise reject deleting a prescription that still
    has dose history or alerts pointing at it.
    """
    with get_db() as conn:
        conn.execute("DELETE FROM alerts WHERE prescription_id = ?", (prescription_id,))
        conn.execute("DELETE FROM dosage_logs WHERE prescription_id = ?", (prescription_id,))
        conn.execute("DELETE FROM prescriptions WHERE id = ?", (prescription_id,))
        conn.commit()

# ---------- Dosage Logs ----------

def log_dose(prescription_id, amount_given):
    with get_db() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO dosage_logs (prescription_id, given_at, amount_given) VALUES (?, ?, ?)",
            (prescription_id, now, amount_given)
        )
        # Decrementing supply here (rather than recomputing it from the log
        # elsewhere) keeps supply_on_hand as a single source of truth that
        # the refill-warning check in alerts.py can read directly.
        conn.execute(
            "UPDATE prescriptions SET supply_on_hand = supply_on_hand - ? WHERE id = ?",
            (amount_given, prescription_id)
        )
        conn.commit()


def get_alerts_for_owner(owner_id):
    """Fetch every unresolved alert for an owner's pets, with the pet name,
    vet info, and medication name joined in for display.

    Pulled out of app.py's index() route so the JSON API can return the
    exact same alert data as the dashboard without duplicating this query.
    """
    with get_db() as conn:
        return conn.execute("""
            SELECT alerts.*, pets.name as pet_name, pets.id as pet_id,
                   pets.vet_name as vet_name, pets.vet_contact as vet_contact,
                   medications.name as medication_name
            FROM alerts
            JOIN prescriptions ON alerts.prescription_id = prescriptions.id
            JOIN pets ON prescriptions.pet_id = pets.id
            JOIN medications ON prescriptions.medication_id = medications.id
            WHERE alerts.resolved = 0 AND pets.owner_id = ?
        """, (owner_id,)).fetchall()


def get_alert_with_owner(alert_id):
    """Fetch an alert along with the owner_id of the pet it belongs to, for
    the API's ownership check on PATCH /api/alerts/<id>.
    """
    with get_db() as conn:
        return conn.execute("""
            SELECT alerts.*, pets.owner_id AS owner_id
            FROM alerts
            JOIN prescriptions ON alerts.prescription_id = prescriptions.id
            JOIN pets ON prescriptions.pet_id = pets.id
            WHERE alerts.id = ?
        """, (alert_id,)).fetchone()


def resolve_alert(alert_id):
    with get_db() as conn:
        conn.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (alert_id,))
        conn.commit()
