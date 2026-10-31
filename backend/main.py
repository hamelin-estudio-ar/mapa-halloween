import copy
import hashlib
import math
import os
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache, wraps
from urllib.parse import urlparse

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
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
)

FIRESTORE_DATABASE = os.getenv("FIRESTORE_DATABASE", "(default)").strip() or "(default)"
FIRESTORE_COLLECTIONS = {
    "usuarios.json": "usuarios",
    "visitas.json": "visitas",
    "locales.json": "locales",
}
CHECKIN_DISTANCE_LIMIT_METERS = 70
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


def transaction_get_document(transaction, document_ref):
    result = transaction.get(document_ref)
    if hasattr(result, "exists"):
        return result
    return next(iter(result))


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


def normalize_locale_payload(data):
    if not isinstance(data, dict):
        return None, "Ingresá los datos del local"
    nombre = data.get("nombre", "").strip() if isinstance(data.get("nombre"), str) else ""
    address = data.get("dir", data.get("direccion", ""))
    address = address.strip() if isinstance(address, str) else ""
    turno = data.get("turno", "manana")
    if not 2 <= len(nombre) <= 120:
        return None, "El nombre debe tener entre 2 y 120 caracteres"
    if not address or len(address) > 240:
        return None, "Ingresá una dirección de hasta 240 caracteres"
    if not isinstance(turno, str) or turno not in {"manana", "tarde", "ambos"}:
        return None, "Seleccioná un horario válido"

    coordinates = []
    for key, minimum, maximum in (("lat", -90, 90), ("lng", -180, 180)):
        value = data.get(key)
        if value in (None, ""):
            coordinates.append(None)
            continue
        try:
            coordinate = float(value)
        except (TypeError, ValueError):
            return None, "Las coordenadas deben ser números válidos"
        if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
            return None, "Las coordenadas están fuera de rango"
        coordinates.append(coordinate)
    if (coordinates[0] is None) != (coordinates[1] is None):
        return None, "Ingresá latitud y longitud juntas, o dejá ambas vacías"
    if coordinates[0] is None:
        return None, "No se pudo asignar la ubicación. Revisá la dirección e intentá de nuevo"

    def safe_url(key):
        value = data.get(key, "")
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value:
            return ""
        if len(value) > 1000:
            return None
        try:
            parsed = urlparse(value)
        except ValueError:
            return None
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None

    instagram = safe_url("instagram")
    facebook = safe_url("facebook")
    web = safe_url("web")
    if instagram is None or facebook is None or web is None:
        return None, "Los enlaces deben comenzar con http:// o https://"

    description = data.get("descripcion", "")
    hours = data.get("horarios", "")
    phone = data.get("telefono", "")
    if not all(isinstance(value, str) for value in (description, hours, phone)):
        return None, "Descripción, horarios y teléfono deben ser texto"
    if len(description) > 500 or len(hours) > 160 or len(phone) > 40:
        return None, "Revisá la longitud de descripción, horarios o teléfono"
    active = data.get("activo", True)
    if not isinstance(active, bool):
        return None, "El estado del local no es válido"
    return {
        "nombre": nombre,
        "dir": address,
        "turno": turno,
        "lat": coordinates[0],
        "lng": coordinates[1],
        "descripcion": description.strip(),
        "horarios": hours.strip(),
        "instagram": instagram,
        "facebook": facebook,
        "web": web,
        "telefono": phone.strip(),
        "activo": active,
    }, None


