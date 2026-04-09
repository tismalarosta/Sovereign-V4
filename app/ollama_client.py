"""
Ollama client — sends prompts to local LLM via Ollama HTTP API.
No paid APIs. Single function interface.

Default model: gemma4:e4b (Gemma 4 E4B — Phase 13).
Override via LLM_MODEL= in data/.env.
"""

import json
from collections.abc import Generator

import httpx

from app.settings import settings

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL = settings.llm_model
TIMEOUT = 120.0  # seconds — generation can take time on first run


def generate(prompt: str) -> str:
    """Send prompt to local LLM via Ollama. Returns full response text."""
    payload = {"model": MODEL, "prompt": prompt, "stream": False}
    response = httpx.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()["response"].strip()


def generate_stream(prompt: str) -> Generator[str, None, None]:
    """
    Stream tokens from local LLM via Ollama.
    Yields one token string at a time until generation is complete.
    """
    payload = {"model": MODEL, "prompt": prompt, "stream": True}
    with httpx.Client(timeout=TIMEOUT) as client:
        with client.stream("POST", OLLAMA_URL, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done", False):
                    break
