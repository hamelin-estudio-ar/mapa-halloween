import copy
import hashlib
import math
import os
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache, wraps

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

app = Flask(__name__)
allowed_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "*").split(",") if origin.strip()]
CORS(
    app,
    resources={r"/api/*": {"origins": allowed_origins}},
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "DELETE", "OPTIONS"],
)

FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "(default)").strip() or "(default)"
FIRESTORE_COLLECTIONS = {
    "usuarios.json": "usuarios",
    "visitas.json": "visitas",
    "locales.json": "locales",
}
CHECKIN_DISTANCE_LIMIT_METERS = 2
SESSION_SECRET = os.getenv("SECRET_KEY", "").strip()
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
TOKEN_SERIALIZER = (
    URLSafeTimedSerializer(SESSION_SECRET, salt="ruta-magica-session-v1")
    if SESSION_SECRET
    else None
)
EMAIL_PATTERN = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
    r"(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$",
    re.IGNORECASE,
)
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


@lru_cache(maxsize=1)
def _firestore_client():
    from google.cloud import firestore

    return firestore.Client(database=FIRESTORE_DATABASE)


def _collection(filename):
    try:
        collection_name = FIRESTORE_COLLECTIONS[filename]
    except KeyError as error:
        raise ValueError("Colección de persistencia no permitida") from error
    return _firestore_client().collection(collection_name)


def get_document(filename, document_id):
    snapshot = _collection(filename).document(document_id).get()
    return snapshot.to_dict() if snapshot.exists else None


def user_document_id(email):
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def visit_document_id(email, local_id):
    value = f"{email}:{int(local_id)}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def read_json(filename, default):
    collection = _collection(filename)
    if filename == "usuarios.json":
        records = {}
        for snapshot in collection.stream():
            record = snapshot.to_dict() or {}
            email = normalize_email(record.get("email") or snapshot.id)
            if email == "admin@rutamagica.com.ar":
                snapshot.reference.delete()
                continue
            legacy_fields = {"tipo_documento", "documento", "password_hash", "password_reset_at"}
            fields_to_remove = legacy_fields.intersection(record)
            if fields_to_remove:
                from google.cloud import firestore

                snapshot.reference.update({field: firestore.DELETE_FIELD for field in fields_to_remove})
                for field in fields_to_remove:
                    record.pop(field, None)
            record.setdefault("email", email)
            records[email] = record
        return records if records else copy.deepcopy(default)

    records = []
    for snapshot in collection.stream():
        record = snapshot.to_dict() or {}
        if filename == "visitas.json" and record.get("email") == "admin@rutamagica.com.ar":
            snapshot.reference.delete()
            continue
        records.append(record)
    if not records:
        return copy.deepcopy(default)
    if filename == "locales.json":
        records.sort(key=lambda record: int(record.get("id", 0)))
    return records


def run_transaction(callback):
    from google.cloud import firestore

    transaction = _firestore_client().transaction()
    return firestore.transactional(callback)(transaction)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_email(value):
    return value.strip().lower() if isinstance(value, str) else ""


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


def public_user(user):
    return {
        "nombre": user["nombre"],
        "apellido": user["apellido"],
        "email": user["email"],
        "telefono": user.get("telefono", ""),
        "rol": "admin" if user.get("rol") == "admin" else "user",
        "timestampRegistro": user["timestampRegistro"],
    }


def issue_token(email, auth_version=0):
    if TOKEN_SERIALIZER is None:
        raise RuntimeError("El backend requiere configurar SECRET_KEY para habilitar sesiones")
    return TOKEN_SERIALIZER.dumps({"email": email, "auth_version": auth_version})


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
        user = get_document("usuarios.json", user_document_id(g.user_email))
        if not user:
            return jsonify({"error": "La cuenta ya no está disponible. Iniciá sesión nuevamente"}), 401
        try:
            token_version = int(payload.get("auth_version", 0))
            current_version = int(user.get("auth_version", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "La sesión no es válida"}), 401
        if token_version != current_version:
            return jsonify({"error": "La sesión fue revocada. Iniciá sesión nuevamente"}), 401
        return view(*args, **kwargs)

    return wrapped


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_document("usuarios.json", user_document_id(g.user_email))
        if not user:
            return jsonify({"error": "Usuario no encontrado"}), 401
        if user.get("rol") != "admin":
            return jsonify({"error": "Se requiere rol de administrador"}), 403
        g.admin_user = user
        return view(*args, **kwargs)

    return wrapped


def get_visits_for(email):
    return [snapshot.to_dict() or {} for snapshot in _collection("visitas.json").where("email", "==", email).stream()]


