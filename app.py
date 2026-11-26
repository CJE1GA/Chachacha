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
idle_timers = {}
sessions_lock = threading.Lock()


def cancel_idle_farewell(phone):
    timer = idle_timers.pop(phone, None)
    if timer:
        timer.cancel()


def idle_farewell_for_option(option):
    if option == "wellness":
        return "Tu cita Wellness quedó en camino 🧘✨ Cuando quieras volver, aquí estaremos con calma y buena vibra. ¡Hasta pronto!"
    if option == "santa_anita":
        return "¡Listo, guerrero! Te esperamos en Bosque Santa Anita con tenis puestos y buena actitud 💪🏋️ ¡Nos vemos entrenando!"
    if option == "guadalupe":
        return "¡Dale, guerrero! Guadalupe ya tiene ganas de verte entrenar 🔥 Que le ganes a las excusas y nos vemos a Full 💪"
    if option == "hyrox":
        return "¡Reta tus límites! HYROX está listo para ti ⚡ Cuando quieras volver, seguimos en la zona de combate 😄"
    return "Gracias por conversar con Full Training 💪 Fue un gusto ayudarte. ¡Aquí estaremos cuando quieras dar el siguiente paso!"


def schedule_idle_farewell(phone, option):
    cancel_idle_farewell(phone)

    def send_farewell():
        with sessions_lock:
            current = sessions.get(phone)
            if current is None or current.get("phase") != "complete" or current.get("option") != option:
                idle_timers.pop(phone, None)
                return
            idle_timers.pop(phone, None)
        try:
            send_meta_messages(phone, [{"type": "text", "text": {"body": idle_farewell_for_option(option)}}])
        except Exception:
            app.logger.exception("Could not send idle farewell")

    timer = threading.Timer(30.0, send_farewell)
    idle_timers[phone] = timer
    timer.daemon = True
    timer.start()


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


def wellness_sheet_request(action, lead=None, **fields):
    url = os.getenv("GOOGLE_SHEET_WEBHOOK_URL")
    if not url:
        raise RuntimeError("missing_google_sheet_webhook")
    payload = {
        "action": action,
        "token": os.getenv("GOOGLE_SHEET_TOKEN", "0710"),
        "sheet": "Wellness",
        **fields,
    }
    if lead:
        payload["lead"] = lead
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "wellness_sheet_rejected_payload"))
    return data


def get_wellness_slots():
    data = wellness_sheet_request("list_wellness_slots")
    return data.get("slots", [])


def reserve_wellness_slot(slot, registration, identifier):
    return wellness_sheet_request(
        "reserve_wellness_slot",
        lead={"name": registration["name"]},
        day=slot["day"],
        time=slot["time"],
        row=slot.get("row"),
        identifier=str(identifier),
    )


def format_wellness_slots(slots):
    if not slots:
        return "Por ahora no quedan horarios Wellness disponibles."
    grouped = {}
    for slot in slots:
        grouped.setdefault(slot["day"], []).append(slot["time"])
    lines = ["Estos son los horarios Wellness disponibles, a tu ritmo 🧘✨"]
    for day, times in grouped.items():
        lines.append(f"{day}: " + " | ".join(times))
    lines.append("Responde con el día y la hora que prefieras, por ejemplo: Martes 10:00.")
    return "\n".join(lines)


def find_wellness_slot(text, slots):
    normalized_text = normalize(text)
    compact_text = re.sub(r"[^0-9]", "", text)

    for slot in slots:
        day = normalize(slot["day"])
        slot_time = str(slot["time"]).strip()
        compact_slot_time = re.sub(r"[^0-9]", "", slot_time)
        if day not in normalized_text:
            continue
        if compact_text and (compact_text in compact_slot_time or compact_slot_time.startswith(compact_text)):
            return slot
    return None


def enter_option(session, phone):
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    option = session["option"]

    if option == "guadalupe":
        session["phase"] = "offer_sample"
        result = [{"type": "text", "text": {"body": GUADALUPE}}]
        if base:
            result.append({"type": "image", "image": {"link": f"{base}/media/precios_guadalupe.png", "caption": "Precios de Guadalupe"}})
        result.append(sample_class_menu())
        return result

    if option == "santa_anita":
        session["phase"] = "offer_sample"
        result = [{"type": "text", "text": {"body": SANTA_ANITA}}]
        if base:
            result.append({"type": "image", "image": {"link": f"{base}/media/precios_bosque_santa_anita.png", "caption": "Precios de Bosque Santa Anita"}})
        result.append(sample_class_menu())
        return result

    if option == "wellness":
        session["phase"] = "offer_wellness"
        result = [{"type": "text", "text": {"body": "Nuestro rincón Wellness está en Guadalupe, esperando a que le des una pausa a tanto ardor fitness 🧘✨ Aquí recargas cuerpo y mente, sin prisas y con buena vibra. ¿Te agendamos una cita?"}}]
        result.append(wellness_appointment_menu())
        return result

    if option == "hyrox":
        session["phase"] = "hyrox_branch"
        return [{"type": "text", "text": {"body": HYROX}}, branch_menu()]
    return []


