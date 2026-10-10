import os
import uuid
import httpx
from dotenv import load_dotenv

load_dotenv()
AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")


async def ask_gigachat(prompt: str) -> str:
    if not AUTH_KEY:
        return "⚠️ GigaChat не настроен"

    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        r = await client.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={
                "Authorization": f"Basic {AUTH_KEY}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"scope": "GIGACHAT_API_PERS"},
        )
        if r.status_code != 200:
            return f"⚠️ Ошибка авторизации GigaChat: {r.status_code} {r.text[:200]}"
        token = r.json().get("access_token")

    async with httpx.AsyncClient(timeout=60, verify=False) as client:
        r = await client.post(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "model": "GigaChat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
            },
        )
        if r.status_code != 200:
            return f"⚠️ Ошибка GigaChat: {r.status_code} {r.text[:200]}"
        return r.json()["choices"][0]["message"]["content"]