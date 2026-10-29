import copy
import smtplib
import json
import math
import os
import re
import secrets
import tempfile
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
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
GCS_DATA_PREFIX = "ruta_magica"
PERSISTENCE_FILES = {"usuarios.json", "visitas.json", "locales.json", "email_verificaciones.json"}
SESSION_SECRET = os.getenv("SECRET_KEY", "").strip()
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@rutamagica.com.ar").strip().lower()
ADMIN_INITIAL_PASSWORD = os.getenv("ADMIN_INITIAL_PASSWORD", "")
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME).strip()
EMAIL_CODE_TTL_SECONDS = 10 * 60
EMAIL_CODE_COOLDOWN_SECONDS = 60
EMAIL_CODE_MAX_ATTEMPTS = 5
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
TOKEN_SERIALIZER = (
    URLSafeTimedSerializer(SESSION_SECRET, salt="ruta-magica-session-v1")
    if SESSION_SECRET
    else None
)
EMAIL_VERIFICATION_SERIALIZER = (
    URLSafeTimedSerializer(SESSION_SECRET, salt="ruta-magica-email-verification-v1")
    if SESSION_SECRET
    else None
)
LOCAL_STORAGE_LOCK = threading.RLock()
EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"[0-9]{8,15}")
DOCUMENT_TYPES = {
    "dni",
    "pasaporte_argentino",
    "pasaporte_extranjero",
    "pasaporte_emergencia",
    "pasaporte_excepcional",
    "cedula_identidad",
    "libreta_civica",
    "libreta_enrolamiento",
    "documento_viaje",
    "residencia_precaria",
    "otro",
}
PASSPORT_TYPES = {
    "pasaporte_argentino",
    "pasaporte_extranjero",
    "pasaporte_emergencia",
    "pasaporte_excepcional",
}

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


def _gcs_object_name(filename):
    if filename not in PERSISTENCE_FILES:
        raise ValueError("Archivo de persistencia no permitido")
    return f"{GCS_DATA_PREFIX}/{filename}"


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
            return _decode_json(bucket.blob(_gcs_object_name(filename)).download_as_text(), filename)
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
            blob = bucket.blob(_gcs_object_name(filename))
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
        and len(password) <= 128
        and re.search(r"[A-Z]", password) is not None
        and re.search(r"[^A-Za-z0-9]", password) is not None
    )


def valid_person_name(value):
    if not isinstance(value, str):
        return False
    name = value.strip()
    if not 2 <= len(name) <= 60 or not name[0].isalpha():
        return False
    return all(
        character.isalpha()
        or unicodedata.category(character).startswith("M")
        or character in " '\u2019-"
        for character in name[1:]
    )


def valid_phone(value):
    return isinstance(value, str) and PHONE_PATTERN.fullmatch(value.strip()) is not None


def send_verification_email(email, code):
    if not SMTP_HOST or not SMTP_FROM:
        raise RuntimeError("El envío de email no está configurado en el servidor")
    message = EmailMessage()
    message["Subject"] = "Código de verificación - Ruta Mágica 2026"
    message["From"] = SMTP_FROM
    message["To"] = email
    message.set_content(
        f"Tu código para verificar el email en Ruta Mágica 2026 es: {code}\n\n"
        "Vence en 10 minutos. Si no solicitaste este código, podés ignorar este mensaje."
    )
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.starttls()
        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)