def collect_registration(session, text, identifier):
    phase = session["phase"]
    registration = session["registration"]
    prompts = registration_prompts(session["option"])

    if phase == "register_name":
        if not valid_name(text):
            return [{"type": "text", "text": {"body": "¡Tranquil@! Necesito tu nombre completo con nombre y apellido, por ejemplo: Ana López 😊"}}]
        registration["name"] = text.strip()
        session["phase"] = "register_phone"
        return [{"type": "text", "text": {"body": prompts["phone"]}}]

    if phase == "register_phone":
        if not valid_phone(text):
            return [{"type": "text", "text": {"body": "Ese teléfono casi llega, pero necesito entre 8 y 15 dígitos. Puedes ponerlo con lada y sin espacios 😊"}}]
        registration["phone"] = text.strip()
        session["phase"] = "register_email"
        return [{"type": "text", "text": {"body": prompts["email"]}}]

    if phase == "register_email":
        if not valid_email(text):
            return [{"type": "text", "text": {"body": "Ese correo no parece completo. Escríbelo así: nombre@dominio.com, sin espacios 😊"}}]
        registration["email"] = text.strip().lower()
        session["phase"] = "register_birthYear"
        return [{"type": "text", "text": {"body": prompts["birthYear"]}}]

    if phase == "register_birthYear":
        if not valid_birth_year(text):
            return [{"type": "text", "text": {"body": "¡Ya casi terminamos! Escribe un año válido con 4 dígitos, por ejemplo: 1995 😊"}}]
        registration["birthYear"] = text.strip()
        sheet_error = None
        try:
            append_registration(registration, session["option"], identifier)
        except Exception as error:
            sheet_error = str(error)
            app.logger.error("Google Sheets append failed: %s", sheet_error)

        if session["option"] == "wellness":
            try:
                slots = get_wellness_slots()
            except Exception as error:
                app.logger.error("Wellness schedule fetch failed: %s", error)
                slots = []
            session["wellness_slots"] = slots
            session["phase"] = "wellness_schedule"
            if slots:
                return [{"type": "text", "text": {"body": format_wellness_slots(slots)}}]
            return [{"type": "text", "text": {"body": "Tu registro quedó guardado 🧘✨ No pude consultar los horarios disponibles. Escribe “Horarios” para intentarlo de nuevo, o continúa por WhatsApp: " + link_for("wellness")}}]

        session["phase"] = "complete"
        link = link_for(session["option"])
        warning = "\n\nNota técnica: hubo un problema temporal al guardar el registro." if sheet_error else ""
        completion = prompts["complete"].format(name=registration["name"], warning=warning, link=link)
        schedule_idle_farewell(identifier, session["option"])
        return [{"type": "text", "text": {"body": completion}}]
    return [{"type": "text", "text": {"body": "No entendí tu respuesta. Podemos empezar de nuevo con “Inicio”."}}]


