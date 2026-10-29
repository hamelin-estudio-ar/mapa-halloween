# Backend Ruta Magica 2026

## Configuración de producción

Configurar estas variables en Cloud Run:

- `GCS_BUCKET_NAME`: bucket existente donde se guardan `usuarios.json`, `visitas.json` y `locales.json`.
- `SECRET_KEY`: secreto estable y privado, administrado mediante Secret Manager. Debe mantenerse igual entre instancias y revisiones para validar sesiones.
- `CORS_ORIGINS`: origen exacto del frontend publicado; acepta varios orígenes separados por coma. Si no se define, CORS queda abierto para facilitar desarrollo.

La cuenta de servicio de Cloud Run necesita permisos de lectura y escritura de objetos en el bucket (por ejemplo, `roles/storage.objectUser`). En local, si `GCS_BUCKET_NAME` no está definido, los JSON se guardan en `backend/data/`.

No guardar `SECRET_KEY` en este repositorio. Sin esa variable, las rutas de autenticación responden `503` en vez de emitir sesiones no seguras.

## API

- `GET /api/locales`: crea `locales.json` con los 27 locales si todavía no existe y los devuelve.
- `POST /api/auth/register`: crea una cuenta con contraseña hasheada y devuelve un token de sesión.
- `POST /api/auth/login`: valida credenciales y devuelve un token de sesión.
- `GET /api/visitas?email=...`: requiere `Authorization: Bearer <token>` y devuelve el historial de ese usuario.
- `POST /api/visita`: registra un check-in autenticado con `local_id` y `distancia`.
- `DELETE /api/visitas/<local_id>`: deshace el check-in del usuario autenticado.
