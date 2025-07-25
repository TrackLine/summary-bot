import os
import google.generativeai as genai
from dotenv import load_dotenv


load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

def get_topic_emoji(topic):
    # Расширенный словарь тем и их эмодзи
    emoji_map = {
        # Технические темы
        "разработка": "💻",
        "код": "👨‍💻",
        "баг": "🐛",
        "ошибка": "❌",
        "тест": "🧪",
        "api": "🔌",
        "бот": "🤖",
        "база данных": "💾",
        "сервер": "🖥️",
        # Бизнес и организация
        "встреча": "📅",
        "проект": "📋",
        "задача": "✅",
        "дедлайн": "⏰",
        "план": "📊",
        "статистика": "📈",
        "отчет": "📑",
        # Коммуникация
        "обсуждение": "💬",
        "вопрос": "❓",
        "решение": "💡",
        "предложение": "✨",
        "проблема": "⚠️",
        # Безопасность
        "безопасность": "🔒",
        "доступ": "🔑",
        "пароль": "🔐",
        # Общие темы
        "обновление": "🆕",
        "изменение": "🔄",
        "настройка": "⚙️",
        "документация": "📚",
        "default": "📝"
    }
    
    for key, emoji in emoji_map.items():
        if key.lower() in topic.lower():
            return emoji
    return emoji_map["default"]

async def summarize_threads(storage, chat_id, threads, since_date=None):
    summaries = []
    links = []
    last_summary_time = since_date or await storage.get_last_summary_time(chat_id)

    def clean_text(text):
        return text.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')

    for thread_id in threads:
        messages = await storage.get_messages_since(chat_id, thread_id, last_summary_time)
        if not messages:
            continue

        # Собираем ссылки из сообщений
        for msg in messages:
            text = msg.get('text', '')
            if text:
                words = text.split()
                for word in words:
                    if word.startswith(('http://', 'https://', 't.me/')):
                        links.append(word)

        text_block = "\n".join([f"{m['user']}: {clean_text(m['text'])}" for m in messages])
        prompt = (
            "Проанализируй диалог и определи несколько главных тем обсуждения. "
            "Ответь ТОЛЬКО основными темами в 3-4 слова без дополнительного текста.\n\n"
            f"{text_block}"
        )

        response = await model.generate_content_async(prompt)
        topic = clean_text(response.text.strip())
        emoji = get_topic_emoji(topic)
        msg_count = len(messages)
        thread_url = f"https://t.me/c/{str(chat_id)[4:]}/{thread_id}" if thread_id else None

        summary_item = {
            "emoji": emoji,
            "topic": topic,
            "message_count": msg_count,
            "thread_id": thread_id,
            "url": thread_url
        }
        summaries.append(summary_item)

    summaries.sort(key=lambda x: x["message_count"], reverse=True)
    clean_links = [clean_text(link) for link in set(links)]
    return {
        "topics": summaries,
        "links": clean_links
    }