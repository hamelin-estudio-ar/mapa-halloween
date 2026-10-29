import copy
import json
import math
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, request
from flask_cors import CORS
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
allowed_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]
CORS(
    app,
    resources={r"/api/*": {"origins": allowed_origins}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "DELETE", "OPTIONS"],
)

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parent / "data"))
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "").strip()
SESSION_SECRET = os.getenv("SECRET_KEY", "").strip()
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
TOKEN_SERIALIZER = (
    URLSafeTimedSerializer(SESSION_SECRET, salt="ruta-magica-session-v1")
    if SESSION_SECRET
    else None
)
LOCAL_STORAGE_LOCK = threading.RLock()
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

DEFAULT_LOCALES = [
    {"id": 1, "nombre": "Il Gioco Tienda de Ropa", "dir": "Av Rivadavia 4995, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 2, "nombre": "BetyGino", "dir": "Rosario 190, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 3, "nombre": "Tienta Helados", "dir": "Rosario 262, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 4, "nombre": "Toffee Tienda", "dir": "Viel 220, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 5, "nombre": "Café del Parque", "dir": "Viel 267, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 6, "nombre": "Veterinaria Los tres mascoteros", "dir": "Guayaquil 284, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 7, "nombre": "Bull! Café", "dir": "Viel 368, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 8, "nombre": "Peluqueria", "dir": "Viel 382, Buenos Aires", "turno": "tarde", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 9, "nombre": "Giusseppe", "dir": "Viel 384, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 10, "nombre": "Librería Sofi", "dir": "Viel 489, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 11, "nombre": "SANITARIOS LA NUEVA ERA", "dir": "Viel 493, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 12, "nombre": "La Vicca Pizzeria", "dir": "Juan Bautista Alberdi 365, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 13, "nombre": "Peluquería Picardías", "dir": "Formosa 407, Buenos Aires", "turno": "tarde", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 14, "nombre": "Otero Café", "dir": "Guayaquil 389, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 15, "nombre": "Del Turista Caballito", "dir": "Beauchef 294, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 16, "nombre": "FARO AZUL", "dir": "Rosario 486, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 17, "nombre": "Pañalera Do Re Mi", "dir": "Rosario 531, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 18, "nombre": "Aurora Café", "dir": "Rosario 588, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 19, "nombre": "Tienda Fun Star", "dir": "Rosario 596, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 20, "nombre": "Vizzentino", "dir": "Av Jose María Moreno 168, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 21, "nombre": "Peluquería Tijeritas", "dir": "José María Moreno 308, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 22, "nombre": "Dulce Esquina", "dir": "Juan Bautista Alberdi 599, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 23, "nombre": "Lavedog", "dir": "Juan Bautista Alberdi 774, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 24, "nombre": "Didactikids Caballito", "dir": "Del Barco Centenera 256, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 25, "nombre": "Libreria Apolo XI", "dir": "Del Barco Centenera 228, Buenos Aires", "turno": "manana", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 26, "nombre": "Local Arte Studio", "dir": "Del Barco Centenera 150, Buenos Aires", "turno": "tarde", "lat": None, "lng": None, "web": "", "telefono": ""},
    {"id": 27, "nombre": "Grooving Tattoo Studio", "dir": "Del Barco Centenera 150, Buenos Aires", "turno": "tarde", "lat": None, "lng": None, "web": "", "telefono": ""},
]


def _gcs_bucket():
    if not GCS_BUCKET_NAME:
        if os.getenv("K_SERVICE"):
            raise RuntimeError("Cloud Run requiere configurar GCS_BUCKET_NAME para persistir datos")
        return None
    from google.cloud import storage

    return storage.Client().bucket(GCS_BUCKET_NAME)


def _decode_json(raw, filename):
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        app.logger.exception("El objeto %s contiene JSON inválido", filename)
        raise RuntimeError(f"El archivo de datos {filename} no es JSON válido") from error


