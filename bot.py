import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.enums import ChatType
from aiogram.types import Message
from dotenv import load_dotenv
from storage import MessageStorage
from summarizer import summarize_threads
from datetime import datetime, timedelta, timezone
from aiogram.exceptions import TelegramBadRequest

# --- Логгирование ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SUMMARY_INTERVAL_MINUTES = int(os.getenv("SUMMARY_INTERVAL_MINUTES", 60))

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
storage = MessageStorage()

logger.info("Бот запускается...")

# --- Базовые команды ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я бот для создания саммари обсуждений в чатах и топиках.\n\n"
        "Основные команды:\n"
        "/set_summary_topic - установить топик для отправки саммари\n"
        "/set_interval - установить интервал саммари (в минутах)\n"
        "/summary_on - включить автоматическое саммари\n"
        "/summary_off - выключить автоматическое саммари\n"
        "/summary_now - создать саммари сейчас (только для админов)"
    )
    logger.info(f"Отправлено приветственное сообщение в чате {message.chat.id}")

# --- Сбор сообщений ---
@dp.message(~Command("start", "set_summary_topic", "set_interval", "summary_on", "summary_off", "summary_now"))
async def collect_messages(message: Message):
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP, ChatType.PRIVATE]:
        # Проверяем наличие текста в сообщении
        if message.text:
            thread_id = message.message_thread_id or 0
            msg_date = message.date
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            else:
                msg_date = msg_date.astimezone(timezone.utc)
            await storage.save_message(
                chat_id=message.chat.id,
                thread_id=thread_id,
                user=message.from_user.full_name,
                text=message.text,
                date=msg_date
            )
            logger.info(f"Собрано сообщение в чате {message.chat.id} (топик {thread_id}): {message.from_user.full_name}")
    return

# --- Настройки ---
@dp.message(Command("set_summary_topic", ignore_mention=True))
async def set_summary_topic(message: Message, command: CommandObject):
    # Теперь команда доступна и в общем чате, и в топиках
    if not command.args:
        await message.reply("Укажите ID топика или 0 для основного чата. Пример: /set_summary_topic 12345")
        return
    try:
        topic_id = int(command.args.strip())
        await storage.set_summary_topic(message.chat.id, topic_id)
        await message.reply(f"Топик для саммари установлен: {topic_id}")
        logger.info(f"Установлен топик для саммари в чате {message.chat.id}: {topic_id} (thread_id={message.message_thread_id})")
    except Exception as e:
        logger.error(f"Ошибка установки топика: {e}")
        await message.reply("Ошибка: не удалось установить топик. Пример: /set_summary_topic 12345")

@dp.message(Command("set_interval", ignore_mention=True))
async def set_interval(message: Message, command: CommandObject):
    if not command.args:
        await message.reply("Укажите интервал в минутах. Пример: /set_interval 60")
        return
    try:
        interval = int(command.args.strip())
        await storage.set_summary_interval(message.chat.id, interval)
        await message.reply(f"Интервал саммари установлен: {interval} минут")
        logger.info(f"Установлен интервал саммари в чате {message.chat.id}: {interval} минут (thread_id={message.message_thread_id})")
    except Exception as e:
        logger.error(f"Ошибка установки интервала: {e}")
        await message.reply("Ошибка: не удалось установить интервал. Пример: /set_interval 60")

@dp.message(Command("summary_on", ignore_mention=True))
async def summary_on(message: Message):
    await storage.set_summary_enabled(message.chat.id, True)
    await message.reply("Саммари включено.")
    logger.info(f"Саммари включено в чате {message.chat.id} (thread_id={message.message_thread_id})")

@dp.message(Command("summary_off", ignore_mention=True))
async def summary_off(message: Message):
    await storage.set_summary_enabled(message.chat.id, False)
    await message.reply("Саммари выключено.")
    logger.info(f"Саммари выключено в чате {message.chat.id} (thread_id={message.message_thread_id})")

