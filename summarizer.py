import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

def get_topic_emoji(topic):
    # Словарь тем и их эмодзи
    emoji_map = {
        "разработка": "💻",
        "статистика": "📊",
        "безопасность": "🔒",
        "доступ": "🌐",
        "финансы": "💰",
        "конфигурация": "⚙️",
        "нагрузка": "⚖️",
        "музыка": "🎶",
        "пароль": "🔑",
        "api": "🔧",
        "бот": "🤖",
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

    for thread_id in threads:
        messages = await storage.get_messages_since(chat_id, thread_id, last_summary_time)
        if not messages:
            continue

        # Собираем ссылки из сообщений
        for msg in messages:
            text = msg.get('text', '')
            if text:  # Проверяем, что текст не пустой
                words = text.split()
                for word in words:
                    if word.startswith(('http://', 'https://', 't.me/')):
                        links.append(word)

        # Очищаем текст от HTML тегов и экранируем специальные символы
        def clean_text(text):
            # Заменяем специальные символы HTML на их экранированные версии
            return text.replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')
            
        text_block = "\n".join([f"{m['user']}: {clean_text(m['text'])}" for m in messages])
        prompt = (
            "На основе этих сообщений:\n"
            "1. Определи основную тему обсуждения одним коротким предложением (до 6 слов)\n"
            "2. Верни ответ в формате: ТЕМА\n\n"
            f"{text_block}"
        )

        response = await openai_client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": "Вы - полезный помощник с искусственным интеллектом, который обобщает сообщения чата. Сделайте все возможное, чтобы предоставить полезную информацию о том, что обсуждалось в предоставленных сообщениях чата."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=100,
        )

        topic = clean_text(response.choices[0].message.content.strip())
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

    # Сортируем по количеству сообщений
    summaries.sort(key=lambda x: x["message_count"], reverse=True)
    
    # Очищаем ссылки от HTML тегов и экранируем специальные символы
    clean_links = [clean_text(link) for link in set(links)]
    
    return {
        "topics": summaries,
        "links": clean_links  # Очищенные уникальные ссылки
    } 