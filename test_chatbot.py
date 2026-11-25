import os
import unittest
from unittest.mock import patch

from app import append_registration, process_incoming, get_session


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
        invalid = process_incoming("Ana", None, "test-guadalupe")
        self.assertIn("nombre completo", invalid[0]["text"]["body"])
        valid = process_incoming("Ana López", None, "test-guadalupe")
        self.assertIn("teléfono", valid[0]["text"]["body"])

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

    def test_status_endpoint(self):
        from app import app

        response = app.test_client().get("/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("instagram_configured", response.get_json())

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
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
