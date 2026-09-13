"""JSON REST API for PetScript Manager.

Registered as a Blueprint under /api so it can grow independently of the
HTML routes in app.py, while sharing the same models, validation rules,
and session-based login/ownership checks.

Auth: the API relies on the same Flask session cookie as the HTML pages
(set at /login), rather than a separate token scheme. That keeps a single
login system for the whole app, which is appropriate for a project this
size - a public/mobile-client API would need real token auth instead.

CSRF: state-changing HTML forms are protected by the token check in
app.py's before_request hook. That check is skipped for /api/* routes
here because JSON request bodies can't be sent by a plain HTML <form> -
a browser can't set Content-Type: application/json on a cross-site form
submission - so the classic CSRF attack vector doesn't apply to a JSON API
the way it does to form posts.
"""

from flask import Blueprint, request, jsonify, session

from models import (
    get_pet, get_pets_for_owner, add_pet, update_pet, delete_pet,
    get_prescription_with_owner, get_prescriptions_for_pet, add_prescription,
    add_medication, update_prescription, delete_prescription, log_dose,
    get_alerts_for_owner, get_alert_with_owner, resolve_alert,
)
from validators import parse_optional_float, parse_optional_int, parse_required_float, parse_required_int

api = Blueprint("api", __name__, url_prefix="/api")


# ---------- Helpers ----------

def require_login_json():
    """Return the logged-in owner_id, or None. Callers turn None into a 401."""
    return session.get("owner_id")


def pet_to_dict(pet):
    return {
        "id": pet["id"],
        "owner_id": pet["owner_id"],
        "name": pet["name"],
        "species": pet["species"],
        "breed": pet["breed"],
        "weight_lbs": pet["weight_lbs"],
        "age": pet["age"],
        "medical_issues": pet["medical_issues"],
        "photo_filename": pet["photo_filename"],
        "vet_name": pet["vet_name"],
        "vet_contact": pet["vet_contact"],
    }


def prescription_to_dict(rx):
    d = {
        "id": rx["id"],
        "pet_id": rx["pet_id"],
        "medication_id": rx["medication_id"],
        "dosage_amount": rx["dosage_amount"],
        "frequency_hours": rx["frequency_hours"],
        "supply_on_hand": rx["supply_on_hand"],
        "refill_threshold": rx["refill_threshold"],
        "start_date": rx["start_date"],
    }
    # get_prescriptions_for_pet's JOIN adds these; get_prescription_with_owner
    # doesn't, so guard with keys() rather than assuming they're present.
    if "medication_name" in rx.keys():
        d["medication_name"] = rx["medication_name"]
        d["medication_unit"] = rx["medication_unit"]
    return d


def alert_to_dict(alert):
    return {
        "id": alert["id"],
        "prescription_id": alert["prescription_id"],
        "alert_type": alert["alert_type"],
        "message": alert["message"],
        "created_at": alert["created_at"],
        "resolved": bool(alert["resolved"]),
        "pet_id": alert["pet_id"],
        "pet_name": alert["pet_name"],
        "medication_name": alert["medication_name"],
        "vet_name": alert["vet_name"],
        "vet_contact": alert["vet_contact"],
    }


# ---------- Pets ----------

@api.route("/pets", methods=["GET"])
def list_pets():
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    pets = get_pets_for_owner(owner_id)
    return jsonify([pet_to_dict(p) for p in pets]), 200


