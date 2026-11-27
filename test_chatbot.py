import os
import unittest
from unittest.mock import patch

from app import (append_registration, process_incoming, get_session,
                  send_meta_messages, registration_prompts,
                  idle_farewell_for_option, cancel_idle_farewell,
                  schedule_idle_farewell, find_wellness_slot,
                  format_wellness_slots, is_unsupported_wellness_action,
                  wellness_schedule_fallback, wellness_slot_start_time)


class MetaSendTests(unittest.TestCase):
    @patch.dict(os.environ, {
        "META_ACCESS_TOKEN": '  "IG_TEST_TOKEN"  ',
        "META_INSTAGRAM_ACCOUNT_ID": "ig-account",
        "META_GRAPH_HOST": "graph.instagram.com",
    })
    @patch("app.requests.post")
    def test_instagram_login_payload(self, post_mock):
        post_mock.return_value.ok = True
        post_mock.return_value.text = '{"recipient_id":"ig-user"}'
        post_mock.return_value.raise_for_status.return_value = None

        send_meta_messages("ig-user", [{"type": "text", "text": {"body": "Hola"}}])

        args, kwargs = post_mock.call_args
        self.assertIn("graph.instagram.com/v27.0/ig-account/messages", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer IG_TEST_TOKEN")

    @patch.dict(os.environ, {
            "META_ACCESS_TOKEN": "IG_TEST_TOKEN",
            "META_INSTAGRAM_ACCOUNT_ID": "ig-account",
            "META_GRAPH_HOST": "graph.instagram.com",
        })
    @patch("app.requests.post")
    def test_sample_class_quick_reply_payload(self, post_mock):
        post_mock.return_value.ok = True
        post_mock.return_value.text = '{"recipient_id":"ig-user"}'
        post_mock.return_value.raise_for_status.return_value = None

        send_meta_messages("ig-user", [{
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": "¿Te gustaría reservar una clase muestra?"},
                "action": {"buttons": [{"type": "reply", "reply": {"id": "clase_muestra", "title": "Quiero clase muestra"}}]},
            },
        }])

        args, kwargs = post_mock.call_args
        self.assertIn("/messages", args[0])
        quick_replies = kwargs["json"]["message"]["quick_replies"]
        self.assertEqual(quick_replies[0]["payload"], "clase_muestra")
        self.assertLessEqual(len(quick_replies[0]["title"]), 20)


class RegistrationPromptTests(unittest.TestCase):
    def test_wellness_prompts_are_specific(self):
        prompts = registration_prompts("wellness")
        self.assertIn("calma", prompts["name"].lower())
        self.assertIn("cita", prompts["phone"].lower())
        self.assertIn("equilibrio", prompts["complete"].lower())

    def test_branch_prompts_are_specific(self):
        guadalupe = registration_prompts("guadalupe")
        santa_anita = registration_prompts("santa_anita")
        self.assertIn("Guadalupe", guadalupe["complete"])
        self.assertIn("Bosque Santa Anita", santa_anita["complete"])


class GoogleSheetsTests(unittest.TestCase):
    @patch.dict(os.environ, {
        "GOOGLE_SHEET_WEBHOOK_URL": "https://script.google.com/macros/s/test/exec",
        "GOOGLE_SHEET_TOKEN": "0710",
    })
    @patch("app.requests.post")
    def test_google_sheet_payload(self, post_mock):
        post_mock.return_value.raise_for_status.return_value = None
        post_mock.return_value.json.return_value = {"ok": True, "identifier": "ig-test-123"}

        payload = append_registration(
            {
                "name": "Ana López",
                "phone": "3312345678",
                "email": "ana@example.com",
                "birthYear": "1995",
            },
            "guadalupe",
            "ig-test-123",
        )

        self.assertEqual(payload["action"], "upsert_lead")
        self.assertEqual(payload["token"], "0710")
        self.assertEqual(payload["lead"]["source"], "Instagram")
        self.assertEqual(payload["lead"]["identifier"], "ig-test-123")
        self.assertEqual(payload["lead"]["program"], "Guadalupe")
        post_mock.assert_called_once()


