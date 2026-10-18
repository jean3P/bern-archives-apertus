"""Configurable OpenAI-compatible Apertus connection, without automatic retries."""

import time

import httpx

from core.config import Settings


class ApertusClient:
    def __init__(self, config: Settings, transport=None):
        self.config = config
        headers = {"Authorization": "Bearer " + config.api_key} if config.api_key else {}
        self.http = httpx.Client(timeout=config.timeout, transport=transport, trust_env=False, headers=headers)

    def close(self):
        self.http.close()

    def models(self):
        response = self.http.get(self.config.base_url + "/models")
        response.raise_for_status()
        payload = response.json()
        if not any(row.get("id") == self.config.model for row in payload.get("data", [])):
            raise ValueError("The configured Apertus model is not served")
        return payload

    def complete(self, messages, schema, *, name, max_tokens, record):
        """One explicit POST. Record raw wire data before parsing; never retry here."""
        request = {"model": self.config.model, "temperature": 0, "max_tokens": max_tokens,
                   "messages": messages,
                   "response_format": {"type": "json_schema", "json_schema": {
                       "name": name, "strict": True, "schema": schema}}}
        record({"event": "generation_request", "stage": name, "request": request})
        tick = time.perf_counter()
        try:
            response = self.http.post(self.config.base_url + "/chat/completions", json=request)
        except httpx.HTTPError as error:
            record({"event": "generation_transport_error", "stage": name,
                    "error_type": type(error).__name__, "seconds": time.perf_counter() - tick})
            raise
        record({"event": "generation_response", "stage": name,
                "http_status": response.status_code, "body": response.text,
                "seconds": time.perf_counter() - tick})
        response.raise_for_status()
        payload = response.json()
        if payload.get("model") != self.config.model:
            raise ValueError("The response model differs from the configured model")
        choices = payload.get("choices", [])
        if len(choices) != 1 or choices[0].get("finish_reason") != "stop":
            raise ValueError("Missing, multiple or incomplete model replies")
        content = choices[0].get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty model reply")
        return content

    def smoke(self):
        models = self.models()
        request = {"model": self.config.model, "temperature": 0, "max_tokens": 16,
                   "messages": [{"role": "user", "content": "Reply with exactly BERN_READY and nothing else."}]}
        tick = time.perf_counter()
        response = self.http.post(self.config.base_url + "/chat/completions", json=request)
        response.raise_for_status()
        payload = response.json()
        choice = payload["choices"][0]
        content = choice["message"]["content"]
        if payload.get("model") != self.config.model or choice.get("finish_reason") != "stop":
            raise ValueError("Wrong model or incomplete reply")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty model reply")
        return {"connection_ok": True, "model": self.config.model,
                "models_response": models, "request": request, "response": payload,
                "request_seconds": time.perf_counter() - tick,
                "exact_smoke_text": content.strip() == "BERN_READY",
                "generation_posts": 1, "archive_question_answering_tested": False}
