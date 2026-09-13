import os
import secrets
from flask import Flask, render_template, request, redirect, session, url_for, abort
from database import init_db, get_db
from models import (
    create_owner, get_owner, authenticate_owner, email_exists,
    add_pet, get_pets_for_owner, get_pet, search_pets, update_pet_photo,
    update_pet, delete_pet, resolve_alert, get_alerts_for_owner,
    add_medication, add_prescription, get_prescriptions_for_pet,
    get_prescription, get_prescription_with_owner, refill_prescription, log_dose
)
from alerts import check_refill_warnings, check_dispense_reminders
from validators import (
    parse_optional_float, parse_optional_int, parse_required_float, parse_required_int,
    save_photo as _save_photo,
)
from api import api as api_blueprint

app = Flask(__name__)

# The secret key signs session cookies - anyone who has it can forge a
# logged-in session for any user. It must never be hardcoded in source that
# ends up in version control. In production, set the SECRET_KEY environment
# variable; the random fallback below only exists so the app still runs
# locally without extra setup (a new random key each restart just means
# existing sessions get logged out, which is an acceptable tradeoff for dev).
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

UPLOAD_FOLDER = os.path.join("static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
# Caps request size so a malicious or accidental huge upload can't exhaust
# server memory/disk before secure_filename or the extension check even runs.
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

init_db()

# The JSON REST API lives in its own blueprint (api.py) so it can grow
# independently of these HTML routes while sharing the same models.
app.register_blueprint(api_blueprint)


# ---------- CSRF protection ----------
# Flask-WTF isn't in requirements.txt, so this is a minimal hand-rolled
# CSRF check: a random token is stored in the session and must be echoed
# back by every POST form. Without this, a malicious external site could
# trick a logged-in user's browser into submitting one of our forms
# (e.g. deleting a pet) just by having them visit a page with a hidden
# auto-submitting form pointed at our routes.
#
# /api/* is exempt: those routes take JSON bodies, and a plain HTML <form>
# (the classic CSRF delivery mechanism) cannot send a JSON content type
# cross-site, so the attack this check defends against doesn't apply there.

def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = get_csrf_token


@app.before_request
def enforce_csrf():
    if request.method == "POST" and not request.path.startswith("/api/"):
        submitted = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        # compare_digest avoids leaking timing information about how much
        # of the token matched, same reasoning as password hash comparison.
        if not expected or not secrets.compare_digest(submitted, expected):
            abort(400, description="Missing or invalid CSRF token.")


def save_photo(file_storage):
    return _save_photo(file_storage, app.config["UPLOAD_FOLDER"])


def owner_owns_pet(pet, owner_id):
    return pet is not None and pet["owner_id"] == owner_id


def require_login():
    """Return the logged-in owner_id, or None if not logged in."""
    return session.get("owner_id")


# ---------- Account setup (signup) ----------

@app.route("/setup", methods=["GET", "POST"])
def setup():
    if request.method == "POST":
        owner_name = request.form["owner_name"]
        email = request.form["email"]
        password = request.form["password"]

        if email_exists(email):
            return render_template("setup.html", error="An account with that email already exists. Please log in instead.")

        owner_id = create_owner(owner_name, email, password)
        session["owner_id"] = owner_id
        return render_template("setup.html", success=True, owner_name=owner_name)

    return render_template("setup.html")

# ---------- Login ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        owner = authenticate_owner(email, password)
        if owner:
            session["owner_id"] = owner["id"]
            return redirect(url_for("index"))
        return render_template("login.html", error="Incorrect email or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- Home / dashboard ----------

@app.route("/")
def index():
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    check_refill_warnings()
    check_dispense_reminders()

    pets = get_pets_for_owner(owner_id)
    alerts = get_alerts_for_owner(owner_id)

    return render_template("index.html", pets=pets, alerts=alerts)

# ---------- Search ----------

@app.route("/search")
def search():
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))
    query = request.args.get("q", "")
    results = search_pets(owner_id, query) if query else []
    return render_template("search.html", results=results, query=query)

# ---------- Add pet ----------

