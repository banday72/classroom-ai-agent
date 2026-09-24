"""Minimal OpenAI-compatible chat client (uses plain HTTP on purpose).

WHAT: Sends a conversation to any OpenAI-compatible chat-completions API and
      returns the model's reply text.
WHY:  We deliberately use `requests` instead of an SDK so you can SEE the
      actual HTTP call. That is the whole "AI request" — building a JSON
      body, POSTing it to an endpoint, reading JSON back. Every provider
      (OpenAI, Groq, Ollama, OpenRouter...) speaks this same shape when
      running in "OpenAI mode", so changing provider = changing .env.
HOW:  POST {base_url}/chat/completions with:
        {"model": ..., "messages": [{"role": "system"|"user", "content": ...}],
         "temperature": ...}
      Then read data["choices"][0]["message"]["content"].
"""

import requests

from app import config


class AIError(Exception):
    """Raised for any AI call problem (network, auth, bad response...)."""


class AIClient:
    def __init__(self):
        self.api_key = config.AI_API_KEY
        self.base_url = config.AI_BASE_URL
        self.model = config.AI_MODEL
        self.temperature = config.AI_TEMPERATURE

    def chat(self, messages: list, temperature: float = None) -> str:
        """Send messages and return the assistant's text reply."""
        uses_local_model = "localhost" in self.base_url or "127.0.0.1" in self.base_url
        if not self.api_key and not uses_local_model:
            raise AIError(
                "No AI_API_KEY set. Copy .env.example to .env and fill in a key, "
                "or point AI_BASE_URL at a free local model (e.g. Ollama)."
            )

        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=180)
        except requests.RequestException as exc:
            raise AIError(f"Network problem while calling the AI API: {exc}") from exc

        if response.status_code != 200:
            raise AIError(
                f"AI API returned HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise AIError(f"Unexpected response shape from AI API: {exc}") from exc