def read_json(filename, default):
    bucket = _gcs_bucket()
    if bucket:
        from google.api_core.exceptions import NotFound

        try:
            return _decode_json(bucket.blob(filename).download_as_text(), filename)
        except NotFound:
            return copy.deepcopy(default)

    path = DATA_DIR / filename
    with LOCAL_STORAGE_LOCK:
        if not path.exists():
            return copy.deepcopy(default)
        return _decode_json(path.read_text(encoding="utf-8"), filename)


def _write_local_json(filename, value):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    serialized = json.dumps(value, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=DATA_DIR, delete=False) as temp_file:
        temp_file.write(serialized)
        temp_path = Path(temp_file.name)
    os.replace(temp_path, path)


def update_json(filename, default, mutator):
    bucket = _gcs_bucket()
    if bucket:
        from google.api_core.exceptions import NotFound, PreconditionFailed

        for _ in range(6):
            blob = bucket.blob(filename)
            try:
                blob.reload()
                generation = int(blob.generation)
                current = _decode_json(blob.download_as_text(if_generation_match=generation), filename)
            except NotFound:
                generation = 0
                current = copy.deepcopy(default)
            next_value, result = mutator(current)
            try:
                blob.upload_from_string(
                    json.dumps(next_value, ensure_ascii=False, indent=2),
                    content_type="application/json; charset=utf-8",
                    if_generation_match=generation,
                )
                return result
            except PreconditionFailed:
                continue
        raise RuntimeError(f"No se pudo actualizar {filename} por escrituras concurrentes")

    with LOCAL_STORAGE_LOCK:
        path = DATA_DIR / filename
        current = _decode_json(path.read_text(encoding="utf-8"), filename) if path.exists() else copy.deepcopy(default)
        next_value, result = mutator(current)
        _write_local_json(filename, next_value)
        return result


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_email(value):
    return value.strip().lower() if isinstance(value, str) else ""


def valid_password(password):
    return (
        isinstance(password, str)
        and len(password) >= 8
        and re.search(r"[A-Z]", password) is not None
        and re.search(r"[^A-Za-z0-9]", password) is not None
    )


def public_user(user):
    return {
        "nombre": user["nombre"],
        "apellido": user["apellido"],
        "email": user["email"],
        "telefono": user.get("telefono", ""),
        "timestampRegistro": user["timestampRegistro"],
    }


def issue_token(email):
    if TOKEN_SERIALIZER is None:
        raise RuntimeError("El backend requiere configurar SECRET_KEY para habilitar sesiones")
    return TOKEN_SERIALIZER.dumps({"email": email})