@app.route("/add_pet", methods=["GET", "POST"])
def add_pet_route():
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        errors = []

        name = request.form["name"]
        species = request.form["species"]
        breed = request.form["breed"]
        weight_lbs = parse_optional_float(request.form.get("weight_lbs"), "Weight", errors)
        age = parse_optional_int(request.form.get("age"), "Age", errors)
        medical_issues = request.form["medical_issues"]
        vet_name = request.form.get("vet_name")
        vet_contact = request.form.get("vet_contact")

        # The optional prescription block only needs to validate if the user
        # actually started filling it in (indicated by a medication name).
        med_name = request.form.get("med_name")
        dosage_amount = frequency_hours = supply_on_hand = refill_threshold = None
        if med_name:
            dosage_amount = parse_required_float(request.form.get("dosage_amount"), "Dosage amount", errors)
            frequency_hours = parse_required_int(request.form.get("frequency_hours"), "Frequency (hours)", errors)
            supply_on_hand = parse_required_float(request.form.get("supply_on_hand"), "Supply on hand", errors)
            refill_threshold = parse_required_float(request.form.get("refill_threshold"), "Refill threshold", errors)

        photo_filename = None
        try:
            photo_filename = save_photo(request.files.get("photo"))
        except ValueError as e:
            errors.append(str(e))

        if errors:
            return render_template("add_pet.html", error=" ".join(errors))

        pet_id = add_pet(owner_id, name, species, breed, weight_lbs, age,
                          medical_issues, photo_filename, vet_name, vet_contact)

        if med_name:
            med_unit = request.form.get("med_unit", "unit")
            start_date = request.form.get("start_date", "")
            medication_id = add_medication(med_name, med_unit)
            add_prescription(pet_id, medication_id, dosage_amount, frequency_hours,
                              supply_on_hand, refill_threshold, start_date)

        return redirect(url_for("pet_detail", pet_id=pet_id))

    return render_template("add_pet.html")

# ---------- Pet detail ----------

@app.route("/pet/<int:pet_id>")
def pet_detail(pet_id):
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    pet = get_pet(pet_id)
    # Without this check, any logged-in user could view any other owner's
    # pet (including their vet contact info) just by guessing the pet_id.
    if not owner_owns_pet(pet, owner_id):
        return redirect(url_for("index"))

    prescriptions = get_prescriptions_for_pet(pet_id)
    return render_template("pet_detail.html", pet=pet, prescriptions=prescriptions)

@app.route("/pet/<int:pet_id>/photo", methods=["POST"])
def upload_photo(pet_id):
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    pet = get_pet(pet_id)
    if not owner_owns_pet(pet, owner_id):
        return redirect(url_for("index"))

    try:
        photo_filename = save_photo(request.files.get("photo"))
    except ValueError:
        # Invalid file type - silently ignore and return to the pet page
        # rather than crash; the photo upload form has no error display slot.
        return redirect(url_for("pet_detail", pet_id=pet_id))

    if photo_filename:
        update_pet_photo(pet_id, photo_filename)
    return redirect(url_for("pet_detail", pet_id=pet_id))

@app.route("/pet/<int:pet_id>/edit", methods=["GET", "POST"])
def edit_pet(pet_id):
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    pet = get_pet(pet_id)
    if not owner_owns_pet(pet, owner_id):
        return redirect(url_for("index"))

    if request.method == "POST":
        errors = []

        name = request.form["name"]
        species = request.form["species"]
        breed = request.form["breed"]
        weight_lbs = parse_optional_float(request.form.get("weight_lbs"), "Weight", errors)
        age = parse_optional_int(request.form.get("age"), "Age", errors)
        medical_issues = request.form["medical_issues"]
        vet_name = request.form.get("vet_name")
        vet_contact = request.form.get("vet_contact")

        if errors:
            return render_template("edit_pet.html", pet=pet, error=" ".join(errors))

        update_pet(pet_id, name, species, breed, weight_lbs, age,
                   medical_issues, vet_name, vet_contact)
        return redirect(url_for("pet_detail", pet_id=pet_id))

    return render_template("edit_pet.html", pet=pet)