def delete_visits_for_email(email):
    collection = _collection("visitas.json")
    batch = _firestore_client().batch()
    pending = 0
    for snapshot in collection.where("email", "==", email).stream():
        batch.delete(snapshot.reference)
        pending += 1
        if pending == 450:
            batch.commit()
            batch = _firestore_client().batch()
            pending = 0
    if pending:
        batch.commit()


@app.get("/")
def health_check():
    return jsonify({
        "status": "ok",
        "message": "Backend Ruta Mágica 2026 activo",
        "storage": "firestore",
    }), 200


@app.get("/api/locales")
def listar_locales():
    locales = read_json("locales.json", None)
    if not isinstance(locales, list) or not locales:
        from google.api_core.exceptions import AlreadyExists

        collection = _collection("locales.json")
        for local in DEFAULT_LOCALES:
            try:
                collection.document(str(local["id"])).create(local)
            except AlreadyExists:
                pass
        locales = read_json("locales.json", DEFAULT_LOCALES)
    return jsonify({"success": True, "locales": locales}), 200


@app.get("/api/auth/google/config")
def configuracion_login_google():
    return jsonify({
        "enabled": bool(GOOGLE_OAUTH_CLIENT_ID),
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
    }), 200


@app.post("/api/auth/google")
def iniciar_sesion_google():
    if TOKEN_SERIALIZER is None:
        return jsonify({"error": "El backend no tiene SECRET_KEY configurada"}), 503
    if not GOOGLE_OAUTH_CLIENT_ID:
        return jsonify({"error": "El acceso con Google todavía no está configurado"}), 503

    data = request.get_json(silent=True) or {}
    credential = data.get("credential")
    if not isinstance(credential, str) or not credential:
        return jsonify({"error": "Google no devolvió una credencial válida"}), 400
    try:
        claims = google_id_token.verify_oauth2_token(
            credential,
            GoogleAuthRequest(),
            GOOGLE_OAUTH_CLIENT_ID,
        )
    except (ValueError, GoogleAuthError):
        return jsonify({"error": "No se pudo verificar tu cuenta de Google. Intentá nuevamente."}), 401

    email = normalize_email(claims.get("email"))
    google_sub = claims.get("sub")
    if not EMAIL_PATTERN.fullmatch(email) or not isinstance(google_sub, str) or not google_sub:
        return jsonify({"error": "Google no devolvió un email válido"}), 401
    if claims.get("email_verified") is not True:
        return jsonify({"error": "Necesitamos un email verificado por Google"}), 401

    full_name = str(claims.get("name", "")).strip().split()
    first_name = str(claims.get("given_name") or (full_name[0] if full_name else "Participante")).strip()
    last_name = str(claims.get("family_name") or " ".join(full_name[1:]) or "Google").strip()
    if not valid_person_name(first_name):
        first_name = "Participante"
    if not valid_person_name(last_name):
        last_name = "Google"
    now = utc_now()
    new_user = {
        "nombre": first_name,
        "apellido": last_name,
        "email": email,
        "telefono": "",
        "rol": "user",
        "auth_version": 1,
        "google_sub": google_sub,
        "timestampRegistro": now,
        "acepta_terminos": True,
        "fecha_aceptacion_terminos": now,
        "consentimiento_promociones": data.get("consentimiento_promociones") is True,
        "fecha_consentimiento_promociones": now if data.get("consentimiento_promociones") is True else None,
        "email_verificado": True,
        "fecha_verificacion_email": now,
    }
    user_ref = _collection("usuarios.json").document(user_document_id(email))

    def upsert_google_user(transaction):
        snapshot = transaction.get(user_ref)
        user = snapshot.to_dict() if snapshot.exists else None
        if user:
            linked_sub = user.get("google_sub")
            if linked_sub and linked_sub != google_sub:
                return {"conflict": True}
            user.update({
                "google_sub": google_sub,
                "email_verificado": True,
                "fecha_verificacion_email": user.get("fecha_verificacion_email") or now,
            })
            transaction.set(user_ref, user)
            return {"user": user}
        if data.get("acepta_terminos") is not True:
            return {"requires_terms": True}
        transaction.create(user_ref, new_user)
        return {"user": new_user}

    result = run_transaction(upsert_google_user)
    if result.get("requires_terms"):
        return jsonify({
            "error": "Aceptá las bases y el aviso de privacidad para crear la cuenta con Google",
            "requires_terms": True,
        }), 428
    if result.get("conflict"):
        return jsonify({"error": "Esta cuenta ya está vinculada a otro perfil de Google"}), 409
    user = result.get("user")
    if not user:
        return jsonify({"error": "No se pudo iniciar sesión con Google"}), 500
    return jsonify({"success": True, "token": issue_token(email, int(user.get("auth_version", 0))), "user": public_user(user)}), 200


