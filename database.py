import aiosqlite
import logging
from datetime import datetime
from typing import Optional
from config import DB_PATH

logger = logging.getLogger(__name__)

async def init_db():
    """Инициализация таблиц"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                branch_short_name TEXT,         -- краткое название точки/филиала
                phone TEXT,                     -- номер телефона
                status TEXT DEFAULT 'pending',  -- pending, approved, restricted
                role TEXT DEFAULT 'user',       -- user, admin
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP
            )
        """)
        # Таблица для отслеживаемых объявлений (пока не используется в v0.1)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS monitored_ads (
                item_id INTEGER PRIMARY KEY,
                title TEXT,
                enabled INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Состояние чатов для отслеживания новых сообщений (будет в следующих версиях)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_states (
                chat_id TEXT PRIMARY KEY,
                item_id INTEGER,
                last_message_id INTEGER,
                last_checked TIMESTAMP
            )
        """)

        # === НОВОЕ: Филиалы / Адреса магазинов (20+ филиалов) ===
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,           -- Полный адрес, например "Ростов-на-Дону, ул. Ленина, 15"
                short_name TEXT,              -- Короткое название "Батайск-Центр"
                city TEXT,
                enabled INTEGER DEFAULT 1
            )
        """)

        # Подписки пользователей на филиалы (какие адреса мониторит конкретный сотрудник)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_store_subscriptions (
                user_telegram_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_telegram_id, store_id),
                FOREIGN KEY (store_id) REFERENCES stores (id) ON DELETE CASCADE
            )
        """)

        # === Быстрые ответы (Quick Replies) ===
        # telegram_id = NULL → глобальные (стандартные) шаблоны владельца
        # telegram_id = ID сотрудника → личные шаблоны сотрудника
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quick_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,           -- NULL = глобальный, иначе личный
                title TEXT NOT NULL,           -- Название кнопки (короткое)
                text TEXT NOT NULL,            -- Полный текст ответа
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # === Заказы Авито (для управления отправками) ===
        await db.execute("""
            CREATE TABLE IF NOT EXISTS avito_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,             -- ссылка на avito_accounts.id
                chat_id TEXT,
                item_id INTEGER,
                buyer_name TEXT,
                item_title TEXT,
                status TEXT DEFAULT 'active',   -- active, shipped, delivered, cancelled
                ship_by_date TEXT,              -- "до 05.07.2026"
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Хранение сообщений чата (для полного просмотра истории)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,             -- ссылка на avito_accounts.id
                chat_id TEXT,
                sender TEXT,                    -- 'client' или 'seller'
                text TEXT,
                timestamp TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Логи рассылок (блокнот с историей рассылок)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sent_by INTEGER,                -- telegram_id владельца/админа
                text TEXT,
                chats_count INTEGER,
                status TEXT DEFAULT 'sent',     -- sent, scheduled, failed
                scheduled_for TEXT,             -- если по времени
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # === Несколько профилей Авито (поддержка 3+ аккаунтов) ===
        await db.execute("""
            CREATE TABLE IF NOT EXISTS avito_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,             -- например "Основной", "Второй", "Третий"
                client_id TEXT,
                client_secret TEXT,
                user_id INTEGER,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблица для рассылок (mailings) с разными типами
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mailings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_by INTEGER,             -- telegram_id
                type TEXT NOT NULL,             -- 'one_time', 'scheduled', 'triggered'
                text TEXT NOT NULL,
                target TEXT DEFAULT 'all_unread',
                schedule_time TEXT,
                trigger_condition TEXT,
                profiles TEXT DEFAULT 'all',
                time_start TEXT,                -- '09:00'
                time_end TEXT,                  -- '20:00'
                days_of_week TEXT DEFAULT 'all',-- '1,2,3,4,5' или 'all'
                cooldown_minutes INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                last_run TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.commit()

        # Seed примеров филиалов (только если таблица пустая)
        await seed_example_stores(db)
        await seed_mock_orders()
        await seed_example_avito_accounts(db)

    logger.info("База данных инициализирована (включая stores, подписки, быстрые ответы, заказы и профили Авито)")

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            return await cursor.fetchone()

async def get_pending_users():
    """Получить всех пользователей со статусом pending"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE status = 'pending' ORDER BY joined_at DESC"
        ) as cursor:
            return await cursor.fetchall()

