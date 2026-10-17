import json

import httpx

from patient_memory.config import Settings
from patient_memory.domain import now
from patient_memory.providers import CompatibleSelector
from tests.unit.test_provider import sample_fact


def test_native_ollama_uses_json_schema_without_thinking_or_tools():
    fact = sample_fact()

    def handler(request):
        data = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert data["think"] is False and data["stream"] is False
        assert data["format"]["additionalProperties"] is False
        assert "tools" not in data
        return httpx.Response(200, json={"message": {"content": json.dumps({"evidence_ids": [str(fact["id"])]})}})

    cfg = Settings(provider="ollama", provider_url="http://127.0.0.1:11434", provider_model="synthetic-test")
    claims = CompatibleSelector(cfg, httpx.MockTransport(handler)).generate("sleep", [fact], now())
    assert claims[0].text == fact["quote"]