def public_user(user):
    return {
        "nombre": user["nombre"],
        "apellido": user["apellido"],
        "email": user["email"],
        "telefono": user.get("telefono", ""),
        "foto": user.get("foto", ""),
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
    locales = read_json("locales.json", [])
    activos = [local for local in locales if local.get("activo", True) is not False]
    return jsonify({"success": True, "locales": activos}), 200


@app.get("/api/admin/locales")
@require_session
@require_admin
def listar_locales_admin():
    locales = read_json("locales.json", [])
    locales.sort(key=lambda local: (str(local.get("nombre", "")).casefold(), int(local.get("id", 0))))
    return jsonify({"success": True, "locales": locales}), 200


@app.post("/api/admin/locales")
@require_session
@require_admin
def crear_local_admin():
    payload, error = normalize_locale_payload(request.get_json(silent=True) or {})
    if error:
        return jsonify({"error": error}), 400
    collection = _collection("locales.json")
    counter_ref = _firestore_client().collection("sistema").document("locales")

    def create_local(transaction):
        counter_snapshot = transaction_get_document(transaction, counter_ref)
        if counter_snapshot.exists:
            next_id = max(1, int((counter_snapshot.to_dict() or {}).get("next_id", 1)))
        else:
            existing = collection.stream(transaction=transaction)
            next_id = max((int((snapshot.to_dict() or {}).get("id", 0)) for snapshot in existing), default=0) + 1
        while transaction_get_document(transaction, collection.document(str(next_id))).exists:
            next_id += 1
        local = {**payload, "id": next_id, "activo": True, "created_at": utc_now(), "updated_at": utc_now()}
        transaction.create(collection.document(str(next_id)), local)
        transaction.set(counter_ref, {"next_id": next_id + 1})
        return local

    local = run_transaction(create_local)
    return jsonify({"success": True, "local": local}), 201


@app.put("/api/admin/locales/<int:local_id>")
@require_session
@require_admin
def actualizar_local_admin(local_id):
    payload, error = normalize_locale_payload(request.get_json(silent=True) or {})
    if error:
        return jsonify({"error": error}), 400
    local_ref = _collection("locales.json").document(str(local_id))

    def update_local(transaction):
        snapshot = transaction_get_document(transaction, local_ref)
        if not snapshot.exists:
            return None
        current = snapshot.to_dict() or {}
        local = {
            **payload,
            "id": local_id,
            "activo": payload["activo"],
            "created_at": current.get("created_at", current.get("createdAt", "")),
            "updated_at": utc_now(),
        }
        transaction.set(local_ref, local)
        return local

    local = run_transaction(update_local)
    if not local:
        return jsonify({"error": "No existe un local con ese ID"}), 404
    return jsonify({"success": True, "local": local}), 200


@app.delete("/api/admin/locales/<int:local_id>")
@require_session
@require_admin
def desactivar_local_admin(local_id):
    local_ref = _collection("locales.json").document(str(local_id))

    def deactivate_local(transaction):
        snapshot = transaction_get_document(transaction, local_ref)
        if not snapshot.exists:
            return False
        local = snapshot.to_dict() or {}
        local.update({"activo": False, "updated_at": utc_now()})
        transaction.set(local_ref, local)
        return True

    deactivated = run_transaction(deactivate_local)
    if not deactivated:
        return jsonify({"error": "No existe un local con ese ID"}), 404
    return jsonify({"success": True, "id": local_id, "activo": False}), 200


@app.delete("/api/admin/locales/<int:local_id>/definitivo")
@require_session
@require_admin
def eliminar_local_admin(local_id):
    local_ref = _collection("locales.json").document(str(local_id))
    visit_query = _collection("visitas.json").where("local_id", "==", local_id).limit(1)

    def delete_local(transaction):
        local_snapshot = transaction_get_document(transaction, local_ref)
        if not local_snapshot.exists:
            return {"not_found": True}
        historical_visits = list(visit_query.stream(transaction=transaction))
        if historical_visits:
            return {"has_history": True}
        transaction.delete(local_ref)
        return {"deleted": True}

    result = run_transaction(delete_local)
    if result.get("not_found"):
        return jsonify({"error": "No existe un local con ese ID"}), 404
    if result.get("has_history"):
        return jsonify({"error": "El local tiene visitas históricas. Inhabilitalo para conservarlas."}), 409
    return jsonify({"success": True, "id": local_id, "deleted": True}), 200


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
    picture = claims.get("picture")
    picture = picture if isinstance(picture, str) and urlparse(picture).scheme == "https" and urlparse(picture).netloc else ""
    new_user = {
        "nombre": first_name,
        "apellido": last_name,
        "email": email,
        "foto": picture,
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
        snapshot = transaction_get_document(transaction, user_ref)
        user = snapshot.to_dict() if snapshot.exists else None
        if user:
            linked_sub = user.get("google_sub")
            if linked_sub and linked_sub != google_sub:
                return {"conflict": True}
            user.update({
                "google_sub": google_sub,
                "foto": picture or user.get("foto", ""),
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
        snapshot = transaction_get_document(transaction, user_ref)
        target = snapshot.to_dict() if snapshot.exists else None
        if not target:
            return {"not_found": True}
        roles_snapshot = transaction_get_document(transaction, roles_ref)
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
        snapshot = transaction_get_document(transaction, user_ref)
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
    locales = read_json("locales.json", [])
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
        return jsonify({"error": "La visita debe estar a menos de 70 metros del local"}), 400
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
    local_ref = _collection("locales.json").document(str(local_id))

    def add_visit(transaction):
        local_snapshot = transaction_get_document(transaction, local_ref)
        local_record = local_snapshot.to_dict() if local_snapshot.exists else None
        if not local_record or local_record.get("activo", True) is False:
            return {"local_unavailable": True}
        user_snapshot = transaction_get_document(transaction, user_ref)
        if not user_snapshot.exists:
            return {"account_missing": True}
        snapshot = transaction_get_document(transaction, visit_ref)
        if snapshot.exists:
            return {"created": False, "visit": snapshot.to_dict() or {}}
        transaction.create(visit_ref, visit)
        return {"created": True, "visit": visit}

    result = run_transaction(add_visit)
    if result.get("local_unavailable"):
        return jsonify({"error": "El local ya no está disponible"}), 404
    if result.get("account_missing"):
        return jsonify({"error": "La cuenta ya no está disponible. Iniciá sesión nuevamente"}), 401
    total = len(get_visits_for(g.user_email))
    return jsonify({"success": True, "visitado": result["visit"], "created": result["created"], "total_visitados": total}), 200


@app.delete("/api/visitas/<int:local_id>")
@require_session
def eliminar_visita(local_id):
    visit_ref = _collection("visitas.json").document(visit_document_id(g.user_email, local_id))

    def remove_visit(transaction):
        snapshot = transaction_get_document(transaction, visit_ref)
        if not snapshot.exists:
            return {"removed": False}
        transaction.delete(visit_ref)
        return {"removed": True}

    result = run_transaction(remove_visit)
    return jsonify({"success": True, "removed": result["removed"]}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)