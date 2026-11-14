from groq import Groq
from . import config


def chat(prompt: str, system: str = "You are a concise assistant.", max_tokens: int = 300) -> str:
    client = Groq(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL.removesuffix("/openai/v1") or "https://api.groq.com",
    )
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        max_tokens=max_tokens,
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Groq returned an empty chat response")
    return content