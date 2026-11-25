import hmac
import hashlib
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent
MESSAGES = ROOT / "Information" / "messages"
IMAGES = ROOT / "Information" / "images"

app = Flask(__name__)

WELCOME = (MESSAGES / "mensaje_bienvenida.txt").read_text(encoding="utf-8").strip()
GUADALUPE = (MESSAGES / "Horario_Guadalupe.txt").read_text(encoding="utf-8").strip()
SANTA_ANITA = (MESSAGES / "Horario_bosque_Santa_Anita.txt").read_text(encoding="utf-8").strip()
HYROX = (MESSAGES / "Hyrox.txt").read_text(encoding="utf-8").strip()

links = {}
links_text = (MESSAGES / "Links.txt").read_text(encoding="utf-8")
for label, url in re.findall(r'(Guadalupe|Santa Anita|Wellness):\s*"([^"]+)"', links_text, re.I):
    links[re.sub(r"\s+", " ", label).strip().lower()] = url

sessions = {}
seen_webhook_messages = set()
sessions_lock = threading.Lock()


def meta_access_token():
    return os.getenv("META_ACCESS_TOKEN", "").strip().strip('"').strip("'")


def meta_instagram_account_id():
    for name in ("META_INSTAGRAM_ACCOUNT_ID", "INSTAGRAM_ACCOUNT_ID", "META_PAGE_ID", "PAGE_ID"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def meta_graph_host():
    value = os.getenv("META_GRAPH_HOST", "graph.instagram.com").strip().rstrip("/")
    return value.replace("https://", "").replace("http://", "")


def normalize(text):
    text = text.lower().strip()
    replacements = str.maketrans("áéíóúüñ", "aeiouun")
    return re.sub(r"[^a-z0-9]+", " ", text.translate(replacements)).strip()


def match_option(text, selected_id=None):
    candidates = {
        "guadalupe": ["guadalupe", "guad", "gpe"],
        "santa_anita": ["bosque santa anita", "santa anita", "santa", "bosque"],
        "wellness": ["wellness", "bienestar", "spa"],
        "hyrox": ["hyrox", "crossfit", "competencia", "reto"],
    }
    normalized = normalize(selected_id or text)
    for option, aliases in candidates.items():
        if any(alias in normalized or normalized in alias for alias in aliases):
            return option
    return None


def get_session(phone):
    with sessions_lock:
        if phone not in sessions:
            sessions[phone] = {"phase": "welcome", "option": None, "registration": {}, "greeted": False}
        return sessions[phone]


def reset_session(phone):
    with sessions_lock:
        sessions[phone] = {"phase": "welcome", "option": None, "registration": {}, "greeted": False}


def option_label(option):
    return {"guadalupe": "Guadalupe", "santa_anita": "Bosque Santa Anita", "wellness": "Wellness", "hyrox": "Hyrox"}.get(option, option)


def link_for(option):
    if option == "guadalupe":
        return links.get("guadalupe", "")
    if option == "santa_anita":
        return links.get("santa anita", "")
    if option == "wellness":
        return links.get("wellness", "")
    return links.get("guadalupe", "")


def options_menu():
    return {"type": "interactive", "interactive": {
        "type": "list",
        "body": {"text": "Elige la opción que deseas conocer:"},
        "action": {"button": "Ver opciones", "sections": [{"title": "Full Training", "rows": [
            {"id": "guadalupe", "title": "Guadalupe"},
            {"id": "santa_anita", "title": "Bosque Santa Anita"},
            {"id": "wellness", "title": "Wellness"},
            {"id": "hyrox", "title": "Hyrox"}
        ]}]}
    }}


def branch_menu():
    return {"type": "interactive", "interactive": {
        "type": "button",
        "body": {"text": "HYROX está listo para ti. ¿En qué sucursal te gustaría entrenar?"},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": "guadalupe", "title": "Guadalupe"}},
            {"type": "reply", "reply": {"id": "santa_anita", "title": "Santa Anita"}}
        ]}
    }}


def valid_name(value):
    parts = value.strip().split()
    return len(parts) >= 2 and re.fullmatch(r"[\w\s.'’\-]+", value.strip(), re.UNICODE) is not None and 3 <= len(value.strip()) <= 100


