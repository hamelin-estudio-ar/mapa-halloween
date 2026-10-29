# Backend Ruta Magica 2026

## Configuración de producción

Configurar estas variables en Cloud Run:

- `GCS_BUCKET_NAME`: bucket existente donde se guardan `ruta_magica/usuarios.json`, `ruta_magica/visitas.json` y `ruta_magica/locales.json`.
- `SECRET_KEY`: secreto estable y privado, administrado mediante Secret Manager. Debe mantenerse igual entre instancias y revisiones para validar sesiones.
- `ADMIN_EMAIL`: email de la cuenta que debe tener siempre el rol admin. La persona debe registrarse con ese email o volver a iniciar sesión luego de configurar la variable.
- `ADMIN_INITIAL_PASSWORD`: contraseña inicial del admin, cargada desde Secret Manager. Debe cumplir las reglas de contraseña y nunca guardarse en el repositorio. Al primer login se crea `admin@rutamagica.com.ar` si todavía no existe; si ya existe, se conserva su hash de contraseña y sólo se asegura el rol admin.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`: configuración SMTP para enviar códigos OTP. Guardar `SMTP_PASSWORD` en Secret Manager. Sin SMTP, no se puede completar el registro.
- `CORS_ORIGINS`: origen exacto del frontend publicado; acepta varios orígenes separados por coma. Si no se define, CORS queda abierto para facilitar desarrollo.

La cuenta de servicio de Cloud Run necesita permisos de lectura y escritura de objetos en el bucket (por ejemplo, `roles/storage.objectUser`). En local, si `GCS_BUCKET_NAME` no está definido, los JSON se guardan en `backend/data/`.

No guardar `SECRET_KEY` en este repositorio. Sin esa variable, las rutas de autenticación responden `503` en vez de emitir sesiones no seguras.

## API

- `GET /api/locales`: crea `locales.json` con los 27 locales si todavía no existe y los devuelve.
- `POST /api/auth/register`: crea una cuenta con contraseña hasheada y devuelve un token de sesión.
- `POST /api/auth/email/send-code` y `POST /api/auth/email/verify-code`: envían/verifican OTP antes del registro.
- El alta requiere aceptar las bases/aviso de privacidad. El consentimiento de promociones es separado, opcional y se guarda con su fecha.
- `POST /api/auth/login`: valida credenciales y devuelve un token de sesión.
- `GET /api/visitas?email=...`: requiere `Authorization: Bearer <token>` y devuelve el historial de ese usuario.
- `POST /api/visita`: registra un check-in autenticado con `local_id` y `distancia`.
- `DELETE /api/visitas/<local_id>`: deshace el check-in del usuario autenticado.
- `GET /api/admin/usuarios`: requiere rol admin y devuelve perfiles sin credenciales ni documentos.
- `POST /api/admin/cambiar-rol`: requiere rol admin; protege el administrador principal y evita quitar el último admin.
- `GET /api/admin/visitas-resumen`: requiere rol admin y devuelve usuarios con sus visitas y los locales más visitados.
