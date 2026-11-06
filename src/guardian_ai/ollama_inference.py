"""ShieldAI Ollama client - local LLM inference, no cloud.

Talks to a local Ollama daemon over HTTP (default http://localhost:11434).
Everything stays on this machine, same as the rest of the platform.

Design contract (first principles):
- available() must fail fast and never hang the CLI
- inference is optional - every caller must have a deterministic fallback
- LLM output is inference, not verified fact; callers must label it so
"""
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_HOST = "http://localhost:11434"


class OllamaClient:
    """Minimal local Ollama HTTP client (stdlib only)."""

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 3.0):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._available: Optional[bool] = None

    def _get(self, path: str, timeout: float) -> Optional[Dict[str, Any]]:
        try:
            req = urllib.request.Request(self.host + path)
            # nosec B310 - host is localhost/operator-configured local daemon
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return None

    def _post(self, path: str, payload: Dict[str, Any], timeout: float) -> Optional[Dict[str, Any]]:
        try:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                self.host + path, data=body,
                headers={"Content-Type": "application/json"})
            # nosec B310 - host is localhost/operator-configured local daemon
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            return None

    def available(self) -> bool:
        """True when the daemon answers /api/tags. Result is cached."""
        if self._available is None:
            self._available = self._get("/api/tags", self.timeout) is not None
        return self._available

    def models(self) -> List[str]:
        """Names of locally installed models ([] when unreachable)."""
        data = self._get("/api/tags", self.timeout) or {}
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    def pick_model(self, preferred: Optional[str] = None) -> Optional[str]:
        """Return `preferred` if installed, else the first installed model."""
        installed = self.models()
        if not installed:
            return None
        if preferred in installed:
            return preferred
        # prefer a same-family tag (e.g. llama3:8b-instruct for llama3:8b)
        if preferred:
            family = preferred.split(":")[0]
            for name in installed:
                if name.split(":")[0] == family:
                    return name
        return installed[0]

    def generate(self, prompt: str, model: str, system: Optional[str] = None,
                 timeout: float = 60.0) -> Optional[str]:
        """Run /api/generate; returns response text or None on failure."""
        payload: Dict[str, Any] = {"model": model, "prompt": prompt,
                                   "stream": False}
        if system:
            payload["system"] = system
        data = self._post("/api/generate", payload, timeout)
        return data.get("response") if data else None

    def chat(self, messages: List[Dict[str, str]], model: str,
             timeout: float = 60.0) -> Optional[str]:
        """Run /api/chat; returns assistant text or None on failure."""
        data = self._post("/api/chat",
                          {"model": model, "messages": messages, "stream": False},
                          timeout)
        if data and isinstance(data.get("message"), dict):
            return data["message"].get("content")
        return None


__all__ = ["OllamaClient", "DEFAULT_HOST"]
