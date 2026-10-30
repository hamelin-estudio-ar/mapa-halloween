# Backend Ruta Magica 2026

## Configuración de producción

Configurar estas variables en Cloud Run:

- `FIRESTORE_DATABASE`: base Firestore; por defecto `(default)`.
- `SECRET_KEY`: secreto estable y privado, administrado mediante Secret Manager. Debe mantenerse igual entre instancias y revisiones para validar sesiones.
- `GOOGLE_OAUTH_CLIENT_ID`: Client ID público de un OAuth 2.0 Web client de Google. Autorizar como JavaScript origin el origen exacto de GitHub Pages (por ejemplo, `https://hamelin-estudio-ar.github.io`) y configurar este valor en Cloud Run. El backend verifica el ID token; no poner client secrets en el HTML.
- `CORS_ORIGINS`: origen exacto del frontend publicado; acepta varios orígenes separados por coma. Si no se define, CORS queda abierto para facilitar desarrollo.

La cuenta de servicio de Cloud Run necesita el rol `roles/datastore.user` en el proyecto con Firestore habilitado. El backend usa Application Default Credentials y escribe en tres colecciones: `usuarios`, `visitas` y `locales`. Cada perfil, check-in y local es un documento independiente. Los check-ins usan un ID determinístico por email/local y se crean o eliminan mediante transacciones para evitar duplicados concurrentes.

El acceso a cuentas es exclusivamente con Google. Las cuentas nuevas reciben rol `user`; las cuentas ya existentes conservan el rol guardado. No se crea ni promueve ninguna cuenta admin por email o contraseña: los roles admin se gestionan desde el panel y se conservan en la colección `usuarios`. El modo invitado guarda el progreso sólo en el dispositivo y no crea una cuenta en el backend.

Al leer los datos existentes, el backend elimina campos heredados de DNI y hashes locales de contraseña, además de la cuenta ficticia `admin@rutamagica.com.ar` y sus visitas. Los roles de las demás cuentas no se modifican.

## Migración desde GCS

Antes de desplegar esta versión, importar los JSON actuales de `ruta_magica/` en el bucket anterior. La cuenta que ejecuta la migración necesita lectura en el bucket y escritura en Firestore:

```powershell
python backend/migrate_gcs_to_firestore.py --bucket NOMBRE_DEL_BUCKET --project hamelin-estudio-prod
```

El script importa usuarios a `usuarios`, registros a `visitas` y locales a `locales`; crea un documento por registro y omite IDs que ya existan, por lo que puede ejecutarse nuevamente sin sobrescribir datos Firestore. Limpia DNI, hashes locales y la cuenta ficticia durante la importación. Los objetos JSON originales no se borran; conservarlos como respaldo hasta verificar la aplicación desplegada.

No guardar `SECRET_KEY` en este repositorio. Sin esa variable, las rutas de autenticación responden `503` en vez de emitir sesiones no seguras.

## API

- `GET /api/locales`: crea documentos en `locales` con los 27 locales si todavía no hay datos y los devuelve.
- `GET /api/auth/google/config` y `POST /api/auth/google`: publican la configuración de Google y verifican el ID token en backend. Las cuentas nuevas requieren aceptar las bases y el aviso de privacidad; el consentimiento de promociones es opcional y se guarda con su fecha.
- `GET /api/visitas?email=...`: requiere `Authorization: Bearer <token>` y devuelve el historial de ese usuario.
- `POST /api/visita`: registra un check-in autenticado con `local_id` y `distancia`.
- `DELETE /api/visitas/<local_id>`: deshace el check-in del usuario autenticado.
- `GET /api/admin/usuarios`: requiere rol admin y devuelve perfiles sin credenciales ni datos de identificación.
- `POST /api/admin/cambiar-rol`: requiere rol admin y evita quitar el último admin.
- `GET /api/admin/visitas-resumen`: requiere rol admin y devuelve usuarios con sus visitas y los locales más visitados.