async def create_or_update_user(telegram_id: int, username: str, full_name: str, branch_short_name: str = None, phone: str = None, status: str = "pending"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (telegram_id, username, full_name, branch_short_name, phone, status, last_activity)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                branch_short_name = COALESCE(excluded.branch_short_name, users.branch_short_name),
                phone = COALESCE(excluded.phone, users.phone),
                last_activity = CURRENT_TIMESTAMP
        """, (telegram_id, username, full_name, branch_short_name, phone, status))
        await db.commit()

async def update_user_status(telegram_id: int, new_status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET status = ?, last_activity = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (new_status, telegram_id)
        )
        await db.commit()
    logger.info(f"Статус пользователя {telegram_id} изменён на {new_status}")

async def update_user_role(telegram_id: int, new_role: str):
    """Сделать пользователя админом или обычным пользователем"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET role = ?, last_activity = CURRENT_TIMESTAMP WHERE telegram_id = ?",
            (new_role, telegram_id)
        )
        await db.commit()
    logger.info(f"Роль пользователя {telegram_id} изменена на {new_role}")

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY joined_at DESC") as cursor:
            return await cursor.fetchall()

async def get_approved_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT telegram_id FROM users WHERE status = 'approved'"
        ) as cursor:
            rows = await cursor.fetchall()
            return [row["telegram_id"] for row in rows]

async def is_owner(telegram_id: int) -> bool:
    from config import OWNER_TELEGRAM_ID
    return telegram_id == OWNER_TELEGRAM_ID

async def is_admin(telegram_id: int) -> bool:
    if await is_owner(telegram_id):
        return True
    user = await get_user(telegram_id)
    return user is not None and user["role"] == "admin"

async def get_approved_users():
    """Возвращает список всех approved пользователей"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE status = 'approved'"
        ) as cursor:
            return await cursor.fetchall()


async def has_access(telegram_id: int) -> bool:
    if await is_owner(telegram_id):
        return True
    user = await get_user(telegram_id)
    return user is not None and user["status"] == "approved"


# ===================== ФИЛИАЛЫ / АДРЕСА =====================

async def add_store(name: str, short_name: str = None, city: str = None) -> int:
    """Добавить новый филиал. Возвращает id"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO stores (name, short_name, city) VALUES (?, ?, ?)",
            (name, short_name, city)
        )
        await db.commit()
        return cursor.lastrowid