def verification_expired(record, now):
    try:
        expires_at = datetime.fromisoformat(record["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return True
    return now >= expires_at


@app.post("/api/auth/email/send-code")
def enviar_codigo_verificacion():
    if EMAIL_VERIFICATION_SERIALIZER is None:
        return jsonify({"error": "El backend no tiene SECRET_KEY configurada"}), 503
    if not SMTP_HOST or not SMTP_FROM:
        return jsonify({"error": "La verificación por email todavía no está configurada en el servidor"}), 503
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    if len(email) > 160 or not EMAIL_PATTERN.fullmatch(email):
        return jsonify({"error": "Ingresá un email válido con formato nombre@dominio.com"}), 400

    now = datetime.now(timezone.utc)
    code = f"{secrets.randbelow(1_000_000):06d}"
    record = {
        "code_hash": generate_password_hash(code),
        "sent_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=EMAIL_CODE_TTL_SECONDS)).isoformat(),
        "attempts": 0,
    }
    result = {}

    def store_code(records):
        previous = records.get(email)
        if previous:
            try:
                previous_sent_at = datetime.fromisoformat(previous.get("sent_at", ""))
                elapsed = (now - previous_sent_at).total_seconds()
            except (TypeError, ValueError):
                elapsed = EMAIL_CODE_COOLDOWN_SECONDS
            if elapsed < EMAIL_CODE_COOLDOWN_SECONDS:
                result["cooldown"] = int(EMAIL_CODE_COOLDOWN_SECONDS - elapsed)
                return records, None
        records[email] = record
        return records, None

    update_json("email_verificaciones.json", {}, store_code)
    if result.get("cooldown"):
        return jsonify({"error": f"Esperá {result['cooldown']} segundos antes de pedir otro código"}), 429

    try:
        send_verification_email(email, code)
    except (OSError, smtplib.SMTPException, RuntimeError) as error:
        app.logger.warning("No se pudo enviar un código de verificación: %s", error)

        def remove_failed_code(records):
            current = records.get(email)
            if current and current.get("code_hash") == record["code_hash"]:
                records.pop(email, None)
            return records, None

        update_json("email_verificaciones.json", {}, remove_failed_code)
        return jsonify({"error": "No se pudo enviar el email. Revisá la configuración del servidor e intentá de nuevo"}), 503

    return jsonify({"success": True, "message": "Si el email puede recibir mensajes, enviamos un código de verificación"}), 200


@app.post("/api/auth/email/verify-code")
def verificar_codigo_email():
    if EMAIL_VERIFICATION_SERIALIZER is None:
        return jsonify({"error": "El backend no tiene SECRET_KEY configurada"}), 503
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    code = data.get("code")
    if len(email) > 160 or not EMAIL_PATTERN.fullmatch(email) or not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        return jsonify({"error": "Ingresá un email válido y un código de 6 dígitos"}), 400

    now = datetime.now(timezone.utc)
    result = {}

    def check_code(records):
        record = records.get(email)
        if not record:
            result["error"] = "Solicitá un código nuevo para verificar tu email"
            return records, None
        if verification_expired(record, now):
            records.pop(email, None)
            result["error"] = "El código venció. Solicitá uno nuevo"
            return records, None
        if record.get("attempts", 0) >= EMAIL_CODE_MAX_ATTEMPTS:
            records.pop(email, None)
            result["error"] = "Se superó el máximo de intentos. Solicitá un código nuevo"
            return records, None
        if not check_password_hash(record.get("code_hash", ""), code):
            record["attempts"] = record.get("attempts", 0) + 1
            result["error"] = "El código ingresado no es válido"
            return records, None
        records.pop(email, None)
        result["verified"] = True
        return records, None

    update_json("email_verificaciones.json", {}, check_code)
    if not result.get("verified"):
        return jsonify({"error": result.get("error", "No se pudo verificar el email")}), 400
    token = EMAIL_VERIFICATION_SERIALIZER.dumps({"email": email, "purpose": "register"})
    return jsonify({"success": True, "email_verification_token": token}), 200


def public_user(user):
    return {
        "nombre": user["nombre"],
        "apellido": user["apellido"],
        "email": user["email"],
        "telefono": user.get("telefono", ""),
        "tipo_documento": user.get("tipo_documento", ""),
        "documento": user.get("documento", ""),
        "rol": "admin" if user.get("rol") == "admin" else "user",
        "timestampRegistro": user["timestampRegistro"],
    }


def issue_token(email):
    if TOKEN_SERIALIZER is None:
        raise RuntimeError("El backend requiere configurar SECRET_KEY para habilitar sesiones")
    return TOKEN_SERIALIZER.dumps({"email": email})


def ensure_bootstrap_admin():
    if not ADMIN_EMAIL or not valid_password(ADMIN_INITIAL_PASSWORD):
        return

    timestamp = utc_now()
    seeded_admin = {
        "nombre": "Administrador",
        "apellido": "Ruta Mágica",
        "email": ADMIN_EMAIL,
        "telefono": "",
        "tipo_documento": "",
        "documento": "",
        "rol": "admin",
        "password_hash": generate_password_hash(ADMIN_INITIAL_PASSWORD),
        "timestampRegistro": timestamp,
        "acepta_terminos": False,
        "fecha_aceptacion_terminos": None,
        "consentimiento_promociones": False,
        "fecha_consentimiento_promociones": None,
    }

    def seed_admin(users):
        existing = users.get(ADMIN_EMAIL)
        if existing:
            existing["rol"] = "admin"
        else:
            users[ADMIN_EMAIL] = seeded_admin
        return users, None

    update_json("usuarios.json", {}, seed_admin)


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


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        users = read_json("usuarios.json", {})
        user = users.get(g.user_email)
        if not user:
            return jsonify({"error": "Usuario no encontrado"}), 401
        if g.user_email == ADMIN_EMAIL and user.get("rol") != "admin":
            def promote_bootstrap_admin(records):
                if g.user_email in records:
                    records[g.user_email]["rol"] = "admin"
                return records, None

            update_json("usuarios.json", {}, promote_bootstrap_admin)
            user["rol"] = "admin"
        if user.get("rol") != "admin":
            return jsonify({"error": "Se requiere rol de administrador"}), 403
        g.admin_user = user
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
    tipo_documento = data.get("tipo_documento", "").strip().lower() if isinstance(data.get("tipo_documento"), str) else ""
    documento = data.get("documento", "").strip().upper() if isinstance(data.get("documento"), str) else ""
    password = data.get("password")
    verification_token = data.get("email_verification_token")

    if not valid_person_name(nombre) or not valid_person_name(apellido):
        return jsonify({"error": "Nombre y apellido deben tener entre 2 y 60 letras"}), 400
    if len(email) > 160 or not EMAIL_PATTERN.fullmatch(email):
        return jsonify({"error": "Ingresá un email válido con formato nombre@dominio.com"}), 400
    if not valid_phone(telefono):
        return jsonify({"error": "Ingresá un teléfono válido de 8 a 20 caracteres"}), 400
    if data.get("acepta_terminos") is not True:
        return jsonify({"error": "Debés aceptar las bases de participación y el aviso de privacidad"}), 400
    if not isinstance(verification_token, str) or EMAIL_VERIFICATION_SERIALIZER is None:
        return jsonify({"error": "Verificá tu email antes de crear la cuenta"}), 400
    try:
        verification = EMAIL_VERIFICATION_SERIALIZER.loads(
            verification_token,
            max_age=EMAIL_CODE_TTL_SECONDS,
        )
    except (BadSignature, SignatureExpired):
        return jsonify({"error": "La verificación del email venció o no es válida. Solicitá un código nuevo"}), 400
    if verification.get("email") != email or verification.get("purpose") != "register":
        return jsonify({"error": "El email verificado no coincide con el email de registro"}), 400
    if tipo_documento not in DOCUMENT_TYPES:
        return jsonify({"error": "Seleccioná un tipo de documento válido"}), 400
    if tipo_documento == "dni" and not re.fullmatch(r"[0-9]{7,8}", documento):
        return jsonify({"error": "El DNI debe contener 7 u 8 números"}), 400
    if tipo_documento in PASSPORT_TYPES and not re.fullmatch(r"[A-Z0-9-]{4,20}", documento):
        return jsonify({"error": "El pasaporte debe tener entre 4 y 20 letras, números o guiones"}), 400
    if tipo_documento not in PASSPORT_TYPES and not re.fullmatch(r"[A-Z0-9./ -]{1,32}", documento):
        return jsonify({"error": "El documento contiene caracteres no admitidos"}), 400
    if not valid_password(password):
        return jsonify({"error": "La contraseña requiere 8 caracteres, una mayúscula y un carácter especial"}), 400

    if email == ADMIN_EMAIL:
        if not valid_password(ADMIN_INITIAL_PASSWORD):
            return jsonify({"error": "La cuenta admin inicial no tiene una contraseña válida en Secret Manager"}), 503
        ensure_bootstrap_admin()

    terms_timestamp = utc_now()
    promotions_consent = data.get("consentimiento_promociones") is True
    user_record = {
        "nombre": nombre,
        "apellido": apellido,
        "email": email,
        "telefono": telefono,
        "tipo_documento": tipo_documento,
        "documento": documento,
        "rol": "user",
        "password_hash": generate_password_hash(password),
        "timestampRegistro": utc_now(),
        "acepta_terminos": True,
        "fecha_aceptacion_terminos": terms_timestamp,
        "consentimiento_promociones": promotions_consent,
        "fecha_consentimiento_promociones": terms_timestamp if promotions_consent else None,
        "email_verificado": True,
        "fecha_verificacion_email": utc_now(),
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
    if email == ADMIN_EMAIL and email not in users:
        if not valid_password(ADMIN_INITIAL_PASSWORD):
            return jsonify({"error": "La cuenta admin inicial no tiene una contraseña válida en Secret Manager"}), 503
        ensure_bootstrap_admin()
        users = read_json("usuarios.json", {})
    user = users.get(email)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return jsonify({"error": "Email o contraseña incorrectos"}), 401
    role = "admin" if email == ADMIN_EMAIL or user.get("rol") == "admin" else "user"
    if user.get("rol") != role:
        def persist_role(records):
            if email in records:
                records[email]["rol"] = role
            return records, None

        update_json("usuarios.json", {}, persist_role)
        user["rol"] = role
    return jsonify({"success": True, "token": issue_token(email), "user": public_user(user)}), 200


def admin_user_summary(email, user):
    return {
        "email": email,
        "nombre": user.get("nombre", ""),
        "apellido": user.get("apellido", ""),
        "telefono": user.get("telefono", ""),
        "rol": "admin" if email == ADMIN_EMAIL or user.get("rol") == "admin" else "user",
        "fecha_registro": user.get("timestampRegistro", ""),
    }


@app.get("/api/admin/usuarios")
@require_session
@require_admin
def listar_usuarios_admin():
    users = read_json("usuarios.json", {})
    usuarios = [admin_user_summary(email, user) for email, user in users.items()]
    usuarios.sort(key=lambda user: (user["apellido"].casefold(), user["nombre"].casefold(), user["email"]))
    return jsonify({"success": True, "usuarios": usuarios, "total_usuarios": len(usuarios)}), 200


@app.post("/api/admin/cambiar-rol")
@require_session
@require_admin
def cambiar_rol_admin():
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    role = data.get("rol")
    if not EMAIL_PATTERN.fullmatch(email) or not isinstance(role, str) or role not in {"user", "admin"}:
        return jsonify({"error": "Ingresá un email y un rol válidos"}), 400
    if email == ADMIN_EMAIL and role != "admin":
        return jsonify({"error": "No se puede degradar al administrador principal"}), 409

    result = {}

    def set_role(users):
        target = users.get(email)
        if not target:
            result["not_found"] = True
            return users, None
        if role == "user":
            admins = sum(
                1 for user_email, user in users.items()
                if user_email == ADMIN_EMAIL or user.get("rol") == "admin"
            )
            if admins <= 1 and target.get("rol") == "admin":
                result["last_admin"] = True
                return users, None
        target["rol"] = role
        result["user"] = admin_user_summary(email, target)
        return users, None

    update_json("usuarios.json", {}, set_role)
    if result.get("not_found"):
        return jsonify({"error": "No existe un usuario con ese email"}), 404
    if result.get("last_admin"):
        return jsonify({"error": "Debe quedar al menos un administrador"}), 409
    return jsonify({"success": True, "usuario": result["user"]}), 200


@app.get("/api/admin/visitas-resumen")
@require_session
@require_admin
def resumen_visitas_admin():
    users = read_json("usuarios.json", {})
    visits = read_json("visitas.json", [])
    locales = read_json("locales.json", DEFAULT_LOCALES)
    local_names = {local.get("id"): local.get("nombre", "Local") for local in locales}
    visits_by_email = {}
    visits_by_local = {}

    for visit in visits:
        email = visit.get("email")
        local_id = visit.get("local_id")
        if email not in users or type(local_id) is not int:
            continue
        visits_by_email.setdefault(email, []).append({
            "local_id": local_id,
            "nombre": local_names.get(local_id, "Local"),
            "timestamp": visit.get("timestamp", ""),
            "distancia": visit.get("distancia"),
        })
        visits_by_local[local_id] = visits_by_local.get(local_id, 0) + 1

    usuarios = []
    for email, user in users.items():
        user_visits = visits_by_email.get(email, [])
        usuarios.append({
            **admin_user_summary(email, user),
            "total_checkins": len(user_visits),
            "visitas": user_visits,
        })
    usuarios.sort(key=lambda user: (-user["total_checkins"], user["apellido"].casefold(), user["email"]))
    locales_mas_visitados = [
        {"local_id": local_id, "nombre": local_names.get(local_id, "Local"), "checkins": count}
        for local_id, count in visits_by_local.items()
    ]
    locales_mas_visitados.sort(key=lambda local: (-local["checkins"], local["local_id"]))

    return jsonify({
        "success": True,
        "total_usuarios": len(users),
        "total_checkins": sum(len(user_visits) for user_visits in visits_by_email.values()),
        "usuarios": usuarios,
        "locales_mas_visitados": locales_mas_visitados,
    }), 200


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