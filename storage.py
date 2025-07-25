import redis.asyncio as aioredis
import os
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

class MessageStorage:
    async def set_selected_topic(self, chat_id: int, thread_id: int):
        await self._init()
        await self.redis.hset(f"selected_topics:{chat_id}", thread_id, 1)

    async def get_selected_topics(self, chat_id: int) -> list:
        await self._init()
        topics = await self.redis.hkeys(f"selected_topics:{chat_id}")
        return [int(t) for t in topics]
    def __init__(self):
        self.redis = None

    async def _init(self):
        if self.redis is None:
            self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)

    async def save_message(self, chat_id: int, thread_id: int, user: str, text: str, date: datetime):
        await self._init()
        # Приводим дату к UTC-aware
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        else:
            date = date.astimezone(timezone.utc)
        key = f"messages:{chat_id}:{thread_id}"
        msg = json.dumps({"user": user, "text": text, "date": date.isoformat()})
        await self.redis.rpush(key, msg)
        await self.redis.sadd("chats", chat_id)
        await self.redis.sadd(f"threads:{chat_id}", thread_id)

    async def get_chats(self) -> List[int]:
        await self._init()
        chats = await self.redis.smembers("chats")
        return [int(cid) for cid in chats]

    async def get_threads(self, chat_id: int) -> List[int]:
        await self._init()
        threads = await self.redis.smembers(f"threads:{chat_id}")
        # Добавляем 0 для основного чата, если его нет в списке
        thread_ids = [int(tid) for tid in threads]
        if 0 not in thread_ids:
            thread_ids.append(0)
        return thread_ids

    async def get_messages_since(self, chat_id: int, thread_id: int, since: str) -> List[Dict]:
        await self._init()
        key = f"messages:{chat_id}:{thread_id}"
        msgs = await self.redis.lrange(key, 0, -1)
        since_dt = datetime.fromisoformat(since)
        if since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=timezone.utc)
        
        # Очищаем сообщения старше 3 суток
        now = datetime.now(timezone.utc)
        three_days_ago = (now - timedelta(days=3)).isoformat()
        await self.clear_old_messages(chat_id, thread_id, three_days_ago)
        
        result = []
        for m in msgs:
            d = json.loads(m)
            msg_dt = datetime.fromisoformat(d["date"])
            if msg_dt.tzinfo is None:
                msg_dt = msg_dt.replace(tzinfo=timezone.utc)
            if msg_dt > since_dt:
                result.append({"user": d["user"], "text": d["text"]})
        return result
        
    async def clear_old_messages(self, chat_id: int, thread_id: int, before_date: str):
        """Очищает сообщения из Redis старше указанной даты"""
        await self._init()
        key = f"messages:{chat_id}:{thread_id}"
        
        # Получаем все сообщения
        messages = await self.redis.lrange(key, 0, -1)
        if not messages:
            return
            
        # Определяем индексы сообщений для сохранения (новее before_date)
        messages_to_keep = []
        for msg in messages:
            msg_data = json.loads(msg)
            msg_date = datetime.fromisoformat(msg_data["date"])
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            if msg_date > datetime.fromisoformat(before_date):
                messages_to_keep.append(msg)
        
        if not messages_to_keep:
            # Если нет сообщений для сохранения, удаляем весь ключ
            await self.redis.delete(key)
            # Если это был последний топик, удаляем его из списка топиков
            remaining_messages = await self.redis.exists(key)
            if not remaining_messages:
                await self.redis.srem(f"threads:{chat_id}", thread_id)
        else:
            # Сохраняем только новые сообщения
            await self.redis.delete(key)
            if messages_to_keep:
                await self.redis.rpush(key, *messages_to_keep)

    async def get_last_summary_time(self, chat_id: int) -> str:
        await self._init()
        val = await self.redis.hget(f"summary_state:{chat_id}", "last_summary_time")
        return val or datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat()

    async def update_last_summary_time(self, chat_id: int):
        await self._init()
        now = datetime.now(timezone.utc).isoformat()
        await self.redis.hset(f"summary_state:{chat_id}", "last_summary_time", now)

    async def set_summary_topic(self, chat_id: int, topic_id: int):
        await self._init()
        await self.redis.hset(f"summary_state:{chat_id}", "summary_topic_id", topic_id)

    async def get_summary_topic(self, chat_id: int) -> int:
        await self._init()
        val = await self.redis.hget(f"summary_state:{chat_id}", "summary_topic_id")
        return int(val) if val is not None else 0

    async def set_summary_interval(self, chat_id: int, interval: int):
        await self._init()
        await self.redis.hset(f"summary_state:{chat_id}", "summary_interval", interval)

    async def get_summary_interval(self, chat_id: int) -> int:
        await self._init()
        val = await self.redis.hget(f"summary_state:{chat_id}", "summary_interval")
        return int(val) if val is not None else None

    async def set_summary_enabled(self, chat_id: int, enabled: bool):
        await self._init()
        await self.redis.hset(f"summary_state:{chat_id}", "summary_enabled", int(enabled))

    async def get_summary_enabled(self, chat_id: int) -> bool:
        await self._init()
        val = await self.redis.hget(f"summary_state:{chat_id}", "summary_enabled")
        return bool(int(val)) if val is not None else True 

    async def clear_messages(self, chat_id: int, thread_id: int, before_date: str):
        """Очищает сообщения из Redis до указанной даты"""
        await self._init()
        key = f"messages:{chat_id}:{thread_id}"
        
        # Получаем все сообщения
        messages = await self.redis.lrange(key, 0, -1)
        if not messages:
            return
        
        # Определяем индексы сообщений для удаления
        indices_to_keep = []
        for i, msg in enumerate(messages):
            msg_data = json.loads(msg)
            msg_date = datetime.fromisoformat(msg_data["date"])
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            if msg_date > datetime.fromisoformat(before_date):
                indices_to_keep.append(i)
        
        if not indices_to_keep:
            # Если нет сообщений для сохранения, удаляем весь ключ
            await self.redis.delete(key)
            # Если это был последний топик, удаляем его из списка топиков
            remaining_messages = await self.redis.exists(key)
            if not remaining_messages:
                await self.redis.srem(f"threads:{chat_id}", thread_id)
        else:
            # Сохраняем только новые сообщения
            new_messages = [messages[i] for i in indices_to_keep]
            # Очищаем старый список и добавляем новые сообщения
            await self.redis.delete(key)
            if new_messages:
                await self.redis.rpush(key, *new_messages)