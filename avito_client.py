"""
Avito Client — работа с официальным Avito Messenger API

Документация: https://developers.avito.ru/api-catalog/messenger/documentation

Требуется:
- Client ID + Client Secret из ЛК Авито (Интеграции и API)
- user_id твоего аккаунта продавца

Возможности:
- Получение токена
- Получение списка чатов
- Получение сообщений в чате
- Отправка сообщений
- Удаление сообщений
"""

import aiohttp
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

AVITO_API_BASE = "https://api.avito.ru"


class AvitoClient:
    def __init__(self, client_id: str, client_secret: str, user_id: int):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_id = user_id
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _get_access_token(self) -> str:
        """Получение или обновление access_token"""
        if self.access_token and self.token_expires_at and datetime.now() < self.token_expires_at:
            return self.access_token

        url = f"{AVITO_API_BASE}/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        session = await self._get_session()
        async with session.post(url, data=data) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Ошибка получения токена Avito: {resp.status} - {text}")

            result = await resp.json()
            self.access_token = result["access_token"]
            # Токен обычно живёт ~1 час
            expires_in = result.get("expires_in", 3600)
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 60)
            logger.info("Avito access_token обновлён")
            return self.access_token

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Универсальный запрос к API"""
        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        url = f"{AVITO_API_BASE}{endpoint}"
        session = await self._get_session()

        async with session.request(method, url, headers=headers, **kwargs) as resp:
            if resp.status >= 400:
                text = await resp.text()
                logger.error(f"Avito API error {resp.status}: {text}")
                raise Exception(f"Avito API error: {resp.status}")
            return await resp.json()

    # ===================== МЕТОДЫ API =====================

    async def get_chats(self, limit: int = 100) -> List[dict]:
        """Получить список чатов"""
        endpoint = f"/messenger/v1/accounts/{self.user_id}/chats"
        params = {"limit": limit}
        data = await self._request("GET", endpoint, params=params)
        return data.get("chats", [])

    async def get_messages(self, chat_id: str, limit: int = 50) -> List[dict]:
        """Получить сообщения из чата"""
        endpoint = f"/messenger/v3/accounts/{self.user_id}/chats/{chat_id}/messages"
        params = {"limit": limit}
        data = await self._request("GET", endpoint, params=params)
        return data.get("messages", [])

    async def send_message(self, chat_id: str, text: str, mark_as_read: bool = False) -> dict:
        """
        Отправить текстовое сообщение в Авито.
        
        По умолчанию mark_as_read=False:
        - Сообщение остаётся НЕПРОЧИТАННЫМ у ПОКУПАТЕЛЯ
        - Мы НЕ вызываем mark_chat_as_read, чтобы чат по возможности оставался непрочитанным и у ПРОДАВЦА (в интерфейсе Авито)
        
        Это специально сделано для рассылок.
        """
        endpoint = f"/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/messages"
        payload = {"message": {"text": text}}
        result = await self._request("POST", endpoint, json=payload)

        if mark_as_read:
            await self.mark_chat_as_read(chat_id)

        return result

    async def delete_message(self, chat_id: str, message_id: str) -> bool:
        """Удалить сообщение (только свои)"""
        endpoint = f"/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/messages/{message_id}"
        try:
            await self._request("DELETE", endpoint)
            return True
        except Exception as e:
            logger.error(f"Не удалось удалить сообщение: {e}")
            return False

    async def mark_chat_as_read(self, chat_id: str) -> bool:
        """Пометить чат как прочитанный"""
        endpoint = f"/messenger/v1/accounts/{self.user_id}/chats/{chat_id}/read"
        try:
            await self._request("POST", endpoint)
            return True
        except:
            return False

    async def get_item_info(self, item_id: int) -> Optional[dict]:
        """Получить информацию об объявлении (если нужно)"""
        # Можно расширить при необходимости
        return None