def require_session(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if TOKEN_SERIALIZER is None:
            return jsonify({"error": "El backend no tiene SECRET_KEY configurada"}), 503
        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return jsonify({"error": "Sesión requerida"}), 401
        try:
            payload = TOKEN_SERIALIZER.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
        except SignatureExpired:
            return jsonify({"error": "La sesión expiró. Iniciá sesión nuevamente"}), 401
        except BadSignature:
            return jsonify({"error": "La sesión no es válida"}), 401
        g.user_email = payload.get("email", "")
        return view(*args, **kwargs)

    return wrapped


def get_visits_for(email):
    visits = read_json("visitas.json", [])
    return [visit for visit in visits if visit.get("email") == email]


@app.get("/")
def health_check():
    return jsonify({
        "status": "ok",
        "message": "Backend Ruta Mágica 2026 activo",
        "storage": "gcs" if GCS_BUCKET_NAME else "local",
    }), 200


@app.get("/api/locales")
def listar_locales():
    locales = read_json("locales.json", None)
    if not isinstance(locales, list) or not locales:
        locales = update_json("locales.json", DEFAULT_LOCALES, lambda value: (value or copy.deepcopy(DEFAULT_LOCALES), value or copy.deepcopy(DEFAULT_LOCALES)))
    return jsonify({"success": True, "locales": locales}), 200


@app.post("/api/auth/register")
def registrar_usuario():
    if TOKEN_SERIALIZER is None:
        return jsonify({"error": "El backend no tiene SECRET_KEY configurada"}), 503
    data = request.get_json(silent=True) or {}
    nombre = data.get("nombre", "").strip() if isinstance(data.get("nombre"), str) else ""
    apellido = data.get("apellido", "").strip() if isinstance(data.get("apellido"), str) else ""
    email = normalize_email(data.get("email"))
    telefono = data.get("telefono", "").strip() if isinstance(data.get("telefono", ""), str) else ""
    password = data.get("password")

    if not nombre or not apellido or not EMAIL_PATTERN.fullmatch(email):
        return jsonify({"error": "Ingresá nombre, apellido y un email válido"}), 400
    if not valid_password(password):
        return jsonify({"error": "La contraseña requiere 8 caracteres, una mayúscula y un carácter especial"}), 400

    user_record = {
        "nombre": nombre,
        "apellido": apellido,
        "email": email,
        "telefono": telefono,
        "password_hash": generate_password_hash(password),
        "timestampRegistro": utc_now(),
    }
    result = {}

    def add_user(users):
        if email in users:
            result["created"] = False
            return users, None
        users[email] = user_record
        result["created"] = True
        return users, None

    update_json("usuarios.json", {}, add_user)
    if not result["created"]:
        return jsonify({"error": "Ya existe una cuenta con ese email"}), 409
    return jsonify({"success": True, "token": issue_token(email), "user": public_user(user_record)}), 201


@app.post("/api/auth/login")
def iniciar_sesion():
    if TOKEN_SERIALIZER is None:
        return jsonify({"error": "El backend no tiene SECRET_KEY configurada"}), 503
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    password = data.get("password")
    if not EMAIL_PATTERN.fullmatch(email) or not isinstance(password, str):
        return jsonify({"error": "Email o contraseña incorrectos"}), 401

    users = read_json("usuarios.json", {})
    user = users.get(email)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return jsonify({"error": "Email o contraseña incorrectos"}), 401
    return jsonify({"success": True, "token": issue_token(email), "user": public_user(user)}), 200


@app.get("/api/visitas")
@require_session
def listar_visitas():
    email = normalize_email(request.args.get("email"))
    if not email:
        return jsonify({"error": "Falta el email"}), 400
    if email != g.user_email:
        return jsonify({"error": "No tenés permiso para consultar estas visitas"}), 403
    visits = get_visits_for(email)
    visits.sort(key=lambda visit: visit.get("timestamp", ""))
    return jsonify({"success": True, "visitas": visits}), 200


@app.post("/api/visita")
@require_session
def registrar_visita():
    data = request.get_json(silent=True) or {}
    try:
        local_id = int(data.get("local_id"))
        distancia = float(data.get("distancia"))
    except (TypeError, ValueError):
        return jsonify({"error": "local_id y distancia son obligatorios"}), 400
    if local_id <= 0 or not math.isfinite(distancia) or distancia < 0 or distancia >= 70:
        return jsonify({"error": "La visita debe estar a menos de 70 metros del local"}), 400
    locales = read_json("locales.json", DEFAULT_LOCALES)
    if not any(local.get("id") == local_id for local in locales):
        return jsonify({"error": "El local no existe"}), 404
    users = read_json("usuarios.json", {})
    user = users.get(g.user_email)
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 401

    visit = {
        "email": g.user_email,
        "local_id": local_id,
        "timestamp": utc_now(),
        "distancia": round(distancia, 2),
    }
    result = {}

    def add_visit(visits):
        existing = next((item for item in visits if item.get("email") == g.user_email and item.get("local_id") == local_id), None)
        if existing:
            result["created"] = False
            result["visit"] = existing
            return visits, None
        visits.append(visit)
        result["created"] = True
        result["visit"] = visit
        return visits, None

    update_json("visitas.json", [], add_visit)
    total = len(get_visits_for(g.user_email))
    return jsonify({"success": True, "visitado": result["visit"], "created": result["created"], "total_visitados": total}), 200


@app.delete("/api/visitas/<int:local_id>")
@require_session
def eliminar_visita(local_id):
    result = {"removed": False}

    def remove_visit(visits):
        remaining = [
            visit for visit in visits
            if not (visit.get("email") == g.user_email and visit.get("local_id") == local_id)
        ]
        result["removed"] = len(remaining) != len(visits)
        return remaining, None

    update_json("visitas.json", [], remove_visit)
    return jsonify({"success": True, "removed": result["removed"]}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)