def valid_phone(value):
    digits = re.sub(r"\D", "", value)
    return 8 <= len(digits) <= 15


def valid_email(value):
    return re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]{2,}", value.strip(), re.I) is not None


def valid_birth_year(value):
    if not re.fullmatch(r"\d{4}", value.strip()):
        return False
    year = int(value)
    current = datetime.now().year
    return current - 100 <= year <= current - 14


def append_registration(registration, option, identifier):
    url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL")
    if not url:
        return None
    now = datetime.now()
    payload = {
        "action": "upsert_lead",
        "token": os.getenv("GOOGLE_SHEET_TOKEN", "0710"),
        "lead": {
            "year": str(now.year),
            "month": f"{now.month:02d}",
            "day": f"{now.day:02d}",
            "hour": f"{now.hour:02d}:00",
            "name": registration["name"],
            "phone": registration["phone"],
            "mail": registration["email"],
            "email": registration["email"],
            "birth_date": str(registration["birthYear"]),
            "program": option_label(option),
            "branch": option_label(option) if option in ("guadalupe", "santa_anita") else ("Guadalupe" if option == "wellness" else "Sin especificar"),
            "source": "Instagram",
            "identifier": str(identifier),
        },
    }
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "sheet_rejected_payload"))
    return payload


def enter_option(session, phone):
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    option = session["option"]

    if option == "guadalupe":
        session["phase"] = "register_name"
        result = [{"type": "text", "text": {"body": GUADALUPE}}]
        if base:
            result.append({"type": "image", "image": {"link": f"{base}/media/precios_guadalupe.png", "caption": "Precios de Guadalupe"}})
        result.append({"type": "text", "text": {"body": "¡Gran elección! Primero hagamos tu registro rápido. ¿Cuál es tu nombre completo?"}})
        return result

    if option == "santa_anita":
        session["phase"] = "register_name"
        result = [{"type": "text", "text": {"body": SANTA_ANITA}}]
        if base:
            result.append({"type": "image", "image": {"link": f"{base}/media/precios_bosque_santa_anita.png", "caption": "Precios de Bosque Santa Anita"}})
        result.append({"type": "text", "text": {"body": "¡Excelente! Vamos con tu registro. ¿Cuál es tu nombre completo?"}})
        return result

    if option == "wellness":
        session["phase"] = "register_name"
        result = [{"type": "text", "text": {"body": "Nuestro espacio Wellness de Full solo está disponible en la sucursal Guadalupe. ¡Es momento de darle balance a tanta fuerza! 🧘💪"}}]
        if base:
            result.append({"type": "image", "image": {"link": f"{base}/media/precios_guadalupe.png", "caption": "Precios de Guadalupe"}})
        result.append({"type": "text", "text": {"body": "Para registrarte en Wellness y comenzar tu plan, dime tu nombre completo."}})
        return result

    if option == "hyrox":
        session["phase"] = "hyrox_branch"
        return [{"type": "text", "text": {"body": HYROX}}, branch_menu()]
    return []


