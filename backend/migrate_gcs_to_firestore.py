import argparse
import concurrent.futures
import hashlib
import json
import os

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import firestore, storage

SOURCE_FILES = ("usuarios.json", "visitas.json", "locales.json")
FAKE_ADMIN_EMAIL = "admin@rutamagica.com.ar"
LEGACY_USER_FIELDS = {"tipo_documento", "documento", "password_hash", "password_reset_at"}


def user_document_id(email):
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def visit_document_id(email, local_id):
    value = f"{email}:{int(local_id)}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def load_source(bucket, prefix, filename, default):
    try:
        raw = bucket.blob(f"{prefix}/{filename}").download_as_text()
    except NotFound:
        return default
    return json.loads(raw)


def prepare_records(filename, source):
    if filename == "usuarios.json":
        if not isinstance(source, dict):
            raise ValueError("usuarios.json debe contener un objeto indexado por email")
        records = []
        for email, user in source.items():
            normalized_email = str(email).strip().lower()
            if normalized_email == FAKE_ADMIN_EMAIL or not isinstance(user, dict):
                continue
            record = dict(user)
            for field in LEGACY_USER_FIELDS:
                record.pop(field, None)
            record["email"] = normalized_email
            records.append((user_document_id(normalized_email), record))
        return records

    if not isinstance(source, list):
        raise ValueError(f"{filename} debe contener una lista")
    records = []
    if filename == "visitas.json":
        unique_visits = {}
        for visit in source:
            if not isinstance(visit, dict):
                continue
            email = str(visit.get("email", "")).strip().lower()
            try:
                local_id = int(visit.get("local_id"))
            except (TypeError, ValueError):
                continue
            if not email or email == FAKE_ADMIN_EMAIL or local_id <= 0:
                continue
            unique_visits[(email, local_id)] = dict(visit, email=email, local_id=local_id)
        records.extend(
            (visit_document_id(email, local_id), visit)
            for (email, local_id), visit in unique_visits.items()
        )
        return records

    for local in source:
        if not isinstance(local, dict) or local.get("id") is None:
            continue
        records.append((str(int(local["id"])), dict(local, id=int(local["id"]))))
    return records


def migrate_collection(client, collection_name, records, workers):
    collection = client.collection(collection_name)

    def create_record(item):
        document_id, record = item
        try:
            collection.document(document_id).create(record)
            return "created"
        except AlreadyExists:
            return "skipped"

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = list(executor.map(create_record, records))
    return {"created": outcomes.count("created"), "skipped": outcomes.count("skipped")}


def main():
    parser = argparse.ArgumentParser(description="Importa los JSON históricos de GCS a documentos Firestore sin sobrescribir.")
    parser.add_argument("--bucket", default=os.getenv("GCS_BUCKET_NAME"), required=os.getenv("GCS_BUCKET_NAME") is None)
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--database", default=os.getenv("FIRESTORE_DATABASE", "(default)"))
    parser.add_argument("--prefix", default="ruta_magica")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.workers < 1 or args.workers > 64:
        parser.error("--workers debe estar entre 1 y 64")

    source_bucket = storage.Client(project=args.project).bucket(args.bucket)
    firestore_client = firestore.Client(project=args.project, database=args.database)
    collection_names = {"usuarios.json": "usuarios", "visitas.json": "visitas", "locales.json": "locales"}

    for filename in SOURCE_FILES:
        source = load_source(source_bucket, args.prefix, filename, {} if filename == "usuarios.json" else [])
        records = prepare_records(filename, source)
        counts = migrate_collection(firestore_client, collection_names[filename], records, args.workers)
        print(f"{filename} -> {collection_names[filename]}: {counts['created']} creados, {counts['skipped']} ya existentes")


if __name__ == "__main__":
    main()
