import os
import logging
import httpx
from dotenv import load_dotenv

from vkbottle.bot import Bot, Message

from gigachat_client import ask_gigachat
from extractor import extract_from_url, extract_from_image

load_dotenv()
API_TOKEN = os.getenv("VK_BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)


SYSTEM_PROMPT = """Ты — эксперт по доказательной медицине. Проверь утверждение.
Верни ответ строго в формате:

ВЕРДИКТ: подтверждено / опровергнуто / спорно / недостаточно данных
УВЕРЕННОСТЬ: число от 0 до 100
ОБЪЯСНЕНИЕ: 2-3 предложения
ИСТОЧНИКИ: 1-3 авторитетных источника (ВОЗ, Минздрав, PubMed, Cochrane)

Утверждение: {claim}
"""


@bot.on.message(text="/start")
async def start_handler(message: Message):
    await message.answer(
        "👋 Привет! Я Импульс — бот для проверки информации о здоровье.\n\n"
        "Отправь мне:\n"
        "• текст с утверждением,\n"
        "• ссылку на статью,\n"
        "• скриншот публикации.\n\n"
        "⚠️ Я не заменяю врача."
    )


@bot.on.message()
async def any_handler(message: Message):
    text = (message.text or "").strip()

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

                    await message.answer(
                        f"📝 Распознан текст:\n{extracted[:300]}\n\n⏳ Проверяю..."
                    )
                    answer = await ask_gigachat(SYSTEM_PROMPT.format(claim=extracted))
                    await message.answer(answer)
                except Exception as e:
                    logger.error(f"Ошибка фото: {e}")
                    await message.answer(f"⚠️ Ошибка обработки фото: {e}")
                return

    if text.startswith("http://") or text.startswith("https://"):
        await message.answer("⏳ Загружаю статью по ссылке...")
        try:
            extracted = await extract_from_url(text)
            if not extracted or len(extracted) < 50:
                await message.answer("😕 Не удалось извлечь текст.")
                return
            await message.answer(
                f"📝 Извлечено ({len(extracted)} симв.):\n{extracted[:300]}...\n\n⏳ Проверяю..."
            )
            answer = await ask_gigachat(SYSTEM_PROMPT.format(claim=extracted[:3000]))
            await message.answer(answer)
        except Exception as e:
            logger.error(f"Ошибка ссылки: {e}")
            await message.answer(f"⚠️ Ошибка обработки ссылки: {e}")
        return

    if not text:
        return

    logger.info(f"Получено: {text[:80]}")
    await message.answer("⏳ Отправляю в GigaChat...")
    answer = await ask_gigachat(SYSTEM_PROMPT.format(claim=text))
    await message.answer(answer)


if __name__ == "__main__":
    logger.info("Бот запущен...")
    bot.run_forever()