class ChatbotTests(unittest.TestCase):
    def test_greets_and_four_options(self):
        messages = process_incoming("Hola", None, "test-welcome")
        self.assertEqual(len(messages), 2)
        self.assertEqual(len(messages[1]["interactive"]["action"]["sections"][0]["rows"]), 4)

    def test_guadalupe_registers(self):
        process_incoming("Guadalupe", None, "test-guadalupe")
        sample = process_incoming("Quiero mi clase muestra", "clase_muestra", "test-guadalupe")
        self.assertIn("nombre completo", sample[0]["text"]["body"])
        invalid = process_incoming("Ana", None, "test-guadalupe")
        self.assertIn("nombre completo", invalid[0]["text"]["body"])
        valid = process_incoming("Ana López", None, "test-guadalupe")
        self.assertIn("teléfono", valid[0]["text"]["body"])

    def test_santa_anita_requests_sample_before_registration(self):
        phone = "test-santa-anita"
        process_incoming("Santa Anita", None, phone)
        messages = process_incoming("Quiero mi clase muestra", "clase_muestra", phone)
        self.assertIn("nombre completo", messages[0]["text"]["body"])

    def test_thanks_farewell(self):
        messages = process_incoming("Muchas gracias", None, "test-thanks")
        self.assertIn("Hasta pronto", messages[0]["text"]["body"])

    def test_hyrox_branch(self):
        process_incoming("Inicio", None, "test-hyrox")
        messages = process_incoming("Hyrox", None, "test-hyrox")
        self.assertEqual(messages[1]["interactive"]["type"], "button")

    def test_unknown_option(self):
        process_incoming("Inicio", None, "test-unknown")
        messages = process_incoming("volando por marte", None, "test-unknown")
        self.assertIn("elige", messages[0]["text"]["body"].lower())
        self.assertEqual(get_session("test-unknown")["phase"], "welcome")

    def test_privacy_page_is_public(self):
        from app import app

        client = app.test_client()
        response = client.get("/privacy")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.content_type)
        self.assertIn("Política de Privacidad", response.get_data(as_text=True))

    @patch("app.send_meta_messages")
    def test_instagram_webhook_accepts_messaging_event(self, send_mock):
        from app import app

        payload = {
            "object": "instagram",
            "entry": [{
                "messaging": [{
                    "sender": {"id": "ig-test-sender"},
                    "recipient": {"id": "ig-test-account"},
                    "message": {"text": "Guadalupe", "mid": "test-mid"},
                }]
            }]
        }
        response = app.test_client().post("/webhook", json=payload)
        duplicate_response = app.test_client().post("/webhook", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(send_mock.call_count, 1)

    @patch.dict(os.environ, {
            "META_ACCESS_TOKEN": "  IG_SINGLE_TOKEN  ",
            "META_INSTAGRAM_ACCOUNT_ID": "ig-single-account",
            "META_GRAPH_HOST": "graph.instagram.com",
        }, clear=False)
    def test_single_token_status(self):
        from app import app

        response = app.test_client().get("/status")
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["token_present"])
        self.assertTrue(data["account_id_present"])

    def test_status_endpoint(self):
        from app import app

        response = app.test_client().get("/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("instagram_configured", response.get_json())

    def test_hola_does_not_enter_guadalupe(self):
        phone = "test-hola-loop"
        first = process_incoming("Hola", None, phone)
        second = process_incoming("Hola", None, phone)
        self.assertIn("Bienvenido", first[0]["text"]["body"])
        self.assertIn("Elige", second[1]["interactive"]["body"]["text"])
        self.assertEqual(get_session(phone)["phase"], "welcome")

    def test_greeting_resets_stale_registration(self):
        phone = "test-stale-registration"
        process_incoming("Guadalupe", None, phone)
        messages = process_incoming("Hola", None, phone)
        self.assertIn("Bienvenido", messages[0]["text"]["body"])
        self.assertEqual(get_session(phone)["phase"], "welcome")

    def test_wellness_requests_appointment_before_registration(self):
        phone = "test-wellness"
        result = process_incoming("Wellness", None, phone)
        self.assertEqual(len(result), 2)
        self.assertIn("rincón Wellness", result[0]["text"]["body"])

        appointment = process_incoming("Quiero agendar cita", "agendar_cita_wellness", phone)
        self.assertIn("nombre completo", appointment[0]["text"]["body"])

    def test_wellness_thanks_farewell(self):
        phone = "test-wellness-thanks"
        process_incoming("Wellness", None, phone)
        messages = process_incoming("Muchas gracias", None, phone)
        self.assertIn("Hasta tu cita", messages[0]["text"]["body"])

    def test_guadalupe_can_switch_to_wellness(self):
        phone = "test-guadalupe-wellness"
        process_incoming("Guadalupe", None, phone)
        result = process_incoming("Cambiar a Wellness", "wellness", phone)
        self.assertIn("rincón Wellness", result[0]["text"]["body"])
        self.assertEqual(result[1]["interactive"]["action"]["buttons"][0]["reply"]["id"], "agendar_cita_wellness")

    def test_idle_farewells_are_option_specific(self):
        wellness = idle_farewell_for_option("wellness")
        guadalupe = idle_farewell_for_option("guadalupe")
        santa_anita = idle_farewell_for_option("santa_anita")
        self.assertIn("Wellness", wellness)
        self.assertIn("Guadalupe", guadalupe)
        self.assertIn("Santa Anita", santa_anita)

    def test_cancel_idle_farewell(self):
        phone = "test-cancel-farewell"
        with patch("app.threading.Timer") as timer_class:
            schedule_idle_farewell(phone, "guadalupe")
            cancel_idle_farewell(phone)
            timer_class.return_value.cancel.assert_called_once()

    def test_unsupported_wellness_action(self):
        self.assertTrue(is_unsupported_wellness_action(RuntimeError("unsupported_action")))
        self.assertFalse(is_unsupported_wellness_action(RuntimeError("slot_occupied")))

    def test_wellness_schedule_fallback(self):
        fallback_message = wellness_schedule_fallback()
        self.assertIn("Lo siento", fallback_message)
        self.assertIn("bienestar", fallback_message)
        self.assertIn("agendar", fallback_message)


class WellnessScheduleTests(unittest.TestCase):
    def test_find_wellness_slot(self):
        slots = [{"day": "Martes", "time": "12:00-13:00", "row": 2}, {"day": "Miercoles", "time": "13:00-14:00", "row": 3}]
        slot = find_wellness_slot("Martes 12:00", slots)
        self.assertEqual(slot["day"], "Martes")

        jueves = find_wellness_slot("Jueves 15:00", [{"day": "Jueves", "time": "15:00-16:00", "row": 5}])
        self.assertEqual(jueves["time"], "15:00-16:00")

    def test_format_wellness_slots(self):
        text = format_wellness_slots([
            {"day": "Martes", "time": "12:00-13:00", "row": 2},
            {"day": "Jueves", "time": "18:00-19:00", "row": 8},
        ])
        self.assertIn("Martes", text)
        self.assertIn("Jueves", text)

    def test_unsupported_action_fallback(self):
        self.assertTrue(is_unsupported_wellness_action(RuntimeError("unsupported_action")))
        message = wellness_schedule_fallback()
        self.assertIn("agenda automática", message)
        self.assertIn("WhatsApp", message)

    def test_wellness_range_displays_start_time_only(self):
        self.assertEqual(wellness_slot_start_time("13:00-14:00"), "13:00")
        text = format_wellness_slots([{"day": "Martes", "time": "13:00-14:00", "row": 3}])
        self.assertIn("13:00", text)
        self.assertNotIn("14:00", text)

    def test_find_wellness_slot_uses_exact_hour(self):
        slots = [
            {"day": "Martes", "time": "16:00-17:00", "row": 2},
            {"day": "Martes", "time": "17:00-18:00", "row": 3},
        ]
        slot = find_wellness_slot("Martes 17:00", slots)
        self.assertEqual(slot["time"], "17:00-18:00")
        self.assertEqual(slot["row"], 3)

    def test_find_wellness_slot_uses_exact_hour_for_thursday(self):
        slots = [
            {"day": "Jueves", "time": "17:00-18:00", "row": 7},
            {"day": "Jueves", "time": "18:00-19:00", "row": 8},
        ]
        slot = find_wellness_slot("Jueves 18:00", slots)
        self.assertEqual(slot["time"], "18:00-19:00")
        self.assertEqual(slot["row"], 8)


if __name__ == "__main__":
    unittest.main()
