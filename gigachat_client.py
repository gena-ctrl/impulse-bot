import os
import uuid
import json
import httpx
from dotenv import load_dotenv

load_dotenv()
AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")


async def ask_gigachat(prompt: str) -> str:
    """Отправляет промпт в GigaChat и возвращает ответ."""
    if not AUTH_KEY:
        return "⚠️ GigaChat не настроен — ключ отсутствует в .env"

    # Шаг 1: получаем access_token
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

    # Шаг 2: отправляем запрос
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


# --- НОВЫЙ КОД ДЛЯ АПЕЛЛЯЦИИ ---

APPEAL_PROMPT = """Ты — старший эксперт по доказательной медицине.
Ранее сервис проверил утверждение: "{original_claim}"
Первоначальный вердикт был: "{original_verdict}".

Пользователь не согласен и прислал новый материал (довод/ссылку/текст):
"{new_material}"

Твоя задача — провести ПОВТОРНУЮ проверку. Выбери ОДИН из трех исходов:
1. "CONFIRMED" — если новый источник неавторитетный (форум, блог), устарел или не относится к делу. Объясни, почему мы оставляем старый вывод.
2. "CHANGED" — если новый источник авторитетный (ВОЗ, PubMed, Минздрав) и он уточняет или меняет вывод. Признай правоту пользователя.
3. "INSUFFICIENT" — если источники противоречат друг другу или данных реально мало. Скажи, что вопрос передан эксперту.

Верни ответ СТРОГО в формате JSON (без markdown-тегов ```json):
{{
  "status": "CONFIRMED" | "CHANGED" | "INSUFFICIENT",
  "explanation": "Развернутое объяснение для пользователя (2-4 предложения)",
  "what_changed": "Краткое описание, что именно повлияло на решение (например: 'Добавлен авторитетный источник', 'Ссылка на форум')"
}}
"""


async def appeal_gigachat(original_claim: str, original_verdict: str, new_material: str) -> dict:
    """Отправляет апелляцию в GigaChat и возвращает словарь."""
    prompt = APPEAL_PROMPT.format(
        original_claim=original_claim, 
        original_verdict=original_verdict, 
        new_material=new_material
    )
    
    raw_response = await ask_gigachat(prompt)
    
    try:
        clean_json = raw_response.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"Ошибка парсинга JSON от GigaChat: {e}")
        return {
            "status": "INSUFFICIENT",
            "explanation": "Не удалось обработать апелляцию автоматически. Передано на проверку эксперту.",
            "what_changed": "Техническая ошибка"
        }