def admin_user_summary(email, user):
    return {
        "email": email,
        "nombre": user.get("nombre", ""),
        "apellido": user.get("apellido", ""),
        "telefono": user.get("telefono", ""),
        "rol": "admin" if user.get("rol") == "admin" else "user",
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
    result = {}

    user_ref = _collection("usuarios.json").document(user_document_id(email))
    roles_ref = _firestore_client().collection("sistema").document("roles")

    def set_role(transaction):
        snapshot = transaction.get(user_ref)
        target = snapshot.to_dict() if snapshot.exists else None
        if not target:
            return {"not_found": True}
        roles_snapshot = transaction.get(roles_ref)
        if roles_snapshot.exists:
            admin_count = int((roles_snapshot.to_dict() or {}).get("admin_count", 0))
        else:
            admins = list(_collection("usuarios.json").where("rol", "==", "admin").stream(transaction=transaction))
            admin_count = len(admins)
        previous_role = target.get("rol")
        if previous_role == "admin" and role == "user":
            if admin_count <= 1:
                return {"last_admin": True}
            admin_count -= 1
        elif previous_role != "admin" and role == "admin":
            admin_count += 1
        target["rol"] = role
        transaction.set(roles_ref, {"admin_count": admin_count})
        transaction.set(user_ref, target)
        return {"user": admin_user_summary(email, target)}

    result = run_transaction(set_role)
    if result.get("not_found"):
        return jsonify({"error": "No existe un usuario con ese email"}), 404
    if result.get("last_admin"):
        return jsonify({"error": "Debe quedar al menos un administrador"}), 409
    return jsonify({"success": True, "usuario": result["user"]}), 200


@app.post("/api/admin/eliminar-usuario")
@require_session
@require_admin
def eliminar_usuario_admin():
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    if not EMAIL_PATTERN.fullmatch(email):
        return jsonify({"error": "Ingresá un email válido"}), 400
    if email == g.user_email:
        return jsonify({"error": "No podés eliminar tu propia cuenta"}), 409
    user_ref = _collection("usuarios.json").document(user_document_id(email))

    def remove_user(transaction):
        snapshot = transaction.get(user_ref)
        current = snapshot.to_dict() if snapshot.exists else None
        if not current:
            return {"not_found": True}
        if current.get("rol") == "admin":
            return {"admin": True}
        transaction.delete(user_ref)
        return {"deleted": True}

    result = run_transaction(remove_user)
    if result.get("not_found"):
        return jsonify({"error": "No existe un usuario con ese email"}), 404
    if result.get("admin"):
        return jsonify({"error": "No se pueden eliminar cuentas de administrador"}), 409

    delete_visits_for_email(email)
    return jsonify({"success": True, "email": email}), 200


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
    if local_id <= 0 or not math.isfinite(distancia) or distancia < 0 or distancia >= CHECKIN_DISTANCE_LIMIT_METERS:
        return jsonify({"error": "La visita debe estar a menos de 2 metros del local"}), 400
    locales = read_json("locales.json", DEFAULT_LOCALES)
    if not any(local.get("id") == local_id for local in locales):
        return jsonify({"error": "El local no existe"}), 404
    user = get_document("usuarios.json", user_document_id(g.user_email))
    if not user:
        return jsonify({"error": "Usuario no encontrado"}), 401

    visit = {
        "email": g.user_email,
        "local_id": local_id,
        "timestamp": utc_now(),
        "distancia": round(distancia, 2),
    }
    visit_ref = _collection("visitas.json").document(visit_document_id(g.user_email, local_id))
    user_ref = _collection("usuarios.json").document(user_document_id(g.user_email))

    def add_visit(transaction):
        user_snapshot = transaction.get(user_ref)
        if not user_snapshot.exists:
            return {"account_missing": True}
        snapshot = transaction.get(visit_ref)
        if snapshot.exists:
            return {"created": False, "visit": snapshot.to_dict() or {}}
        transaction.create(visit_ref, visit)
        return {"created": True, "visit": visit}

    result = run_transaction(add_visit)
    if result.get("account_missing"):
        return jsonify({"error": "La cuenta ya no está disponible. Iniciá sesión nuevamente"}), 401
    total = len(get_visits_for(g.user_email))
    return jsonify({"success": True, "visitado": result["visit"], "created": result["created"], "total_visitados": total}), 200


@app.delete("/api/visitas/<int:local_id>")
@require_session
def eliminar_visita(local_id):
    visit_ref = _collection("visitas.json").document(visit_document_id(g.user_email, local_id))

    def remove_visit(transaction):
        snapshot = transaction.get(visit_ref)
        if not snapshot.exists:
            return {"removed": False}
        transaction.delete(visit_ref)
        return {"removed": True}

    result = run_transaction(remove_visit)
    return jsonify({"success": True, "removed": result["removed"]}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)