def collect_registration(session, text, identifier):
    phase = session["phase"]
    registration = session["registration"]

    if phase == "register_name":
        if not valid_name(text):
            return [{"type": "text", "text": {"body": "Necesito tu nombre completo (nombre y apellido). Ejemplo: Ana López."}}]
        registration["name"] = text.strip()
        session["phase"] = "register_phone"
        return [{"type": "text", "text": {"body": "¿Cuál es tu número de teléfono? Puedes escribirlo con lada."}}]

    if phase == "register_phone":
        if not valid_phone(text):
            return [{"type": "text", "text": {"body": "Ese teléfono no parece válido. Escríbelo con entre 8 y 15 dígitos."}}]
        registration["phone"] = text.strip()
        session["phase"] = "register_email"
        return [{"type": "text", "text": {"body": "Ahora necesito tu correo electrónico."}}]

    if phase == "register_email":
        if not valid_email(text):
            return [{"type": "text", "text": {"body": "Revisa el correo, por favor. Debe tener este formato: nombre@dominio.com"}}]
        registration["email"] = text.strip().lower()
        session["phase"] = "register_birthYear"
        return [{"type": "text", "text": {"body": "¿Cuál es tu año de nacimiento? Escríbelo con 4 dígitos, por ejemplo: 1995."}}]

    if phase == "register_birthYear":
        if not valid_birth_year(text):
            return [{"type": "text", "text": {"body": "Escribe un año de nacimiento válido con 4 dígitos."}}]
        registration["birthYear"] = text.strip()
        session["phase"] = "complete"
        sheet_error = None
        try:
            append_registration(registration, session["option"], identifier)
        except Exception as error:
            sheet_error = str(error)
            app.logger.error("Google Sheets append failed: %s", sheet_error)

        link = link_for(session["option"])
        warning = "\n\nNota técnica: hubo un problema temporal al guardar el registro." if sheet_error else ""
        return [{"type": "text", "text": {"body": f"¡Registro completado, {registration['name']}! 🔥 Ya estás un paso más cerca de tu mejor versión.{warning}\n\nPara confirmar tu clase o atención personalizada, escríbenos por WhatsApp:\n{link}"}}]
    return [{"type": "text", "text": {"body": "No entendí tu respuesta. Podemos empezar de nuevo con “Inicio”."}}]


def process_incoming(text, selected_id, phone):
    session = get_session(phone)
    text = (text or "").strip()

    if re.fullmatch(r"(?i)(reiniciar|reset|inicio|menu|menú)", text) or selected_id == "menu":
        reset_session(phone)
        session = get_session(phone)
        session["greeted"] = True
        return [{"type": "text", "text": {"body": WELCOME}}, options_menu()]

    if session["phase"] == "welcome":
        if not session["greeted"]:
            session["greeted"] = True
            option = match_option(text, selected_id)
            if not option:
                return [{"type": "text", "text": {"body": WELCOME}}, options_menu()]
            session["option"] = option
            return enter_option(session, phone)

        option = match_option(text, selected_id)
        if not option:
            return [{"type": "text", "text": {"body": "Para darte la mejor ruta, elige una de las cuatro opciones — ¡prometo no perseguirte por las demás! 😄"}}, options_menu()]
        session["option"] = option
        return enter_option(session, phone)

    if session["phase"] == "hyrox_branch":
        branch = match_option(text, selected_id)
        if branch not in ("guadalupe", "santa_anita"):
            return [{"type": "text", "text": {"body": "Elige una sucursal para que te muestre horarios y precios."}}, branch_menu()]
        session["option"] = branch
        return enter_option(session, phone)

    if session["phase"].startswith("register_"):
        return collect_registration(session, text, phone)

    if session["phase"] == "complete":
        link = link_for(session["option"])
        return [{"type": "text", "text": {"body": f"Ya quedó tu registro en modo “lista para entrenar” 😄 Para confirmar disponibilidad, precios o resolver cualquier duda, escríbnos por WhatsApp:\n{link}"}}]

    link = link_for(session["option"])
    return [{"type": "text", "text": {"body": "No tengo esa respuesta registrada, pero sí tengo el camino directo a nuestro equipo. Escríbenos por WhatsApp:"}}, {"type": "text", "text": {"body": link}}]


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/status")
def status():
    token = meta_access_token()
    account_id = meta_instagram_account_id()
    return jsonify(
        status="ok",
        instagram_configured=bool(token and "replace-with" not in token.lower() and account_id),
        token_present=bool(token),
        token_length=len(token),
        account_id_present=bool(account_id),
        webhook_signature_configured=bool(os.getenv("WEBHOOK_APP_SECRET")),
        verify_token_configured=bool(os.getenv("VERIFY_TOKEN")),
        google_sheets_configured=bool(os.getenv("GOOGLE_SHEET_WEBHOOK_URL") and os.getenv("GOOGLE_SHEET_TOKEN")),
        meta_graph_host=meta_graph_host(),
    )


