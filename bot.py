import os
import json
import logging
import httpx
from dotenv import load_dotenv
from datetime import datetime

from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle import Keyboard, KeyboardButtonColor, Callback, GroupEventType

from gigachat_client import ask_gigachat, appeal_gigachat
from extractor import extract_from_url, extract_from_image

load_dotenv()
API_TOKEN = os.getenv("VK_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)

DB_FILE = "appeals.json"
user_states = {}

SYSTEM_PROMPT = """Ты — эксперт по доказательной медицине. Проверь утверждение.
Верни ответ строго в формате:
ВЕРДИКТ: подтверждено / опровергнуто / спорно / недостаточно данных
УВЕРЕННОСТЬ: число от 0 до 100
ОБЪЯСНЕНИЕ: 2-3 предложения
ИСТОЧНИКИ: 1-3 авторитетных источника (ВОЗ, Минздрав, PubMed, Cochrane)

Утверждение: {claim}
"""

# --- Вспомогательные функции для работы с историей (с защитой от сбоев) ---
def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Файл appeals.json поврежден. Создан пустой.")
        return {}

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- ХЕНДЛЕРЫ ---

@bot.on.message(text="/start")
async def start_handler(message: Message):
    user_states.pop(message.from_id, None)
    await message.answer(
        "👋 Привет! Я Импульс — бот для проверки информации о здоровье.\n\n"
        "Отправь мне:\n"
        "• текст с утверждением,\n"
        "• ссылку на статью,\n"
        "• скриншот публикации.\n\n"
        "Если не согласен с выводом — нажми кнопку «Оспорить»!\n\n"
        "⚠️ Я не заменяю врача."
    )

# --- ОБРАБОТЧИК КНОПОК (Callback) ---
@bot.on.raw_event(GroupEventType.MESSAGE_EVENT, MessageEvent)
async def button_handler(event: MessageEvent):
    if event.payload:
        payload = event.payload
        if isinstance(payload, str):
            payload = json.loads(payload)
            
        if payload.get("cmd") == "dispute":
            # Сохраняем состояние для апелляции
            user_states[event.user_id] = {
                "state": "waiting_for_evidence",
                "original_claim": payload.get("claim"),
                "original_verdict": payload.get("verdict")
            }
            
            # Убираем "часики" с кнопки
            await event.show_snackbar("Запрос на апелляцию принят")
            
            # Отправляем сообщение пользователю
            await bot.api.messages.send(
                peer_id=event.peer_id,
                message=(
                    "⚖️ Апелляция\n\n"
                    "Вы не согласны с выводом. Пожалуйста, отправьте мне ссылку на авторитетный источник "
                    "(ВОЗ, PubMed, Минздрав) или текст с вашими доводами.\n\n"
                    "Я проведу повторную проверку и дам развернутый ответ."
                ),
                random_id=0
            )

# --- ОСНОВНОЙ ОБРАБОТЧИК ТЕКСТА, ФОТО И ССЫЛОК ---
@bot.on.message()
async def any_handler(message: Message):
    text = (message.text or "").strip()

    # 1. Проверяем, не ждем ли мы аргумент для апелляции
    user_id = message.from_id
    if user_id in user_states and user_states[user_id]["state"] == "waiting_for_evidence":
        if not text and not message.attachments:
            return
        await process_appeal(message, text)
        return

    # 2. Обработка фото (OCR)
    if message.attachments:
        for att in message.attachments:
            if att.photo:
                await message.answer("⏳ Распознаю текст на фото...")
                try:
                    photo = att.photo.sizes[-1]
                    async with httpx.AsyncClient(timeout=20) as client:
                        r = await client.get(photo.url)
                        image_bytes = r.content

                    extracted = extract_from_image(image_bytes)
                    if not extracted or len(extracted) < 10:
                        await message.answer("😕 Не удалось распознать текст.")
                        return

                    await message.answer(f"📝 Распознан текст:\n{extracted[:300]}\n\n⏳ Проверяю...")
                    answer = await ask_gigachat(SYSTEM_PROMPT.format(claim=extracted))
                    await send_result_with_button(message, answer, extracted[:50])
                except Exception as e:
                    logger.error(f"Ошибка фото: {e}")
                    await message.answer(f"⚠️ Ошибка обработки фото.")
                return

    # 3. Обработка ссылок
    if text.startswith("http://") or text.startswith("https://"):
        await message.answer("⏳ Загружаю статью по ссылке...")
        try:
            extracted = await extract_from_url(text)
            if not extracted or len(extracted) < 50:
                await message.answer("😕 Не удалось извлечь текст со страницы.")
                return
            await message.answer(f"📝 Извлечено ({len(extracted)} симв.):\n{extracted[:300]}...\n\n⏳ Проверяю...")
            answer = await ask_gigachat(SYSTEM_PROMPT.format(claim=extracted[:3000]))
            await send_result_with_button(message, answer, extracted[:50])
        except Exception as e:
            logger.error(f"Ошибка ссылки: {e}")
            await message.answer(f"⚠️ Ошибка обработки ссылки.")
        return

    # 4. Обработка обычного текста
    if not text or text.startswith("/"):
        return

    logger.info(f"Получено: {text[:80]}")
    await message.answer("⏳ Отправляю в GigaChat...")
    
    try:
        answer = await ask_gigachat(SYSTEM_PROMPT.format(claim=text))
    except Exception as e:
        logger.error(f"Ошибка GigaChat: {e}")
        await message.answer("⚠️ Ошибка при обращении к GigaChat. Попробуйте позже.")
        return

    await send_result_with_button(message, answer, text[:50])

# --- Вспомогательная функция для отправки ответа с кнопкой ---
async def send_result_with_button(message: Message, answer: str, claim_short: str):
    verdict_short = "неизвестно"
    if "ВЕРДИКТ:" in answer:
        verdict_short = answer.split("ВЕРДИКТ:")[1].split("\n")[0].strip()

    kb = Keyboard(inline=True)
    kb.add(Callback("❌ Оспорить", payload={"cmd": "dispute", "claim": claim_short, "verdict": verdict_short}), color=KeyboardButtonColor.NEGATIVE)
    
    await message.answer(answer, keyboard=kb.get_json())

# --- ЛОГИКА АПЕЛЛЯЦИИ ---
async def process_appeal(message: Message, new_material: str):
    user_id = message.from_id
    state_data = user_states.get(user_id)
    
    original_claim = state_data["original_claim"]
    original_verdict = state_data["original_verdict"]
    
    del user_states[user_id]
    
    # Если пользователь прислал ссылку — вытаскиваем текст
    if new_material.startswith("http"):
        await message.answer("⏳ Загружаю статью по вашей ссылке...")
        extracted_text = await extract_from_url(new_material)
        if extracted_text and len(extracted_text) > 50:
            new_material = extracted_text

    await message.answer("🔍 Провожу повторную проверку с учетом ваших доводов...")
    
    result = await appeal_gigachat(original_claim, original_verdict, new_material)
    
    status = result.get("status", "INSUFFICIENT")
    explanation = result.get("explanation", "")
    what_changed = result.get("what_changed", "")
    
    # Сохраняем в историю
    db = load_db()
    appeal_id = str(datetime.now().timestamp())
    db[appeal_id] = {
        "user_id": user_id,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "claim": original_claim,
        "old_verdict": original_verdict,
        "new_material": new_material[:500],
        "new_status": status,
        "explanation": explanation
    }
    save_db(db)
    
    if status == "CONFIRMED":
        header = "🛡️ Вывод оставлен без изменений"
    elif status == "CHANGED":
        header = "🔄 Вывод изменен!"
    else:
        header = "⚖️ Недостаточно данных"

    response_text = (
        f"{header}\n\n"
        f"Ваш довод: {new_material[:200]}...\n\n"
        f"Обоснование: {explanation}\n\n"
        f"Что повлияло: {what_changed}\n\n"
        f"--- \n"
        f"Первоначальный вердикт: {original_verdict}"
    )
    
    if status == "INSUFFICIENT":
        response_text += "\n\n👨‍⚕️ Ваш запрос передан на проверку эксперту. (В прототипе это имитация)"

    await message.answer(response_text)

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    logger.info("Бот запущен...")
    bot.run_forever()