@dp.message(Command("summary_now", ignore_mention=True))
async def summary_now(message: Message):
    logger.info("Хендлер summary_now вызван")
    chat_id = message.chat.id
    user_id = message.from_user.id
    # Проверка на администратора
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status not in ("administrator", "creator"):
            await message.reply("Только администратор чата может вызывать принудительное саммари.")
            logger.info(f"Пользователь {user_id} не админ, отказано в /summary_now в чате {chat_id} (thread_id={message.message_thread_id})")
            return
    except TelegramBadRequest as e:
        await message.reply("Не удалось проверить права пользователя. Попробуйте позже.")
        logger.error(f"Ошибка проверки прав пользователя {user_id} в чате {chat_id}: {e}")
        return
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    since = (now - timedelta(hours=24)).isoformat()

    # Получаем информацию о чате
    chat = await bot.get_chat(chat_id)
    is_forum = chat.is_forum
    threads = await storage.get_threads(chat_id)
    topic_id = await storage.get_summary_topic(chat_id)

    if is_forum:
        if not topic_id:
            # Если не указан специальный топик, отправляем саммари в каждый топик
            for thread_id in threads:
                if thread_id == 0:  # Пропускаем общий чат для форумов
                    continue
                thread_summaries = await summarize_threads(storage, chat_id, [thread_id])
                if thread_summaries and (thread_summaries.get("topics") or thread_summaries.get("links")):
                    summary_text = format_summary(thread_summaries, yesterday)
                    await bot.send_message(
                        chat_id,
                        summary_text,
                        message_thread_id=thread_id,
                        parse_mode="HTML"
                    )
                    logger.info(f"Отправлено саммари для топика {thread_id} в чате {chat_id}")
        else:
            # Если указан специальный топик, отправляем общее саммари туда
            all_summaries = await summarize_threads(storage, chat_id, threads)
            if all_summaries and (all_summaries.get("topics") or all_summaries.get("links")):
                summary_text = format_summary(all_summaries, yesterday)
                await bot.send_message(
                    chat_id,
                    summary_text,
                    message_thread_id=topic_id,
                    parse_mode="HTML"
                )
                logger.info(f"Отправлено общее саммари в топик {topic_id} чата {chat_id}")
            else:
                await message.reply("Нет сообщений за последние 24 часа для саммари.")
    else:
        # Для обычного чата делаем одно общее саммари
        summaries = await summarize_threads(storage, chat_id, [0])  # Только основной чат
        if summaries and (summaries.get("topics") or summaries.get("links")):
            summary_text = format_summary(summaries, yesterday)
            send_kwargs = {"parse_mode": "HTML"}
            if topic_id and topic_id != 0:
                send_kwargs["message_thread_id"] = topic_id
            await bot.send_message(chat_id, summary_text, **send_kwargs)
            logger.info(f"Отправлено саммари в чат {chat_id}")
        else:
            await message.reply("Нет сообщений за последние 24 часа для саммари.")

# --- Периодический запуск саммари ---
async def periodic_summary():
    while True:
        await asyncio.sleep(10)  # Проверяем чаще, чтобы учитывать разные интервалы
        for chat_id in await storage.get_chats():
            try:
                # Проверяем включено ли саммари для чата
                if not await storage.get_summary_enabled(chat_id):
                    continue

                # Проверяем интервал
                interval = await storage.get_summary_interval(chat_id) or SUMMARY_INTERVAL_MINUTES
                last_time = await storage.get_last_summary_time(chat_id)
                last_time_dt = datetime.fromisoformat(last_time)
                if last_time_dt.tzinfo is None:
                    last_time_dt = last_time_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                yesterday = now - timedelta(days=1)
                if now < last_time_dt + timedelta(minutes=interval):
                    continue
                
                # Получаем информацию о чате
                chat = await bot.get_chat(chat_id)
                is_forum = chat.is_forum
                threads = await storage.get_threads(chat_id)
                logger.info(f"Запуск саммари для чата {chat_id} (топики: {threads})")

                if is_forum:
                    topic_id = await storage.get_summary_topic(chat_id)
                    if not topic_id:
                        # Если не указан специальный топик, отправляем саммари в каждый топик
                        for thread_id in threads:
                            if thread_id == 0:  # Пропускаем общий чат для форумов
                                continue
                            thread_summaries = await summarize_threads(storage, chat_id, [thread_id])
                            if thread_summaries and (thread_summaries.get("topics") or thread_summaries.get("links")):
                                summary_text = format_summary(thread_summaries, yesterday)
                                await bot.send_message(
                                    chat_id,
                                    summary_text,
                                    message_thread_id=thread_id,
                                    parse_mode="HTML"
                                )
                                logger.info(f"Отправлено саммари для топика {thread_id} в чате {chat_id}")
                    else:
                        # Если указан специальный топик, отправляем общее саммари туда
                        all_summaries = await summarize_threads(storage, chat_id, threads)
                        if all_summaries and (all_summaries.get("topics") or all_summaries.get("links")):
                            summary_text = format_summary(all_summaries, yesterday)
                            await bot.send_message(
                                chat_id,
                                summary_text,
                                message_thread_id=topic_id,
                                parse_mode="HTML"
                            )
                            logger.info(f"Отправлено общее саммари в топик {topic_id} чата {chat_id}")
                await storage.update_last_summary_time(chat_id)
            except Exception as e:
                logger.error(f"Ошибка при генерации/отправке саммари для чата {chat_id}: {e}")

def format_summary(summaries, date):
    """Форматирует саммари в нужный вид"""
    summary_lines = [f"📆 Что обсуждалось {date.strftime('%d.%m.%Y')}\n"]
    
    # Добавляем темы
    for topic in summaries["topics"]:
        topic_line = f"{topic['emoji']} {topic['topic']}"
        if topic["url"]:
            topic_line += f" ({topic['message_count']} сообщений ({topic['url']}))"
        else:
            topic_line += f" ({topic['message_count']} сообщений)"
        summary_lines.append(topic_line)

    # Добавляем ссылки
    if summaries["links"]:
        summary_lines.append("\nИнтересные ссылки:\n")
        for link in summaries["links"]:
            summary_lines.append(f"🔗 {link}")

    return "\n".join(summary_lines)

async def main():
    logger.info("Бот запущен и ожидает события...")
    asyncio.create_task(periodic_summary())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main()) 