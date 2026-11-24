# Chatbot Full Training para Instagram — instrucciones completas

## 1. Qué hace

El proyecto implementa el flujo descrito en `Information/Flujo/Steps.txt`:

1. La primera respuesta activa el saludo y muestra las opciones Guadalupe, Bosque Santa Anita, Wellness e HYROX.
2. Las respuestas por texto o botones se normalizan y aceptan variantes parecidas.
3. Muestra horarios e imágenes para las sucursales.
4. Wellness informa que está disponible únicamente en Guadalupe.
5. HYROX muestra su información y pregunta la sucursal; después continúa el registro.
6. Para Guadalupe, Santa Anita y Wellness recopila nombre completo, teléfono, correo y año de nacimiento.
7. El registro se intenta enviar a Google Sheets, junto con año, mes, día y opción.
8. Al finalizar se entrega el link correcto de WhatsApp.
9. Si no entiende una respuesta posterior al registro, devuelve el link correspondiente de forma formal y motivacional.

## 2. Archivos principales

- `app.py`: servidor webhook, flujo conversacional, registro y enlaces.
- `test_chatbot.py`: pruebas del flujo básico.
- `requirements.txt`: dependencias Python.
- `.env.example`: modelo de configuración.
- `.venv/`: entorno Python aislado del proyecto.
- `Information/messages/`: saludos, horarios, HYROX y WhatsApp.
- `Information/images/`: imágenes de precios.

## 3. Configuración local

Crea `.env` usando `.env.example`:

```text
PORT=3000
PUBLIC_BASE_URL=https://TU-DOMINIO-PUBLICO
VERIFY_TOKEN=un_token_verificador_largo
META_ACCESS_TOKEN=token_permanente_de_meta
META_INSTAGRAM_ACCOUNT_ID=id_de_cuenta_profesional_instagram
GOOGLE_SHEET_WEBHOOK_URL=https://script.google.com/macros/s/DEPLOYMENT/exec
GOOGLE_SHEET_TOKEN=0710
WEBHOOK_APP_SECRET=app_secret_de_meta
```

## 4. Configurar Instagram

1. En Meta for Developers, agrega Instagram Messaging a la app.
2. Vincula la cuenta profesional de Instagram a la página de Facebook administrada por la app.
3. Copia el ID de la cuenta profesional de Instagram a `META_INSTAGRAM_ACCOUNT_ID`.
4. Crea el token y colócalo en `META_ACCESS_TOKEN`.
5. Expón el puerto 3000 mediante HTTPS público.
6. Configura el Callback URL como `https://TU-DOMINIO-PUBLICO/webhook` y el Verify Token como el valor de `VERIFY_TOKEN`.
7. Suscríbete a mensajes de Instagram en el webhook.
8. Define `PUBLIC_BASE_URL` sin barra final.

## 5. Conectar Google Sheets

El Apps Script existente ya debe usar `Leads`, `DEFAULT_TOKEN = '0710'` y la acción `upsert_lead`.

1. Selecciona **Implementar > Nuevo deployment**.
2. Tipo: **Aplicación web**.
3. Ejecutar como: **Yo**.
4. Acceso: **Cualquier persona**.
5. Copia la URL `/exec` a `GOOGLE_SHEET_WEBHOOK_URL`.
6. Conserva `GOOGLE_SHEET_TOKEN=0710`.

El chatbot enviará automáticamente año, mes, día, hora, nombre, teléfono, correo, fecha de nacimiento, programa, sucursal, fuente Instagram e identificador del usuario de Instagram.

## 6. Validaciones incluidas

- Nombre: al menos dos palabras y máximo 100 caracteres.
- Teléfono: entre 8 y 15 dígitos.
- Email: formato `nombre@dominio.com`.
- Año: cuatro dígitos y una edad válida entre 14 y 100 años.
- Opciones: coincidencia exacta o por palabras clave parecidas.
- Reinicio: escribir `Inicio`, `Menu` o `Reset`.

## 7. Pruebas

Ejecuta:

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_chatbot.py
```

Las pruebas cubren bienvenida, cuatro opciones, Guadalupe, HYROX y opciones desconocidas.

## 8. Seguridad y producción

- Mantén `WEBHOOK_APP_SECRET` configurado para validar que las solicitudes vienen de Meta.
- Usa HTTPS y una variable `VERIFY_TOKEN` larga.
- El estado actual se guarda en memoria. Para varias instancias o reinicios frecuentes usa Redis.
- Meta solo permite iniciar nuevos mensajes fuera de la sesión dentro de plantillas aprobadas; las respuestas automáticas permanecen sujetas a su política de ventanas de atención.
- Los archivos en `Information/` pueden modificarse sin cambiar el código, salvo que cambie el nombre o formato de los archivos.
