import os
import logging
from dotenv import load_dotenv

load_dotenv()
SUMMARIZER_PROVIDER = os.getenv("SUMMARIZER_PROVIDER", "gemini").lower()
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", "models/gemini-1.0-pro")

# --- Gemini ---
if SUMMARIZER_PROVIDER == "gemini":
    import google.generativeai as genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    genai.configure(api_key=GEMINI_API_KEY)
    try:
        available_models = [m.name for m in genai.list_models()]
        logging.info(f"Доступные модели Gemini: {available_models}")
    except Exception as e:
        logging.error(f"Ошибка получения списка моделей Gemini: {e}")
    model = genai.GenerativeModel(SUMMARIZER_MODEL)

# --- OpenAI ---
if SUMMARIZER_PROVIDER == "openai":
    from openai import OpenAI
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

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
            "Проанализируй диалог и выдели несколько главных тем обсуждения, которые реально связаны с основной тематикой чата и обсуждались более 10-15 сообщений. "
            "Игнорируй флуд, троллинг, шутки и оффтоп. Ответь только списком тем (каждая в 3-4 слова, без лишнего текста), отсортированных по важности.\n\n"
            f"{text_block}"
        )

        if SUMMARIZER_PROVIDER == "gemini":
            response = model.generate_content(prompt)
            topic = clean_text(response.text.strip())
        elif SUMMARIZER_PROVIDER == "openai":
            completion = openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "Вы — полезный помощник, который обобщает сообщения чата. Сделайте все возможное, чтобы предоставить полезную информацию о том, что обсуждалось в предоставленных сообщениях чата."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,
            )
            topic = clean_text(completion.choices[0].message.content.strip())
        else:
            topic = "[Провайдер саммари не настроен]"
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