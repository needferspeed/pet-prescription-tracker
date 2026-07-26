from database import get_connection
from datetime import datetime, timedelta

def _has_unresolved_alert(conn, prescription_id, alert_type):
    row = conn.execute(
        """SELECT id FROM alerts
           WHERE prescription_id = ? AND alert_type = ? AND resolved = 0""",
        (prescription_id, alert_type)
    ).fetchone()
    return row is not None

def check_refill_warnings():
    conn = get_connection()
    prescriptions = conn.execute("SELECT * FROM prescriptions").fetchall()
    for p in prescriptions:
        if p["supply_on_hand"] <= p["refill_threshold"]:
            if not _has_unresolved_alert(conn, p["id"], "refill_warning"):
                _create_alert(conn, p["id"], "refill_warning",
                              f"Refill needed: supply at {p['supply_on_hand']}")
    conn.commit()
    conn.close()

def check_dispense_reminders():
    conn = get_connection()
    prescriptions = conn.execute("SELECT * FROM prescriptions").fetchall()
    for p in prescriptions:
        last_dose = conn.execute(
            "SELECT MAX(given_at) as last FROM dosage_logs WHERE prescription_id = ?",
            (p["id"],)
        ).fetchone()
        if last_dose["last"]:
            last_time = datetime.fromisoformat(last_dose["last"])
            due_time = last_time + timedelta(hours=p["frequency_hours"])
            if datetime.now() >= due_time:
                if not _has_unresolved_alert(conn, p["id"], "dispense_reminder"):
                    _create_alert(conn, p["id"], "dispense_reminder", "Dose is due")
    conn.commit()
    conn.close()

def _create_alert(conn, prescription_id, alert_type, message):
    conn.execute(
        "INSERT INTO alerts (prescription_id, alert_type, message, created_at) VALUES (?, ?, ?, ?)",
        (prescription_id, alert_type, message, datetime.now().isoformat())
    )