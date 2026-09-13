from database import get_db
from datetime import datetime, timedelta


def _has_unresolved_alert(conn, prescription_id, alert_type):
    # Prevents duplicate alerts from piling up every time these checks run
    # (they run on every dashboard load) - only create a new one if the
    # previous alert of this type for this prescription was resolved.
    row = conn.execute(
        """SELECT id FROM alerts
           WHERE prescription_id = ? AND alert_type = ? AND resolved = 0""",
        (prescription_id, alert_type)
    ).fetchone()
    return row is not None


def check_refill_warnings():
    with get_db() as conn:
        prescriptions = conn.execute("""
            SELECT prescriptions.*, medications.name AS medication_name
            FROM prescriptions
            JOIN medications ON prescriptions.medication_id = medications.id
        """).fetchall()

        for p in prescriptions:
            # supply_on_hand is decremented on every dose (see log_dose in
            # models.py), so comparing it to refill_threshold here always
            # reflects the true remaining supply without a separate calculation.
            if p["supply_on_hand"] <= p["refill_threshold"]:
                if not _has_unresolved_alert(conn, p["id"], "refill_warning"):
                    _create_alert(conn, p["id"], "refill_warning",
                                  f"{p['medication_name']} refill needed: supply at {p['supply_on_hand']}")
        conn.commit()


def check_dispense_reminders():
    with get_db() as conn:
        prescriptions = conn.execute("""
            SELECT prescriptions.*, medications.name AS medication_name
            FROM prescriptions
            JOIN medications ON prescriptions.medication_id = medications.id
        """).fetchall()

        for p in prescriptions:
            last_dose = conn.execute(
                "SELECT MAX(given_at) as last FROM dosage_logs WHERE prescription_id = ?",
                (p["id"],)
            ).fetchone()

            # A dose is "due" once frequency_hours has elapsed since the last
            # logged dose. If no dose has ever been logged, there's nothing to
            # measure from yet, so we skip rather than firing a false reminder.
            if last_dose["last"]:
                last_time = datetime.fromisoformat(last_dose["last"])
                due_time = last_time + timedelta(hours=p["frequency_hours"])
                if datetime.now() >= due_time:
                    if not _has_unresolved_alert(conn, p["id"], "dispense_reminder"):
                        _create_alert(conn, p["id"], "dispense_reminder",
                                      f"{p['medication_name']} dose is due")
        conn.commit()


def _create_alert(conn, prescription_id, alert_type, message):
    conn.execute(
        "INSERT INTO alerts (prescription_id, alert_type, message, created_at) VALUES (?, ?, ?, ?)",
        (prescription_id, alert_type, message, datetime.now().isoformat())
    )