@api.route("/pets/<int:pet_id>", methods=["GET"])
def get_pet_api(pet_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    pet = get_pet(pet_id)
    if not pet:
        return jsonify(error="Pet not found."), 404
    if pet["owner_id"] != owner_id:
        return jsonify(error="You do not have access to this pet."), 403
    return jsonify(pet_to_dict(pet)), 200


@api.route("/pets", methods=["POST"])
def create_pet_api():
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401

    body = request.get_json(silent=True) or {}
    errors = []
    name = body.get("name")
    if not name:
        errors.append("Name is required.")
    weight_lbs = parse_optional_float(body.get("weight_lbs"), "Weight", errors)
    age = parse_optional_int(body.get("age"), "Age", errors)
    if errors:
        return jsonify(errors=errors), 400

    pet_id = add_pet(
        owner_id, name, body.get("species"), body.get("breed"),
        weight_lbs, age, body.get("medical_issues"),
        photo_filename=None, vet_name=body.get("vet_name"), vet_contact=body.get("vet_contact")
    )
    return jsonify(pet_to_dict(get_pet(pet_id))), 201


@api.route("/pets/<int:pet_id>", methods=["PUT", "PATCH"])
def update_pet_api(pet_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    pet = get_pet(pet_id)
    if not pet:
        return jsonify(error="Pet not found."), 404
    if pet["owner_id"] != owner_id:
        return jsonify(error="You do not have access to this pet."), 403

    body = request.get_json(silent=True) or {}
    errors = []
    # PATCH semantics: fall back to the existing value for any field not
    # supplied, so a client can send just the changed fields.
    name = body.get("name", pet["name"])
    species = body.get("species", pet["species"])
    breed = body.get("breed", pet["breed"])
    weight_lbs = parse_optional_float(body.get("weight_lbs", pet["weight_lbs"]), "Weight", errors)
    age = parse_optional_int(body.get("age", pet["age"]), "Age", errors)
    medical_issues = body.get("medical_issues", pet["medical_issues"])
    vet_name = body.get("vet_name", pet["vet_name"])
    vet_contact = body.get("vet_contact", pet["vet_contact"])
    if errors:
        return jsonify(errors=errors), 400

    update_pet(pet_id, name, species, breed, weight_lbs, age,
               medical_issues, vet_name, vet_contact)
    return jsonify(pet_to_dict(get_pet(pet_id))), 200


@api.route("/pets/<int:pet_id>", methods=["DELETE"])
def delete_pet_api(pet_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    pet = get_pet(pet_id)
    if not pet:
        return jsonify(error="Pet not found."), 404
    if pet["owner_id"] != owner_id:
        return jsonify(error="You do not have access to this pet."), 403

    delete_pet(pet_id)
    return "", 204


# ---------- Prescriptions ----------

@api.route("/pets/<int:pet_id>/prescriptions", methods=["GET"])
def list_prescriptions_api(pet_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    pet = get_pet(pet_id)
    if not pet:
        return jsonify(error="Pet not found."), 404
    if pet["owner_id"] != owner_id:
        return jsonify(error="You do not have access to this pet."), 403

    rxs = get_prescriptions_for_pet(pet_id)
    return jsonify([prescription_to_dict(r) for r in rxs]), 200


@api.route("/pets/<int:pet_id>/prescriptions", methods=["POST"])
def create_prescription_api(pet_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    pet = get_pet(pet_id)
    if not pet:
        return jsonify(error="Pet not found."), 404
    if pet["owner_id"] != owner_id:
        return jsonify(error="You do not have access to this pet."), 403

    body = request.get_json(silent=True) or {}
    errors = []
    med_name = body.get("med_name")
    if not med_name:
        errors.append("Medication name is required.")
    med_unit = body.get("med_unit", "unit")
    dosage_amount = parse_required_float(body.get("dosage_amount"), "Dosage amount", errors)
    frequency_hours = parse_required_int(body.get("frequency_hours"), "Frequency (hours)", errors)
    supply_on_hand = parse_required_float(body.get("supply_on_hand"), "Supply on hand", errors)
    refill_threshold = parse_required_float(body.get("refill_threshold"), "Refill threshold", errors)
    start_date = body.get("start_date", "")
    if errors:
        return jsonify(errors=errors), 400

    medication_id = add_medication(med_name, med_unit)
    add_prescription(pet_id, medication_id, dosage_amount, frequency_hours,
                      supply_on_hand, refill_threshold, start_date)
    # add_prescription() (used by both the HTML and API routes) doesn't
    # return the new row's id, so fetch the pet's prescriptions and take the
    # highest id rather than changing that shared function's return contract
    # just for this one caller.
    rxs = get_prescriptions_for_pet(pet_id)
    created = max(rxs, key=lambda r: r["id"])
    return jsonify(prescription_to_dict(created)), 201


def _get_owned_prescription(prescription_id, owner_id):
    """Shared lookup + ownership check for the three prescription_id routes
    below. Returns (prescription_row, error_response_or_None).
    """
    rx = get_prescription_with_owner(prescription_id)
    if not rx:
        return None, (jsonify(error="Prescription not found."), 404)
    if rx["owner_id"] != owner_id:
        return None, (jsonify(error="You do not have access to this prescription."), 403)
    return rx, None


@api.route("/prescriptions/<int:prescription_id>", methods=["PATCH"])
def update_prescription_api(prescription_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    rx, error = _get_owned_prescription(prescription_id, owner_id)
    if error:
        return error

    body = request.get_json(silent=True) or {}
    errors = []
    dosage_amount = parse_optional_float(body.get("dosage_amount"), "Dosage amount", errors) if "dosage_amount" in body else None
    frequency_hours = parse_optional_int(body.get("frequency_hours"), "Frequency (hours)", errors) if "frequency_hours" in body else None
    supply_on_hand = parse_optional_float(body.get("supply_on_hand"), "Supply on hand", errors) if "supply_on_hand" in body else None
    refill_threshold = parse_optional_float(body.get("refill_threshold"), "Refill threshold", errors) if "refill_threshold" in body else None
    start_date = body.get("start_date")
    if errors:
        return jsonify(errors=errors), 400

    update_prescription(prescription_id, dosage_amount, frequency_hours,
                         supply_on_hand, refill_threshold, start_date)
    return jsonify(prescription_to_dict(get_prescription_with_owner(prescription_id))), 200


@api.route("/prescriptions/<int:prescription_id>", methods=["DELETE"])
def delete_prescription_api(prescription_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    rx, error = _get_owned_prescription(prescription_id, owner_id)
    if error:
        return error

    delete_prescription(prescription_id)
    return "", 204


# ---------- Doses ----------

@api.route("/prescriptions/<int:prescription_id>/doses", methods=["POST"])
def log_dose_api(prescription_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    rx, error = _get_owned_prescription(prescription_id, owner_id)
    if error:
        return error

    body = request.get_json(silent=True) or {}
    errors = []
    amount = parse_required_float(body.get("amount"), "Amount given", errors)
    if errors:
        return jsonify(errors=errors), 400

    log_dose(prescription_id, amount)
    updated = get_prescription_with_owner(prescription_id)
    return jsonify(prescription_to_dict(updated)), 201


# ---------- Alerts ----------

@api.route("/alerts", methods=["GET"])
def list_alerts_api():
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    alerts = get_alerts_for_owner(owner_id)
    return jsonify([alert_to_dict(a) for a in alerts]), 200


@api.route("/alerts/<int:alert_id>", methods=["PATCH"])
def resolve_alert_api(alert_id):
    owner_id = require_login_json()
    if not owner_id:
        return jsonify(error="Login required."), 401
    alert = get_alert_with_owner(alert_id)
    if not alert:
        return jsonify(error="Alert not found."), 404
    if alert["owner_id"] != owner_id:
        return jsonify(error="You do not have access to this alert."), 403

    body = request.get_json(silent=True) or {}
    # Only resolving is supported - there's no legitimate use case in this
    # app for an alert going from resolved back to unresolved (the checks in
    # alerts.py will simply re-create it if the underlying condition still
    # holds), so explicitly reject the confusing case rather than ignore it.
    if body.get("resolved") is False:
        return jsonify(error="Un-resolving an alert is not supported."), 400

    resolve_alert(alert_id)
    return jsonify(id=alert_id, resolved=True), 200
