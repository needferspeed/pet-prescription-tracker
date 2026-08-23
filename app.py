import os
from flask import Flask, render_template, request, redirect, session, url_for
from werkzeug.utils import secure_filename
from database import init_db, get_connection
from models import (
    create_owner, get_owner, authenticate_owner, email_exists,
    add_pet, get_pets_for_owner, get_pet, search_pets, update_pet_photo,
    update_pet, delete_pet, resolve_alert,
    add_medication, add_prescription, get_prescriptions_for_pet,
    get_prescription, refill_prescription, log_dose
)
from alerts import check_refill_warnings, check_dispense_reminders

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-this-later"
UPLOAD_FOLDER = os.path.join("static", "uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

init_db()

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
    owner_id = session.get("owner_id")
    if not owner_id:
        return redirect(url_for("login"))

    check_refill_warnings()
    check_dispense_reminders()

    pets = get_pets_for_owner(owner_id)
    conn = get_connection()
    alerts = conn.execute("""
        SELECT alerts.*, pets.name as pet_name, pets.vet_name as vet_name,
               pets.vet_contact as vet_contact, medications.name as medication_name
        FROM alerts
        JOIN prescriptions ON alerts.prescription_id = prescriptions.id
        JOIN pets ON prescriptions.pet_id = pets.id
        JOIN medications ON prescriptions.medication_id = medications.id
        WHERE alerts.resolved = 0 AND pets.owner_id = ?
    """, (owner_id,)).fetchall()
    conn.close()

    return render_template("index.html", pets=pets, alerts=alerts)

# ---------- Search ----------

@app.route("/search")
def search():
    owner_id = session.get("owner_id")
    if not owner_id:
        return redirect(url_for("login"))
    query = request.args.get("q", "")
    results = search_pets(owner_id, query) if query else []
    return render_template("search.html", results=results, query=query)

# ---------- Add pet ----------

@app.route("/add_pet", methods=["GET", "POST"])
def add_pet_route():
    owner_id = session.get("owner_id")
    if not owner_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form["name"]
        species = request.form["species"]
        breed = request.form["breed"]
        weight_lbs = request.form["weight_lbs"]
        age = request.form["age"]
        medical_issues = request.form["medical_issues"]
        vet_name = request.form.get("vet_name")
        vet_contact = request.form.get("vet_contact")

        photo_filename = None
        photo = request.files.get("photo")
        if photo and photo.filename:
            photo_filename = secure_filename(photo.filename)
            photo.save(os.path.join(app.config["UPLOAD_FOLDER"], photo_filename))

        pet_id = add_pet(owner_id, name, species, breed, weight_lbs, age,
                          medical_issues, photo_filename, vet_name, vet_contact)

        med_name = request.form.get("med_name")
        if med_name:
            med_unit = request.form.get("med_unit", "unit")
            dosage_amount = request.form.get("dosage_amount", 0)
            frequency_hours = request.form.get("frequency_hours", 24)
            supply_on_hand = request.form.get("supply_on_hand", 0)
            refill_threshold = request.form.get("refill_threshold", 0)
            start_date = request.form.get("start_date", "")

            medication_id = add_medication(med_name, med_unit)
            add_prescription(pet_id, medication_id, dosage_amount, frequency_hours,
                              supply_on_hand, refill_threshold, start_date)

        return redirect(url_for("pet_detail", pet_id=pet_id))

    return render_template("add_pet.html")

# ---------- Pet detail ----------

@app.route("/pet/<int:pet_id>")
def pet_detail(pet_id):
    pet = get_pet(pet_id)
    prescriptions = get_prescriptions_for_pet(pet_id)
    return render_template("pet_detail.html", pet=pet, prescriptions=prescriptions)

@app.route("/pet/<int:pet_id>/photo", methods=["POST"])
def upload_photo(pet_id):
    photo = request.files.get("photo")
    if photo and photo.filename:
        photo_filename = secure_filename(photo.filename)
        photo.save(os.path.join(app.config["UPLOAD_FOLDER"], photo_filename))
        update_pet_photo(pet_id, photo_filename)
    return redirect(url_for("pet_detail", pet_id=pet_id))

@app.route("/pet/<int:pet_id>/edit", methods=["GET", "POST"])
def edit_pet(pet_id):
    owner_id = session.get("owner_id")
    if not owner_id:
        return redirect(url_for("login"))

    pet = get_pet(pet_id)
    if not pet or pet["owner_id"] != owner_id:
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form["name"]
        species = request.form["species"]
        breed = request.form["breed"]
        weight_lbs = request.form["weight_lbs"]
        age = request.form["age"]
        medical_issues = request.form["medical_issues"]
        vet_name = request.form.get("vet_name")
        vet_contact = request.form.get("vet_contact")

        update_pet(pet_id, name, species, breed, weight_lbs, age,
                   medical_issues, vet_name, vet_contact)
        return redirect(url_for("pet_detail", pet_id=pet_id))

    return render_template("edit_pet.html", pet=pet)

@app.route("/pet/<int:pet_id>/delete", methods=["POST"])
def delete_pet_route(pet_id):
    owner_id = session.get("owner_id")
    if not owner_id:
        return redirect(url_for("login"))

    pet = get_pet(pet_id)
    if not pet or pet["owner_id"] != owner_id:
        return redirect(url_for("index"))

    delete_pet(pet_id)
    return redirect(url_for("index"))

# ---------- Dosage & refill ----------

@app.route("/dose/<int:prescription_id>", methods=["POST"])
def give_dose(prescription_id):
    amount = float(request.form["amount"])
    log_dose(prescription_id, amount)
    return redirect(request.referrer)

@app.route("/refill/<int:prescription_id>", methods=["POST"])
def refill(prescription_id):
    new_amount = float(request.form["new_amount"])
    refill_prescription(prescription_id, new_amount)
    conn = get_connection()
    conn.execute(
        "UPDATE alerts SET resolved = 1 WHERE prescription_id = ? AND alert_type = 'refill_warning'",
        (prescription_id,)
    )
    conn.commit()
    conn.close()
    return redirect(request.referrer)

# ---------- Prescriptions & Alerts ----------

@app.route("/pet/<int:pet_id>/add_prescription", methods=["POST"])
def add_prescription_route(pet_id):
    owner_id = session.get("owner_id")
    if not owner_id:
        return redirect(url_for("login"))

    pet = get_pet(pet_id)
    if not pet or pet["owner_id"] != owner_id:
        return redirect(url_for("index"))

    med_name = request.form["med_name"]
    med_unit = request.form.get("med_unit", "unit")
    dosage_amount = request.form.get("dosage_amount", 0)
    frequency_hours = request.form.get("frequency_hours", 24)
    supply_on_hand = request.form.get("supply_on_hand", 0)
    refill_threshold = request.form.get("refill_threshold", 0)
    start_date = request.form.get("start_date", "")

    medication_id = add_medication(med_name, med_unit)
    add_prescription(pet_id, medication_id, dosage_amount, frequency_hours,
                      supply_on_hand, refill_threshold, start_date)

    return redirect(url_for("pet_detail", pet_id=pet_id))

@app.route("/alert/<int:alert_id>/dismiss", methods=["POST"])
def dismiss_alert(alert_id):
    owner_id = session.get("owner_id")
    if not owner_id:
        return redirect(url_for("login"))

    conn = get_connection()
    alert = conn.execute("""
        SELECT alerts.id
        FROM alerts
        JOIN prescriptions ON alerts.prescription_id = prescriptions.id
        JOIN pets ON prescriptions.pet_id = pets.id
        WHERE alerts.id = ? AND pets.owner_id = ?
    """, (alert_id, owner_id)).fetchone()
    conn.close()

    if alert:
        resolve_alert(alert_id)
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)

