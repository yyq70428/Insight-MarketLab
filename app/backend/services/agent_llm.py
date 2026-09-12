from __future__ import annotations

import json
import requests
from ..config import get_settings


class ModelUnavailable(RuntimeError): pass


def structured_response(instructions: str, payload: dict, schema: dict, *, judge: bool = False) -> dict:
    settings = get_settings()
    if judge:
        settings = settings.model_copy(update={'openai_api_key': settings.ragas_api_key or settings.openai_api_key,
            'openai_base_url': settings.ragas_base_url or settings.openai_base_url,
            'openai_model': settings.ragas_model or settings.openai_model, 'openai_timeout': settings.ragas_timeout})
    if not settings.openai_api_key:
        raise ModelUnavailable("OPENAI_API_KEY 未設定")
    body = {"model": settings.openai_model, "instructions": instructions,
            "store": False,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False, allow_nan=False)}]}],
            "text": {"format": {"type": "json_schema", "name": "marketlab_report", "strict": True, "schema": schema}}}
    try:
        response = requests.post(f"{settings.openai_base_url.rstrip('/')}/responses", json=body,
                                 headers={"Authorization": f"Bearer {settings.openai_api_key}"}, timeout=settings.openai_timeout)
        if response.status_code in (401, 403):
            raise ModelUnavailable("模型 API 金鑰或模型存取權限無效，請檢查 OPENAI_API_KEY 與 OPENAI_MODEL")
        if response.status_code == 429:
            raise ModelUnavailable("模型配額不足或請求過於頻繁，請稍後重試")
        response.raise_for_status(); data=response.json()
        if data.get("status") not in (None, "completed"):
            raise ModelUnavailable("模型回應未完整完成，未產生交易決策")
        texts = [part["text"] for item in data.get("output", []) if item.get("type") == "message"
                 for part in item.get("content", []) if part.get("type") == "output_text"]
        result = json.loads("".join(texts))
        if not isinstance(result, dict):
            raise ModelUnavailable("模型回應不是有效的結構化報告")
        return result
    except ModelUnavailable:
        raise
    except Exception as exc:
        raise ModelUnavailable("模型服務目前無法完成結構化回應") from exc
