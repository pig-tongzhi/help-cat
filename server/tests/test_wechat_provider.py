import io
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from server.helpcat.auth import WechatProvider
from server.helpcat.config import Settings


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return io.BytesIO(self.payload)

    def __exit__(self, *args):
        return False


class WechatProviderTests(unittest.TestCase):
    def provider(self):
        settings = Settings(database_url="sqlite://")
        settings.wechat_app_id = "wx-app-id"
        settings.wechat_app_secret = "server-only-secret"
        return WechatProvider(settings)

    def test_code_exchange_returns_openid_without_exposing_session_key(self):
        with patch("server.helpcat.auth.urlopen", return_value=Response({"openid": "openid-77", "session_key": "private"})) as call:
            self.assertEqual(self.provider().exchange_code("login-code"), "openid-77")
        url = call.call_args.args[0]
        self.assertIn("jscode2session", url)
        self.assertIn("grant_type=authorization_code", url)
        self.assertEqual(call.call_args.kwargs["timeout"], 8)

    def test_provider_maps_wechat_errors_to_safe_gateway_error(self):
        with patch("server.helpcat.auth.urlopen", return_value=Response({"errcode": 40029, "errmsg": "invalid code"})):
            with self.assertRaises(HTTPException) as raised:
                self.provider().exchange_code("bad-code")
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(raised.exception.detail, {"code": "wechat_code_exchange_failed"})


if __name__ == "__main__":
    unittest.main()
