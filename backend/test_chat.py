import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import HTTPException
from chat import answer, clean_latex
from engine import Twin


class ChatTest(unittest.TestCase):
    def test_missing_key(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': '', 'GROQ_API_KEY': ''}), self.assertRaises(HTTPException):
            answer('Current COD?', [], Twin().snapshot(), None)

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test', 'GROQ_API_KEY': ''})
    @patch('chat.urlopen')
    def test_current_snapshot_sent(self, send):
        snap = Twin().snapshot()
        send.return_value = io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"Test reply"}]}}]}')
        self.assertEqual(answer('Current COD?', [], snap, None), 'Test reply')
        body = json.loads(send.call_args.args[0].data)
        context = body['systemInstruction']['parts'][0]['text']
        self.assertIn(json.dumps(snap['tanks']['outlet']['quality']), context)
        self.assertNotIn('"history"', context)

    @patch.dict(os.environ, {'GEMINI_API_KEY': 'bad-gemini', 'GROQ_API_KEY': 'good-groq'})
    @patch('chat.urlopen')
    def test_groq_fallback(self, send):
        snap = Twin().snapshot()
        # First call fails (Gemini HTTP 503), second call succeeds (Groq)
        send.side_effect = [
            HTTPError('url', 503, 'Unavailable', {}, io.BytesIO(b'')),
            io.BytesIO(b'{"choices":[{"message":{"content":"Groq fallback reply"}}]}')
        ]
        reply, provider = answer('Check alarms', [], snap, None, return_provider=True)
        self.assertEqual(reply, 'Groq fallback reply')
        self.assertEqual(provider, 'Groq (fallback)')

    def test_clean_latex(self):
        raw = "At $t = 49.0\\text{ s}$, BOD is $35.0\\text{ mg/L}$:t{ mg/L} and COD is \\approx 34.97\\text{ mg/L}."
        cleaned = clean_latex(raw)
        self.assertNotIn("$", cleaned)
        self.assertNotIn(r"\text", cleaned)
        self.assertNotIn(r"\approx", cleaned)
        self.assertIn("49.0 s", cleaned)
        self.assertIn("35.0 mg/L", cleaned)
        self.assertIn("~ 34.97 mg/L", cleaned)
