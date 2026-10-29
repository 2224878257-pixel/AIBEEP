"""Minimal DeepSeek JSON-mode API client for server-side AIBEEP scripts.

Keep DEEPSEEK_API_KEY in environment/secret storage, never in static dist/ files.
"""
import json
import os
import time
import urllib.error
import urllib.request

API_URL = "https://api.deepseek.com/chat/completions"


def generate_json(system_prompt, data, *, model=None, token=None):
    token = token or os.environ.get("DEEPSEEK_API_KEY")
    if not token:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    payload = {
        "model": model or os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
        "messages": [
            {"role": "system", "content": system_prompt + "\n请只输出合法 JSON 对象。"},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "max_tokens": 2400,
        "stream": False,
    }
    for attempt in range(3):
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=65) as response:
                result = json.load(response)
            choices = result.get("choices") or []
            if not choices or choices[0].get("finish_reason") != "stop":
                raise ValueError("DeepSeek did not finish the JSON response")
            content = (choices[0].get("message") or {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("DeepSeek returned an empty response")
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("DeepSeek returned non-object JSON")
            return parsed
        except urllib.error.HTTPError as exc:
            # Invalid credentials/request must stop; rate limits and server errors may recover.
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise RuntimeError(f"DeepSeek HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            if attempt == 2:
                raise RuntimeError(f"DeepSeek response failed: {type(exc).__name__}") from None
        time.sleep(2 ** attempt)
    raise RuntimeError("DeepSeek retry limit reached")
