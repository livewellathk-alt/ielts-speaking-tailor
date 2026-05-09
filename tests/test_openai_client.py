import json
import ssl
from types import SimpleNamespace

from ielts_tailor.openai_client import OpenAICompatibleClient


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"choices": [{"message": {"content": "{\"ok\": true}"}}]}).encode("utf-8")


def test_openai_client_uses_certifi_ssl_context(monkeypatch):
    captured = {}

    def fake_create_default_context(*, cafile):
        captured["cafile"] = cafile
        return SimpleNamespace(name="context")

    def fake_urlopen(request, *, timeout, context):
        captured["timeout"] = timeout
        captured["context"] = context
        return FakeResponse()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr("ielts_tailor.openai_client.certifi.where", lambda: "/tmp/cacert.pem")
    monkeypatch.setattr(ssl, "create_default_context", fake_create_default_context)
    monkeypatch.setattr("ielts_tailor.openai_client.urllib.request.urlopen", fake_urlopen)

    result = OpenAICompatibleClient(
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        model="deepseek/deepseek-v4-flash",
    ).complete_json(messages=[{"role": "user", "content": "hi"}], schema_name="style_guide", temperature=0.2)

    assert result == {"ok": True}
    assert captured["cafile"] == "/tmp/cacert.pem"
    assert captured["context"].name == "context"
    assert captured["timeout"] == 120
