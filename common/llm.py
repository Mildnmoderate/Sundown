import httpx
from . import config

def chat(prompt: str, system: str = "You are a concise assistant.", max_tokens: int = 300) -> str:
    r = httpx.post(
        config.LLM_BASE_URL + "/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
        json={
            "model": config.LLM_MODEL,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]