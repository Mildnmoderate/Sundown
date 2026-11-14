from groq import Groq
from . import config


def chat(prompt: str, system: str = "You are a concise assistant.", max_tokens: int = 300) -> str:
    client = Groq(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL.removesuffix("/openai/v1") or "https://api.groq.com",
        timeout=20.0,       # a slow model must never stall an offboarding run
        max_retries=0,
    )
    kwargs = dict(
        model=config.LLM_MODEL,
        max_tokens=max_tokens + 1500,   # reasoning models spend tokens thinking before they answer
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    if "gpt-oss" in config.LLM_MODEL:
        kwargs["reasoning_effort"] = "low"     # keeps latency low for a live demo
    response = client.chat.completions.create(**kwargs)
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError(f"Groq returned an empty reply (model={config.LLM_MODEL}, "
                           f"finish={response.choices[0].finish_reason})")
    return content