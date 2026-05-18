# backend/llm_client.py
#
# Thin wrapper around Gemini and Groq REST endpoints. Stdlib only,
# returns parsed JSON or plain text. Both APIs have FREE tiers.

import json
import re
import urllib.request
import urllib.error

import config


class LLMError(Exception):
    pass


def chat_json(system_prompt: str, user_prompt: str, max_tokens: int = 600) -> dict:
    """Call the configured LLM and return a parsed JSON dict."""
    provider = config.LLM_PROVIDER
    text = chat_text(system_prompt, user_prompt, max_tokens=max_tokens, want_json=True)
    return _extract_json(text)


def chat_text(system_prompt: str, user_prompt: str,
              max_tokens: int = 400, want_json: bool = False) -> str:
    """Call the configured LLM and return raw text content."""
    provider = config.LLM_PROVIDER

    if provider == "gemini":
        return _call_gemini(system_prompt, user_prompt, max_tokens, want_json)
    if provider == "groq":
        return _call_groq(system_prompt, user_prompt, max_tokens, want_json)
    raise LLMError(f"Unsupported LLM_PROVIDER: {provider}")


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _call_gemini(system_prompt, user_prompt, max_tokens, want_json):
    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY not set")

    body = {
        "contents": [
            {"role": "user", "parts": [{"text": system_prompt + "\n\n" + user_prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": max_tokens,
        },
    }
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"

    url = (
        f"{config.GEMINI_BASE_URL.rstrip('/')}"
        f"/models/{config.GEMINI_MODEL}:generateContent"
        f"?key={config.GEMINI_API_KEY}"
    )
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        raise LLMError(f"Gemini HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}") from e
    except Exception as e:
        raise LLMError(f"Gemini error: {e}") from e


# ---------------------------------------------------------------------------
# Groq
# ---------------------------------------------------------------------------

def _call_groq(system_prompt, user_prompt, max_tokens, want_json):
    if not config.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY not set")

    body = {
        "model": config.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    if want_json:
        body["response_format"] = {"type": "json_object"}

    url = f"{config.GROQ_BASE_URL.rstrip('/')}/chat/completions"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.GROQ_API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise LLMError(f"Groq HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}") from e
    except Exception as e:
        raise LLMError(f"Groq error: {e}") from e


# ---------------------------------------------------------------------------
# Embedding (Gemini only — free tier)
# ---------------------------------------------------------------------------

def gemini_embed(text: str) -> list:
    if not config.GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY not set (needed for embeddings)")
    url = (
        f"{config.GEMINI_BASE_URL.rstrip('/')}"
        f"/models/{config.GEMINI_EMBED_MODEL}:embedContent"
        f"?key={config.GEMINI_API_KEY}"
    )
    body = {"content": {"parts": [{"text": text}]}}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["embedding"]["values"]
    except urllib.error.HTTPError as e:
        raise LLMError(f"Gemini embed HTTP {e.code}") from e


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise LLMError(f"Could not parse JSON from LLM output: {text[:200]}")
        return json.loads(m.group(0))
