from pathlib import Path

import openai

CREDS_FILE = Path(__file__).with_name("litellm.env")


def load_creds(path):
    creds = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        creds[key.strip()] = value.strip().strip('"').strip("'")
    return creds


creds = load_creds(CREDS_FILE)

client = openai.OpenAI(
    api_key=creds["LITELLM_API_KEY"],
    base_url=creds["LITELLM_BASE_URL"],  # LiteLLM Proxy is OpenAI compatible
)

response = client.chat.completions.create(
    model=creds.get("LITELLM_MODEL", "GigaChat-3-Pro"),
    messages=[
        {
            "role": "user",
            "content": "this is a test request, write a short poem",
        }
    ],
)

print(response)