def process_incoming(text, selected_id, phone):
    cancel_idle_farewell(phone)
    session = get_session(phone)
    text = (text or "").strip()

    normalized_reset = normalize(text)
    thanks = ("gracias", "muchas gracias", "mil gracias", "te agradezco", "gracias por todo")
    if normalized_reset in thanks or normalized_reset.startswith(thanks) or any(phrase in normalized_reset for phrase in ("muchas gracias", "mil gracias", "gracias por")):
        previous_option = session.get("option")
        reset_session(phone)
        if previous_option == "wellness":
            return [{"type": "text", "text": {"body": "¡A tu ritmo, siempre! Gracias por confiar en nuestro espacio Wellness. Que tu día tenga mucho equilibrio, buena vibra y una dosis de calma 🧘✨ ¡Hasta tu cita!"}}]
        return [{"type": "text", "text": {"body": "¡Un gusto ayudarte! Gracias a ti por confiar en Full Training. Que tengas un excelente día y aquí estaremos para entrenar contigo 💪 ¡Hasta pronto!"}}]

    if normalized_reset in {"reiniciar", "reset", "inicio", "menu", "menu principal", "hola", "holaa", "hola buenos dias", "buenos dias", "buenas tardes", "buenas noches", "hey", "hi"} or selected_id == "menu":
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

    if session["phase"] == "offer_sample":
        if selected_id == "wellness" or match_option(text) == "wellness":
            session["option"] = "wellness"
            return enter_option(session, phone)

        wants_sample = selected_id == "clase_muestra" or normalize(text) in {"quiero mi clase muestra", "quiero clase muestra", "clase muestra", "si", "sí", "quiero", "me interesa"}
        if not wants_sample:
            if session["option"] == "guadalupe":
                return [{"type": "text", "text": {"body": "¡Claro! Puedes elegir una clase muestra o cambiarte a Wellness. Tú decides con calma 😄"}}, guadalupe_switch_menu()]
            return [{"type": "text", "text": {"body": "¡Claro! Toca el botón para reservar tu clase muestra o dime “Quiero mi clase muestra” 😄"}}, sample_class_menu()]
        session["phase"] = "register_name"
        prompts = registration_prompts(session["option"])
        return [{"type": "text", "text": {"body": prompts["name"]}}]

    if session["phase"] == "offer_wellness":
        wants_appointment = selected_id == "agendar_cita_wellness" or normalize(text) in {"quiero agendar cita", "agendar cita", "cita wellness", "si", "sí", "quiero", "me interesa"}
        if not wants_appointment:
            return [{"type": "text", "text": {"body": "Sin estrés: toca “Quiero agendar cita” o escríbeme “Quiero agendar cita” y te doy el siguiente paso."}}, wellness_appointment_menu()]
        session["phase"] = "register_name"
        return [{"type": "text", "text": {"body": "¡Cita en camino! Para apartarla con calma, ¿cuál es tu nombre completo?"}}]

    if session["phase"].startswith("register_"):
        return collect_registration(session, text, phone)

    if session["phase"] == "wellness_schedule":
        if normalize(text) in {"horarios", "horario", "disponibles", "ver horarios"}:
            try:
                slots = get_wellness_slots()
                session["wellness_slots"] = slots
                return [{"type": "text", "text": {"body": format_wellness_slots(slots)}}]
            except Exception as error:
                app.logger.error("Wellness schedule refresh failed: %s", error)
                return [{"type": "text", "text": {"body": "No pude refrescar la agenda Wellness ahora mismo. Inténtalo otra vez en un momento o escríbeme “Horarios”."}}]

        slots = session.get("wellness_slots", [])
        slot = find_wellness_slot(text, slots)
        if not slot:
            try:
                slots = get_wellness_slots()
                session["wellness_slots"] = slots
            except Exception:
                slots = session.get("wellness_slots", [])
            return [{"type": "text", "text": {"body": "Ese horario no está disponible o no reconocí el día y hora. Aquí tienes las opciones libres, sin perder la calma 🧘"}}, {"type": "text", "text": {"body": format_wellness_slots(slots)}}]

        try:
            result = reserve_wellness_slot(slot, session["registration"], phone)
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "reservation_failed"))
        except Exception as error:
            app.logger.error("Wellness reservation failed: %s", error)
            try:
                slots = get_wellness_slots()
                session["wellness_slots"] = slots
            except Exception:
                slots = session.get("wellness_slots", [])
            return [{"type": "text", "text": {"body": "Ese horario acaba de ocuparse o no pude apartarlo. Te comparto los disponibles actuales para que elijas otro momento 😊"}}, {"type": "text", "text": {"body": format_wellness_slots(slots)}}]

        session["phase"] = "complete"
        link = link_for("wellness")
        schedule_idle_farewell(phone, "wellness")
        return [{"type": "text", "text": {"body": f"¡Listo, {session['registration']['name']}! Tu cita Wellness quedó apartada para {slot['day']} a las {slot['time']} 🧘✨ Guarda ese momento para ti.\n\nSi necesitas cambiarla o confirmar algún detalle, escríbenos por WhatsApp:\n{link}"}}]

    if session["phase"] == "complete":
        link = link_for(session["option"])
        return [{"type": "text", "text": {"body": f"Ya quedó tu registro en modo “lista para entrenar” 😄 Para confirmar disponibilidad, precios o resolver cualquier duda, escríbemeos por WhatsApp:\n{link}"}}]

    link = link_for(session["option"])
    return [{"type": "text", "text": {"body": "No pasa nada 😊 Si quieres podemos seguir desde el inicio escribiendo “Inicio”, o te llevo directo con nuestro equipo por WhatsApp:"}}, {"type": "text", "text": {"body": link}}]


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

        for event in messaging_events:
            event_count += 1
            if event.get("message", {}).get("is_echo"):
                continue
            if any(field in event for field in ("delivery", "read", "reaction")):
                continue

            sender = event.get("sender", {}) or {}
            recipient = event.get("recipient", {}) or {}
            instagram_id = str(sender.get("id", ""))
            account_id = str(recipient.get("id", ""))

            message = event.get("message", {}) or {}
            message_id = str(message.get("mid") or message.get("message_id") or "")
            timestamp = str(event.get("timestamp") or "")
            fallback_key = "|".join((
                instagram_id,
                account_id,
                timestamp,
                message_id,
                str(message.get("text", "")),
                str(message.get("quick_reply", {}).get("payload", "")),
                str(event.get("postback", {}).get("payload", "")),
            ))

            dedupe_key = message_id or fallback_key
            if dedupe_key in seen_webhook_messages:
                app.logger.info("Duplicate Instagram webhook message ignored: %s", dedupe_key)
                continue
            seen_webhook_messages.add(dedupe_key)
            if len(seen_webhook_messages) > 5000:
                seen_webhook_messages.clear()

            if not instagram_id:
                app.logger.warning("Instagram webhook event without sender ID: %s", event)
                continue

            text = str(message.get("text", "") or "")
            selected_id = None
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