async def get_all_stores(enabled_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM stores"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY city, name"
        async with db.execute(query) as cursor:
            return await cursor.fetchall()

async def get_store(store_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM stores WHERE id = ?", (store_id,)) as cursor:
            return await cursor.fetchone()

async def update_store(store_id: int, name: str = None, short_name: str = None, city: str = None, enabled: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        fields = []
        values = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if short_name is not None:
            fields.append("short_name = ?")
            values.append(short_name)
        if city is not None:
            fields.append("city = ?")
            values.append(city)
        if enabled is not None:
            fields.append("enabled = ?")
            values.append(enabled)
        if not fields:
            return
        values.append(store_id)
        await db.execute(f"UPDATE stores SET {', '.join(fields)} WHERE id = ?", values)
        await db.commit()

async def get_user_subscriptions(telegram_id: int):
    """Возвращает список store_id, на которые подписан пользователь"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT store_id FROM user_store_subscriptions WHERE user_telegram_id = ?",
            (telegram_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_user_subscribed_stores(telegram_id: int):
    """Полные данные по подписанным филиалам"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT s.* FROM stores s
            JOIN user_store_subscriptions uss ON s.id = uss.store_id
            WHERE uss.user_telegram_id = ? AND s.enabled = 1
            ORDER BY s.city, s.name
        """, (telegram_id,)) as cursor:
            return await cursor.fetchall()

async def subscribe_user(telegram_id: int, store_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO user_store_subscriptions (user_telegram_id, store_id) VALUES (?, ?)",
            (telegram_id, store_id)
        )
        await db.commit()

async def unsubscribe_user(telegram_id: int, store_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM user_store_subscriptions WHERE user_telegram_id = ? AND store_id = ?",
            (telegram_id, store_id)
        )
        await db.commit()

async def set_user_subscriptions(telegram_id: int, store_ids: list[int]):
    """Полностью заменить подписки пользователя (удобно для toggle)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_store_subscriptions WHERE user_telegram_id = ?", (telegram_id,))
        if store_ids:
            values = [(telegram_id, sid) for sid in store_ids]
            await db.executemany(
                "INSERT INTO user_store_subscriptions (user_telegram_id, store_id) VALUES (?, ?)",
                values
            )
        await db.commit()


async def seed_example_stores(db):
    """Добавляет примеры филиалов, если их ещё нет"""
    async with db.execute("SELECT COUNT(*) FROM stores") as cursor:
        count = (await cursor.fetchone())[0]
    if count > 0:
        return

    example_stores = [
        ("Ростов-на-Дону, пр. Соколова, 15", "Ростов-Центр", "Ростов-на-Дону"),
        ("Батайск, ул. Ленина, 42", "Батайск-1", "Батайск"),
        ("Таганрог, ул. Петровская, 88", "Таганрог-Центр", "Таганрог"),
        ("Новочеркасск, пл. Ермака, 5", "Новочеркасск", "Новочеркасск"),
        ("Гуково, ул. Карла Маркса, 21", "Гуково", "Гуково"),
        ("Шахты, ул. Советская, 67", "Шахты-1", "Шахты"),
        ("Ростов-на-Дону, ул. Текучёва, 250", "Ростов-Запад", "Ростов-на-Дону"),
        ("Аксай, ул. Садовая, 12", "Аксай", "Аксай"),
    ]
    for name, short, city in example_stores:
        await db.execute(
            "INSERT INTO stores (name, short_name, city) VALUES (?, ?, ?)",
            (name, short, city)
        )
    await db.commit()
    logger.info(f"Добавлено {len(example_stores)} примеров филиалов")


async def seed_example_avito_accounts(db):
    """Добавляет 3 тестовых профиля Авито"""
    async with db.execute("SELECT COUNT(*) FROM avito_accounts") as cursor:
        count = (await cursor.fetchone())[0]
    if count > 0:
        return

    accounts = [
        ("Основной профиль", "", "", 111111),
        ("Второй профиль", "", "", 222222),
        ("Третий профиль", "", "", 333333),
    ]
    for name, client_id, secret, user_id in accounts:
        await db.execute(
            "INSERT INTO avito_accounts (name, client_id, client_secret, user_id) VALUES (?, ?, ?, ?)",
            (name, client_id, secret, user_id)
        )
    await db.commit()
    logger.info("Добавлены 3 тестовых профиля Авито")


# ===================== БЫСТРЫЕ ОТВЕТЫ (Quick Replies) =====================

async def add_quick_reply(telegram_id: Optional[int], title: str, text: str) -> int:
    """Добавить быстрый ответ. telegram_id=None → глобальный"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO quick_replies (telegram_id, title, text) VALUES (?, ?, ?)",
            (telegram_id, title, text)
        )
        await db.commit()
        return cursor.lastrowid

async def get_global_quick_replies():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM quick_replies WHERE telegram_id IS NULL ORDER BY created_at"
        ) as cursor:
            return await cursor.fetchall()

async def get_personal_quick_replies(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM quick_replies WHERE telegram_id = ? ORDER BY created_at",
            (telegram_id,)
        ) as cursor:
            return await cursor.fetchall()

async def get_all_quick_replies_for_user(telegram_id: int):
    """Глобальные + личные ответы пользователя"""
    global_replies = await get_global_quick_replies()
    personal_replies = await get_personal_quick_replies(telegram_id)
    return global_replies + personal_replies

async def delete_quick_reply(reply_id: int, requester_telegram_id: int) -> bool:
    """
    Удалить быстрый ответ.
    - Владелец может удалять глобальные (telegram_id IS NULL)
    - Пользователь может удалять только свои личные
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем владельца
        from config import OWNER_TELEGRAM_ID
        is_owner = requester_telegram_id == OWNER_TELEGRAM_ID

        if is_owner:
            # Владелец может удалять всё
            await db.execute("DELETE FROM quick_replies WHERE id = ?", (reply_id,))
        else:
            # Обычный пользователь — только свои
            await db.execute(
                "DELETE FROM quick_replies WHERE id = ? AND telegram_id = ?",
                (reply_id, requester_telegram_id)
            )
        await db.commit()
        return True

async def get_quick_reply_by_id(reply_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM quick_replies WHERE id = ?", (reply_id,)) as cursor:
            return await cursor.fetchone()


# ===================== ЗАКАЗЫ АВИТО =====================

async def seed_mock_orders():
    """Добавляет тестовые заказы, если их нет"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM avito_orders") as cursor:
            count = (await cursor.fetchone())[0]
        if count > 0:
            return

        mock_orders = [
            (1, "chat_001", 123456789, "Иван Петров", "iPhone 13 128GB", "active", "до 05.07.2026"),
            (2, "chat_002", 987654321, "Мария Сидорова", "Samsung Galaxy S24", "active", "до 03.07.2026"),
            (1, "chat_003", 555666777, "Алексей Козлов", "PlayStation 5", "shipped", "отправлен 01.07"),
            (3, "chat_004", 111222333, "Ольга Новикова", "MacBook Air M3", "delivered", "доставлен 28.06"),
        ]
        for account_id, chat_id, item_id, buyer, title, status, ship_date in mock_orders:
            await db.execute("""
                INSERT INTO avito_orders (account_id, chat_id, item_id, buyer_name, item_title, status, ship_by_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (account_id, chat_id, item_id, buyer, title, status, ship_date))
        await db.commit()
        logger.info("Добавлены тестовые заказы Авито")

async def get_active_orders():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*, a.name as profile_name 
            FROM avito_orders o
            LEFT JOIN avito_accounts a ON o.account_id = a.id
            WHERE o.status IN ('active', 'shipped') 
            ORDER BY o.created_at DESC
        """) as cursor:
            return await cursor.fetchall()

async def get_delivered_orders():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*, a.name as profile_name 
            FROM avito_orders o
            LEFT JOIN avito_accounts a ON o.account_id = a.id
            WHERE o.status = 'delivered' 
            ORDER BY o.created_at DESC
        """) as cursor:
            return await cursor.fetchall()

async def get_order(order_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT o.*, a.name as profile_name 
            FROM avito_orders o
            LEFT JOIN avito_accounts a ON o.account_id = a.id
            WHERE o.id = ?
        """, (order_id,)) as cursor:
            return await cursor.fetchone()

async def update_order_status(order_id: int, new_status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE avito_orders SET status = ? WHERE id = ?",
            (new_status, order_id)
        )
        await db.commit()

# ===================== СООБЩЕНИЯ ЧАТОВ =====================

async def add_chat_message(chat_id: str, sender: str, text: str, timestamp: str = None):
    if timestamp is None:
        timestamp = datetime.now().strftime("%d.%m %H:%M")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO chat_messages (chat_id, sender, text, timestamp) VALUES (?, ?, ?, ?)",
            (chat_id, sender, text, timestamp)
        )
        await db.commit()

async def get_chat_messages(chat_id: str, limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return list(reversed(rows))  # в хронологическом порядке


# ===================== РАССЫЛКИ (Broadcast) =====================

async def log_broadcast(sent_by: int, text: str, chats_count: int, status: str = "sent", scheduled_for: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO broadcast_logs (sent_by, text, chats_count, status, scheduled_for)
            VALUES (?, ?, ?, ?, ?)
        """, (sent_by, text, chats_count, status, scheduled_for))
        await db.commit()

async def get_broadcast_logs(limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM broadcast_logs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ) as cursor:
            return await cursor.fetchall()


# ===================== MAILINGS (Рассылки с типами) =====================

async def create_mailing(created_by: int, mailing_type: str, text: str, target: str = 'all_unread', schedule_time: str = None, trigger_condition: str = None, profiles: str = 'all', time_start: str = None, time_end: str = None, days_of_week: str = 'all', cooldown_minutes: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO mailings (created_by, type, text, target, schedule_time, trigger_condition, profiles, time_start, time_end, days_of_week, cooldown_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (created_by, mailing_type, text, target, schedule_time, trigger_condition, profiles, time_start, time_end, days_of_week, cooldown_minutes))
        await db.commit()
        return cursor.lastrowid

async def get_active_mailings():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM mailings WHERE is_active = 1 ORDER BY created_at DESC"
        ) as cursor:
            return await cursor.fetchall()

async def get_mailing(mailing_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM mailings WHERE id = ?", (mailing_id,)) as cursor:
            return await cursor.fetchone()

async def update_mailing_status(mailing_id: int, is_active: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE mailings SET is_active = ? WHERE id = ?",
            (is_active, mailing_id)
        )
        await db.commit()

async def log_mailing_run(mailing_id: int, chats_count: int, status: str = 'sent'):
    # Можно расширить broadcast_logs или сделать отдельный лог
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO broadcast_logs (sent_by, text, chats_count, status)
            SELECT created_by, text, ?, ? FROM mailings WHERE id = ?
        """, (chats_count, status, mailing_id))
        await db.commit()