@app.get("/diagnostics/meta")
def meta_diagnostics():
    token = meta_access_token()
    if not token:
        return jsonify(ok=False, error="missing_access_token"), 200
    if "replace-with" in token.lower():
        return jsonify(ok=False, error="placeholder_access_token"), 200

    host = meta_graph_host()
    try:
        response = requests.get(
            f"https://{host}/v27.0/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if not response.ok:
            data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            return jsonify(ok=False, http_status=response.status_code, meta_error=(data.get("error") or {}).get("message", response.text[:300])), 200
        data = response.json()
        return jsonify(ok=True, http_status=response.status_code, account_name=data.get("name"), account_id=data.get("id")), 200
    except Exception as error:
        return jsonify(ok=False, error="request_failed", detail=str(error)), 200


@app.get("/media/<filename>")
def media(filename):
    if filename not in {"precios_guadalupe.png", "precios_bosque_santa_anita.png"}:
        return "", 404
    return send_from_directory(IMAGES, filename)


@app.get("/webhook")
def verify():
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
        return request.args.get("hub.challenge", ""), 200
    return "Forbidden", 403


def valid_signature(raw_body):
    secret = os.getenv("WEBHOOK_APP_SECRET")
    if not secret:
        return True
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, f"sha256={digest}")


def send_meta_messages(instagram_id, messages):
    token = meta_access_token()
    instagram_account_id = meta_instagram_account_id()
    graph_host = meta_graph_host()

    if not token or "replace-with" in token.lower():
        app.logger.error("META_ACCESS_TOKEN is missing or still contains a placeholder")
        return
    if not instagram_account_id:
        app.logger.error("META_INSTAGRAM_ACCOUNT_ID, INSTAGRAM_ACCOUNT_ID or META_PAGE_ID is missing")
        return

    for message in messages:
        payload = {"recipient": {"id": instagram_id}}

        if message.get("type") == "text":
            payload["message"] = {"text": message["text"]["body"]}
        elif message.get("type") == "image":
            payload["message"] = {
                "attachment": {
                    "type": "image",
                    "payload": {"url": message["image"]["link"]},
                }
            }
        elif message.get("type") == "interactive":
            interactive = message["interactive"]
            quick_replies = []
            if interactive["type"] == "list":
                for section in interactive["action"].get("sections", []):
                    for row in section.get("rows", []):
                        quick_replies.append({
                            "content_type": "text",
                            "title": row["title"][:20],
                            "payload": row["id"],
                        })
            else:
                for button in interactive["action"].get("buttons", []):
                    reply = button["reply"]
                    quick_replies.append({
                        "content_type": "text",
                        "title": reply["title"][:20],
                        "payload": reply["id"],
                    })
            payload["message"] = {
                "text": interactive["body"]["text"],
                "quick_replies": quick_replies[:13],
            }

        if "message" not in payload:
            continue

        app.logger.info("Sending Instagram %s message to %s", message.get("type"), instagram_id)
        response = requests.post(
            f"https://{graph_host}/v27.0/{instagram_account_id}/messages",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if not response.ok and message.get("type") == "image":
            image_url = message["image"]["link"]
            app.logger.warning("Image retry for %s using attachments format", image_url)
            payload["message"] = {"attachments": {"type": "image", "payload": {"url": image_url}}}
            response = requests.post(
                f"https://{graph_host}/v27.0/{instagram_account_id}/messages",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
                timeout=10,
            )
        try:
            response.raise_for_status()
            app.logger.info("Instagram message sent to %s: %s", instagram_id, response.text[:500])
        except Exception:
            app.logger.error("Instagram send failed to %s: HTTP %s body=%s", instagram_id, getattr(response, "status_code", "unknown"), getattr(response, "text", "")[:1000])
            continue


@app.post("/webhook")
def webhook():
    raw = request.get_data(cache=True)
    body = request.get_json(silent=True) or {}
    app.logger.info("Instagram webhook received: entries=%s signature=%s", len(body.get("entry", [])), bool(request.headers.get("X-Hub-Signature-256")))

    if not valid_signature(raw):
        app.logger.warning("Instagram webhook signature rejected")
        return "Forbidden", 403

    event_count = 0
    for entry in body.get("entry", []):
        messaging_events = list(entry.get("messaging", []) or [])
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            messaging_events.extend(value.get("messaging", []) or [])
            for message in value.get("messages", []) or []:
                messaging_events.append({
                    "sender": {"id": str(message.get("from", ""))},
                    "recipient": {"id": str(message.get("to", ""))},
                    "message": {"text": message.get("text", {}).get("body", "")},
                })

        for event in messaging_events:
            event_count += 1
            if event.get("message", {}).get("is_echo"):
                continue

            message = event.get("message", {}) or {}
            message_id = str(message.get("mid") or message.get("message_id") or "")
            if message_id:
                if message_id in seen_webhook_messages:
                    app.logger.info("Duplicate Instagram webhook message ignored: %s", message_id)
                    continue
                seen_webhook_messages.add(message_id)
                if len(seen_webhook_messages) > 5000:
                    seen_webhook_messages.clear()

            sender = event.get("sender", {}) or {}
            instagram_id = str(sender.get("id", ""))
            if not instagram_id:
                app.logger.warning("Instagram webhook event without sender ID: %s", event)
                continue

            text = ""
            selected_id = None
            message = event.get("message", {}) or {}
            text = message.get("text", "")
            quick_reply = message.get("quick_reply") or {}
            if quick_reply:
                selected_id = quick_reply.get("payload")

            postback = event.get("postback") or {}
            if postback:
                selected_id = postback.get("payload")
                text = postback.get("title", text)

            app.logger.info("Instagram message from %s: text=%r quick_reply=%r", instagram_id, text, selected_id)
            try:
                replies = process_incoming(text, selected_id, instagram_id)
            except Exception:
                app.logger.exception("Webhook conversation processing failed")
                try:
                    send_meta_messages(instagram_id, [{
                        "type": "text",
                        "text": {"body": "Tuvimos un pequeño tropiezo técnico. Intenta de nuevo o escríbeme por aquí."},
                    }])
                except Exception:
                    app.logger.exception("Could not send webhook fallback message")
                continue

            try:
                send_meta_messages(instagram_id, replies)
            except Exception:
                app.logger.exception("Could not send Instagram reply; no fallback loop will be started")

    app.logger.info("Instagram webhook processed: events=%s", event_count)
    return "", 200


@app.get("/privacy")
def privacy():
    html = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Política de Privacidad | Full Training</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 820px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #222; }
    h1, h2 { color: #111; }
  </style>
</head>
<body>
  <h1>Política de Privacidad</h1>
  <p><strong>Última actualización:</strong> 24 de noviembre de 2026</p>

  <h2>Responsable</h2>
  <p>Full Training administra este chatbot de atención y registro mediante Instagram Direct.</p>

  <h2>Información que recopilamos</h2>
  <p>Cuando el usuario completa el registro, podemos recopilar nombre completo, número telefónico, correo electrónico, año de nacimiento, sucursal o programa de interés y el identificador técnico proporcionado por Meta para mantener la conversación.</p>

  <h2>Uso de la información</h2>
  <p>Los datos se usan para responder solicitudes, proporcionar información sobre sucursales y horarios, registrar interés comercial y permitir el seguimiento de atención por WhatsApp.</p>

  <h2>Almacenamiento</h2>
  <p>La información enviada al finalizar el registro puede almacenarse en Google Sheets mediante la integración autorizada. Los datos se conservan únicamente para fines de atención y gestión comercial.</p>

  <h2>Servicios externos</h2>
  <p>Este servicio utiliza Meta/Instagram Messaging para recibir y enviar mensajes y Google Sheets para almacenar los registros. Ambos servicios pueden aplicar sus propias políticas y medidas de seguridad.</p>

  <h2>Eliminación de datos</h2>
  <p>Para solicitar consulta, corrección o eliminación de datos, el usuario puede comunicarse con Full Training a través del canal de atención que recibió durante la conversación.</p>

  <h2>Derechos del usuario</h2>
  <p>El usuario puede solicitar acceso a sus datos, corrección de información incorrecta o eliminación de su registro.</p>

  <h2>Seguridad</h2>
  <p>Se utilizan comunicaciones HTTPS y credenciales administrativas protegidas para limitar el acceso a los datos. Ninguna clave secreta se publica en esta página.</p>

  <h2>Cambios</h2>
  <p>Esta política puede actualizarse cuando cambien el funcionamiento del chatbot o los servicios utilizados.</p>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}