def sample_class_menu():
    return {"type": "interactive", "interactive": {
        "type": "button",
        "body": {"text": "¿Te gustaría reservar una clase muestra?"},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": "clase_muestra", "title": "Quiero clase muestra"}}
        ]}
    }}


def wellness_appointment_menu():
    return {"type": "interactive", "interactive": {
        "type": "button",
        "body": {"text": "¿List@ para una cita de Wellness?"},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": "agendar_cita_wellness", "title": "Quiero agendar cita"}}
        ]}
    }}


def guadalupe_switch_menu():
    return {"type": "interactive", "interactive": {
        "type": "button",
        "body": {"text": "¿Quieres entrenar con nosotros o recargar tu bienestar?"},
        "action": {"buttons": [
            {"type": "reply", "reply": {"id": "clase_muestra", "title": "Quiero clase muestra"}},
            {"type": "reply", "reply": {"id": "wellness", "title": "Cambiar a Wellness"}}
        ]}
    }}


def registration_prompts(option):
    if option == "wellness":
        return {
            "name": "🧘 Primero, ¿cómo te llamas? Escribe tu nombre completo para preparar tu momento de calma.",
            "phone": "¿Cuál es el número donde podamos confirmar tu cita Wellness? Puedes ponerlo con lada 📲",
            "email": "Ahora tu correo, para que tu cita Wellness quede bien guardadita ✉️ (ejemplo: nombre@dominio.com)",
            "birthYear": "Por último, ¿cuál es tu año de nacimiento? Escríbelo con 4 dígitos, por ejemplo: 1995 🌿",
            "complete": "Listo, {name}: tu espacio de Wellness ya tiene tu registro 🧘✨ Estamos preparando una experiencia con equilibrio, buena vibra y cero prisa.{warning}\n\nPara confirmar horario y atención personalizada, escríbenos por WhatsApp:\n{link}",
        }
    if option == "santa_anita":
        return {
            "name": "🏋️ ¡Dale! ¿Cuál es tu nombre completo? Así guardamos tu lugar en Bosque Santa Anita.",
            "phone": "¿Cuál es tu número de teléfono con lada? Te daremos la ruta para que llegues a entrenar con toda la actitud 📲",
            "email": "Ahora tu correo electrónico, sin sorpresas ni excusas: nombre@dominio.com ✉️",
            "birthYear": "¿Cuál es tu año de nacimiento? Escríbelo con 4 dígitos, por ejemplo: 1995 🗓️",
            "complete": "¡{name}, quedaste registrado para meterle energía en Bosque Santa Anita! 💪 La próxima meta es verte llegar con tenis listos y sonrisa ganadora.{warning}\n\nConfirma detalles de tu clase muestra por WhatsApp:\n{link}",
        }
    if option == "guadalupe":
        return {
            "name": "🔥 ¿Cuál es tu nombre completo? Vamos a ponerle nombre a tu próxima versión “Full”.",
            "phone": "¿Cuál es tu número de teléfono con lada? Lo usaremos para confirmar tu clase en Guadalupe y evitar que el banco te haga ejercicio primero 📲😄",
            "email": "Compárteme tu correo electrónico, por ejemplo: nombre@dominio.com ✉️",
            "birthYear": "Último dato: tu año de nacimiento con 4 dígitos, por ejemplo: 1995 🗓️",
            "complete": "¡Eso, {name}! Tu registro en Guadalupe está listo 🔥 Prepárate para sudar, superarte y conquistar mañana las escaleras.{warning}\n\nConfirma tu clase muestra por WhatsApp:\n{link}",
        }
    return {
        "name": "💪 ¿Cuál es tu nombre completo? Vamos a preparar tu registro.",
        "phone": "¿Cuál es tu número de teléfono con lada?",
        "email": "Compárteme tu correo electrónico, por ejemplo: nombre@dominio.com ✉️",
        "birthYear": "¿Cuál es tu año de nacimiento? Escríbelo con 4 dígitos, por ejemplo: 1995.",
        "complete": "¡Listo, {name}! Tu registro quedó completado. La siguiente meta es verte a Full entrenando.{warning}\n\nConfirma los detalles por WhatsApp:\n{link}",
    }