@app.route("/pet/<int:pet_id>/delete", methods=["POST"])
def delete_pet_route(pet_id):
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    pet = get_pet(pet_id)
    if not owner_owns_pet(pet, owner_id):
        return redirect(url_for("index"))

    delete_pet(pet_id)
    return redirect(url_for("index"))

# ---------- Dosage & refill ----------

@app.route("/dose/<int:prescription_id>", methods=["POST"])
def give_dose(prescription_id):
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    # get_prescription_with_owner joins through to the pet's owner so this
    # can be checked in one query, closing the same IDOR gap as pet_detail.
    prescription = get_prescription_with_owner(prescription_id)
    if not prescription or prescription["owner_id"] != owner_id:
        return redirect(url_for("index"))

    errors = []
    amount = parse_required_float(request.form.get("amount"), "Amount given", errors)
    if errors:
        # No error banner slot exists for this specific form in pet_detail.html
        # (unlike add_prescription's form on the same page), so an invalid
        # amount just redirects back silently rather than crashing. Known
        # limitation - a future pass could add a query-string flash message.
        return redirect(url_for("pet_detail", pet_id=prescription["pet_id"]))

    log_dose(prescription_id, amount)
    return redirect(url_for("pet_detail", pet_id=prescription["pet_id"]))

@app.route("/refill/<int:prescription_id>", methods=["POST"])
def refill(prescription_id):
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    prescription = get_prescription_with_owner(prescription_id)
    if not prescription or prescription["owner_id"] != owner_id:
        return redirect(url_for("index"))

    errors = []
    new_amount = parse_required_float(request.form.get("new_amount"), "New supply amount", errors)
    if errors:
        # Same tradeoff as give_dose above - no error banner slot for this
        # form, so we redirect silently rather than crash on bad input.
        return redirect(url_for("pet_detail", pet_id=prescription["pet_id"]))

    refill_prescription(prescription_id, new_amount)
    with get_db() as conn:
        conn.execute(
            "UPDATE alerts SET resolved = 1 WHERE prescription_id = ? AND alert_type = 'refill_warning'",
            (prescription_id,)
        )
        conn.commit()
    return redirect(url_for("pet_detail", pet_id=prescription["pet_id"]))

# ---------- Prescriptions & Alerts ----------

@app.route("/pet/<int:pet_id>/add_prescription", methods=["POST"])
def add_prescription_route(pet_id):
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    pet = get_pet(pet_id)
    if not owner_owns_pet(pet, owner_id):
        return redirect(url_for("index"))

    errors = []
    med_name = request.form["med_name"]
    med_unit = request.form.get("med_unit", "unit")
    dosage_amount = parse_required_float(request.form.get("dosage_amount"), "Dosage amount", errors)
    frequency_hours = parse_required_int(request.form.get("frequency_hours"), "Frequency (hours)", errors)
    supply_on_hand = parse_required_float(request.form.get("supply_on_hand"), "Supply on hand", errors)
    refill_threshold = parse_required_float(request.form.get("refill_threshold"), "Refill threshold", errors)
    start_date = request.form.get("start_date", "")

    if errors:
        prescriptions = get_prescriptions_for_pet(pet_id)
        return render_template("pet_detail.html", pet=pet, prescriptions=prescriptions, error=" ".join(errors))

    medication_id = add_medication(med_name, med_unit)
    add_prescription(pet_id, medication_id, dosage_amount, frequency_hours,
                      supply_on_hand, refill_threshold, start_date)

    return redirect(url_for("pet_detail", pet_id=pet_id))

@app.route("/alert/<int:alert_id>/dismiss", methods=["POST"])
def dismiss_alert(alert_id):
    owner_id = require_login()
    if not owner_id:
        return redirect(url_for("login"))

    with get_db() as conn:
        alert = conn.execute("""
            SELECT alerts.id
            FROM alerts
            JOIN prescriptions ON alerts.prescription_id = prescriptions.id
            JOIN pets ON prescriptions.pet_id = pets.id
            WHERE alerts.id = ? AND pets.owner_id = ?
        """, (alert_id, owner_id)).fetchone()

    if alert:
        resolve_alert(alert_id)
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)
