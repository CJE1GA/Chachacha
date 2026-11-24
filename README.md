# Chatbot Full Training para Instagram Direct (Meta API)

Chatbot basado en `Information/`. Atiende mensajes de Instagram Direct, registra leads y los guarda en Google Sheets mediante el Apps Script proporcionado.

## 1. Requisitos

- Cuenta Meta Developer con Instagram Messaging configurado.
- Cuenta profesional de Instagram vinculada a una página de Facebook administrada por la app.
- Python 3.12 o superior.
- URL pública HTTPS para el webhook e imágenes.
- Apps Script desplegado en Google Sheets con el token `0710`.

## 2. Instalar

Crea el entorno e instala dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copia `.env.example` como `.env` y completa las variables.

## 3. Configurar Instagram

1. Agrega Instagram Messaging o Instagram API en la app de Meta Developer.
2. Vincula una cuenta profesional de Instagram y una página de Facebook.
3. Copia el ID de la cuenta profesional de Instagram a `META_INSTAGRAM_ACCOUNT_ID`.
4. Crea un token válido y colócalo en `META_ACCESS_TOKEN`.
5. Ejecuta:

```powershell
.\.venv\Scripts\python.exe app.py
```

6. Expón el puerto 3000 mediante HTTPS.
7. Configura el webhook con:
   - URL: `https://TU-DOMINIO/webhook`
   - Verify token: el valor de `VERIFY_TOKEN`
8. Suscríbete a mensajes de Instagram.
9. Configura `PUBLIC_BASE_URL` sin barra final.

## 4. Conectar Google Sheets

Usa el Apps Script proporcionado sin modificar su estructura principal.

1. Selecciona **Implementar > Nuevo deployment**.
2. Tipo: **Aplicación web**.
3. Ejecutar como: **Yo**.
4. Acceso: **Cualquier persona**.
5. Copia la URL `/exec` en `GOOGLE_SHEET_WEBHOOK_URL`.
6. Confirma que `GOOGLE_SHEET_TOKEN=0710` coincide con `DEFAULT_TOKEN` del script.

El chatbot envía:

```text
action=upsert_lead
token=0710
lead.identifier=<ID de Instagram>
lead.source=Instagram
lead.program=<opción seleccionada>
lead.branch=<sucursal>
lead.name, phone, mail, birth_date, year, month, day, hour
```

El script crea o actualiza el lead usando `identifier` para evitar duplicados.

## 5. Pruebas locales

```powershell
.\.venv\Scripts\python.exe -m unittest -v test_chatbot.py
.\.venv\Scripts\python.exe app.py
```

Endpoint de salud:

```text
https://TU-DOMINIO/health
```

## 6. Contenido editable

El chatbot lee automáticamente:

- `Information/messages/mensaje_bienvenida.txt`
- `Information/messages/Horario_Guadalupe.txt`
- `Information/messages/Horario_bosque_Santa_Anita.txt`
- `Information/messages/Hyrox.txt`
- `Information/messages/Links.txt`
- `Information/images/precios_guadalupe.png`
- `Information/images/precios_bosque_santa_anita.png`

No uses nombres nuevos sin actualizarlos también en el código.

## 7. Seguridad

- Configura `WEBHOOK_APP_SECRET` con el App Secret de Meta para validar firmas.
- Nunca subas `.env` a GitHub.
- Usa HTTPS y un token de verificación largo.
- Para muchos usuarios y varias instancias, reemplaza el almacén `Map()` por Redis.
- Meta requiere que los usuarios hayan iniciado el flujo o estén dentro de la ventana de 24 horas para respuestas libres.
