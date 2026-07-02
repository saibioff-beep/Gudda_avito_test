import asyncio
import logging
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, OWNER_TELEGRAM_ID
import database as db

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===================== Registration Router (высокий приоритет) =====================
registration_router = Router()

# ===================== FSM (для будущих форм) =====================
class AdminStates(StatesGroup):
    waiting_for_restrict_reason = State()

# ===================== Клавиатуры =====================
def get_approval_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Разрешить", callback_data=f"approve:{telegram_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"deny:{telegram_id}")
        ]
    ])

def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin:list_users")],
        [InlineKeyboardButton(text="📋 Заявки на вступление", callback_data="admin:pending_requests")],
        [InlineKeyboardButton(text="🏪 Управление филиалами", callback_data="admin:stores")],
        [InlineKeyboardButton(text="📨 Управление рассылками", callback_data="admin:mailings")],
        [InlineKeyboardButton(text="➕ Добавить пользователя по ID", callback_data="admin:add_user_by_id")],
        [InlineKeyboardButton(text="📣 Сообщение всем пользователям", callback_data="admin:broadcast_all")],
        [InlineKeyboardButton(text="👤 Переключиться на меню пользователя", callback_data="user:menu")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:refresh")]
    ])


def get_persistent_menu() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура внизу чата"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📋 Меню"),
                KeyboardButton(text="👤 Мой профиль"),
                KeyboardButton(text="❓ Хелп")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )


def get_admin_persistent_menu() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура только для админов и владельца"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📋 Меню"),
                KeyboardButton(text="👤 Мой профиль"),
                KeyboardButton(text="❓ Хелп"),
                KeyboardButton(text="⚙️ Админ-меню")
            ]
        ],
        resize_keyboard=True,
        persistent=True
    )

def get_user_status_keyboard(telegram_id: int, current_status: str, current_role: str = "user") -> InlineKeyboardMarkup:
    buttons = []
    if current_status != "approved":
        buttons.append([InlineKeyboardButton(text="✅ Одобрить доступ", callback_data=f"set_status:{telegram_id}:approved")])
    if current_status != "restricted":
        buttons.append([InlineKeyboardButton(text="🚫 Ограничить (уволен и т.д.)", callback_data=f"set_status:{telegram_id}:restricted")])
    if current_status != "pending":
        buttons.append([InlineKeyboardButton(text="⏳ В ожидание", callback_data=f"set_status:{telegram_id}:pending")])

    # Управление ролью админа
    if current_role != "admin":
        buttons.append([InlineKeyboardButton(text="👑 Сделать админом", callback_data=f"set_role:{telegram_id}:admin")])
    else:
        buttons.append([InlineKeyboardButton(text="👤 Снять админку", callback_data=f"set_role:{telegram_id}:user")])

    buttons.append([InlineKeyboardButton(text="🔙 Назад к списку", callback_data="admin:list_users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_approved_user_menu() -> InlineKeyboardMarkup:
    """Главное меню для одобренных пользователей"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Мои филиалы / Адреса", callback_data="user:my_stores")],
        [InlineKeyboardButton(text="💬 Мои быстрые ответы", callback_data="user:quick_replies")],
        [InlineKeyboardButton(text="📦 Управление заказами", callback_data="user:orders")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="user:profile")],
        [InlineKeyboardButton(text="🔄 Обновить меню", callback_data="user:menu")]
    ])


def get_stores_toggle_keyboard(user_id: int, stores: list, subscribed_ids: set) -> InlineKeyboardMarkup:
    """Клавиатура с переключателями подписки на филиалы"""
    buttons = []
    for store in stores:
        is_sub = store["id"] in subscribed_ids
        emoji = "✅" if is_sub else "⬜️"
        text = f"{emoji} {store['short_name'] or store['name']}"
        buttons.append([
            InlineKeyboardButton(text=text, callback_data=f"toggle_store:{store['id']}")
        ])
    buttons.append([
        InlineKeyboardButton(text="💾 Сохранить и выйти", callback_data="user:my_stores_save"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="user:menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ===================== Обработчики =====================
@dp.message(Command("help"))
async def cmd_help(message: Message):
    user_id = message.from_user.id
    is_owner = await db.is_owner(user_id)
    user = await db.get_user(user_id)

    if is_owner or (user and user["status"] == "approved"):
        text = (
            "📖 <b>Avito Gudda — Справка по боту</b>\n\n"
            "Это внутренний бот для работы с сообщениями и заказами на Авито.\n\n"
            "<b>Основные возможности:</b>\n"
            "• Регистрация сотрудников с подтверждением по номеру телефона\n"
            "• Просмотр и ответ на сообщения клиентов (полная история чата)\n"
            "• Управление заказами (активные / доставленные)\n"
            "• Быстрые ответы — сохранённые шаблоны для быстрой отправки (вручную)\n"
            "• Рассылки по чатам (единоразовые, по времени, по триггеру)\n"
            "• Выбор филиалов, по которым получать уведомления\n\n"
            "<b>Команды:</b>\n"
            "• /start — запуск и регистрация\n"
            "• /help — эта справка\n"
            "• /admin — панель администратора (только для владельца и админов)\n\n"
            "<b>Для администратора:</b>\n"
            "Управление пользователями, филиалами, рассылками и статистикой.\n\n"
            "────────────────────\n"
            "<i>create by saibioff n Grok X AI</i>\n"
            "<i>Version: V1.3 beta</i>"
        )
    else:
        text = (
            "📖 <b>Справка</b>\n\n"
            "Напиши /start, чтобы начать регистрацию.\n"
            "После одобрения администратором ты получишь доступ к боту.\n\n"
            "Бот помогает сотрудникам быстро работать с сообщениями и заказами на Авито.\n\n"
            "────────────────────\n"
            "<i>create by saibioff n Grok X AI</i>\n"
            "<i>Version: V1.3 beta</i>"
        )

    await message.answer(text, parse_mode="HTML")


# ===================== ОБРАБОТЧИКИ ПОСТОЯННОЙ КЛАВИАТУРЫ =====================
@dp.message(F.text == "Меню")
async def handle_persistent_menu(message: Message):
    await message.answer("Главное меню:", reply_markup=get_approved_user_menu())


@dp.message(F.text == "👤 Мой профиль")
async def handle_persistent_profile(message: Message):
    await message.answer(
        "👤 **Мой профиль** (в разработке)\n\n"
        "Здесь будет:\n"
        "• ФИО, точка, телефон\n"
        "• Количество отвеченных сообщений\n"
        "• Твоё место в рейтинге\n"
        "• Топ-10 пользователей",
        parse_mode="Markdown"
    )


@dp.message(F.text == "Хелп")
async def handle_persistent_help(message: Message):
    await cmd_help(message)


@dp.message(F.text == "⚙️ Админ-меню")
async def handle_persistent_admin_menu(message: Message):
    if await db.is_owner(message.from_user.id) or await db.is_admin(message.from_user.id):
        await message.answer("Админ-меню:", reply_markup=get_admin_menu_keyboard())
    else:
        await message.answer("У тебя нет доступа к админ-меню.")


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""

    print(f"[DEBUG cmd_start] user_id={user_id}, username=@{username}, full_name={full_name}")

    existing_user = await db.get_user(user_id)
    print(f"[DEBUG cmd_start] existing_user = {existing_user}")

    if await db.is_owner(user_id) or await db.is_admin(user_id):
        print("[DEBUG cmd_start] → Admin/Owner branch")
        await message.answer(
            "👋 Привет! У тебя есть доступ администратора.",
            reply_markup=get_admin_persistent_menu()
        )
        await message.answer(
            "Выберите действие:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Админ-меню", callback_data="admin:menu")]
            ])
        )
        await db.create_or_update_user(user_id, username, full_name, status="approved")
        return

    if existing_user:
        print(f"[DEBUG cmd_start] → Existing user, status={existing_user['status']}")
        if existing_user["status"] == "approved":
            await message.answer(
                "Главное меню:",
                reply_markup=get_persistent_menu()
            )
            # Показываем основное inline меню
            await message.answer(
                "Выберите раздел:",
                reply_markup=get_approved_user_menu()
            )
        else:
            await message.answer("⏳ Твоя заявка уже отправлена. Ожидайте решения.")
        return

    # Новая упрощённая регистрация
    print("[DEBUG cmd_start] → New user → share contact first")
    await state.update_data(telegram_id=user_id, username=username, full_name=full_name)

    share_phone_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer(
        "👋 Для подключения к боту нажми кнопку и поделись номером:",
        reply_markup=share_phone_kb
    )
    await state.set_state("waiting_registration_phone")


# ===================== ОБРАБОТЧИК КОНТАКТА =====================
@dp.message(F.contact)
async def handle_contact(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "waiting_registration_phone":
        return

    phone = message.contact.phone_number
    await state.update_data(phone=phone)

    branches = ["МСК", "ВРШ", "АЛК", "СВР", "КМС", "ТМР", "РНХ", "ПЛЗ", "ТЛР", "ДНР", "КРЛ", "СУВ", "ДБР", "НВЧ", "ШХТ", "ШПР", "ТГН", "РПЛ", "БТС", "АЗВ", "КШТ", "РОП"]

    kb = []
    for i in range(0, len(branches), 2):
        row = [InlineKeyboardButton(text=b, callback_data=f"select_branch:{b}") for b in branches[i:i+2]]
        kb.append(row)

    await message.answer(
        "✅ Номер получен!\n\nВыберите вашу точку:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )
    await state.set_state("waiting_registration_branch")


# ===================== ВЫБОР ТОЧКИ =====================
@dp.callback_query(F.data.startswith("select_branch:"))
async def handle_select_branch(callback: CallbackQuery, state: FSMContext):
    branch = callback.data.split(":")[1]
    data = await state.get_data()

    telegram_id = data.get("telegram_id")
    username = data.get("username", "")
    full_name = data.get("full_name", "")
    phone = data.get("phone")

    await db.create_or_update_user(
        telegram_id=telegram_id,
        username=username,
        full_name=full_name,
        branch_short_name=branch,
        phone=phone,
        status="pending"
    )

    try:
        await bot.send_message(
            OWNER_TELEGRAM_ID,
            f"🆕 **Новая заявка на доступ к боту!**\n\n"
            f"👤 **ФИО:** {full_name or 'не указано'}\n"
            f"📍 **Точка:** {branch}\n"
            f"📱 **Телефон:** {phone}\n"
            f"🆔 **ID:** {telegram_id}\n"
            f"👤 **Username:** @{username or 'нет'}",
            reply_markup=get_approval_keyboard(telegram_id),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить заявку владельцу: {e}")

    await callback.message.edit_text(
        f"✅ Заявка отправлена!\n\nТочка: {branch}\nНомер: {phone}\n\nОжидайте одобрения администратора."
    )
    await state.clear()
    await callback.answer()


# ===================== ДОБАВИТЬ ПОЛЬЗОВАТЕЛЯ ПО ID (только для админа/владельца) =====================
@dp.callback_query(F.data == "admin:add_user_by_id")
async def admin_add_user_by_id_start(callback: CallbackQuery, state: FSMContext):
    if not await db.is_owner(callback.from_user.id) and not await db.is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    await callback.message.edit_text(
        "Введите **Telegram ID** пользователя:\n\nПример: `123456789`",
        parse_mode="Markdown"
    )
    await state.set_state("waiting_add_user_id")
    await callback.answer()


@dp.message(F.text & ~F.command)
async def process_add_user_by_id(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if not current_state or not current_state.startswith("waiting_add_user_"):
        return

    if not await db.is_owner(message.from_user.id) and not await db.is_admin(message.from_user.id):
        return

    text = message.text.strip()

    if current_state == "waiting_add_user_id":
        try:
            target_id = int(text)
        except ValueError:
            await message.answer("❌ Введите только цифры Telegram ID.")
            return

        await state.update_data(target_telegram_id=target_id)
        await message.answer("Введите **ФИО** пользователя:")
        await state.set_state("waiting_add_user_full_name")

    elif current_state == "waiting_add_user_full_name":
        await state.update_data(full_name=text)
        await message.answer("Введите **название торговой точки**:")
        await state.set_state("waiting_add_user_branch")

    elif current_state == "waiting_add_user_branch":
        data = await state.get_data()
        target_id = data.get("target_telegram_id")
        full_name = data.get("full_name")

        # Создаём или обновляем пользователя
        await db.create_or_update_user(
            telegram_id=target_id,
            username="",
            full_name=full_name,
            branch_short_name=text,
            status="approved"
        )

        # Отправляем уведомление пользователю
        try:
            await bot.send_message(
                target_id,
                "🎉 Доступ к боту одобрен!\n\n"
                "Напиши /start, чтобы начать работу."
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление пользователю {target_id}: {e}")

        await message.answer(
            f"✅ Пользователь успешно добавлен!\n\n"
            f"ID: {target_id}\n"
            f"ФИО: {full_name}\n"
            f"Точка: {text}\n\n"
            f"Пользователь получил уведомление."
        )

        await state.clear()
        await message.answer("Меню администратора:", reply_markup=get_admin_menu_keyboard())


# ===================== СООБЩЕНИЕ ВСЕМ ПОЛЬЗОВАТЕЛЯМ =====================
@dp.callback_query(F.data == "admin:broadcast_all")
async def admin_broadcast_all_start(callback: CallbackQuery, state: FSMContext):
    if not await db.is_owner(callback.from_user.id) and not await db.is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    await callback.message.edit_text(
        "Введите текст сообщения, которое хотите отправить **всем** пользователям бота:",
        parse_mode="Markdown"
    )
    await state.set_state("waiting_broadcast_text")
    await callback.answer()


@dp.message(F.text & ~F.command)
async def process_broadcast_text(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "waiting_broadcast_text":
        return

    if not await db.is_owner(message.from_user.id) and not await db.is_admin(message.from_user.id):
        return

    text = message.text.strip()
    await state.update_data(broadcast_text=text)

    await message.answer(
        f"**Подтвердите отправку сообщения всем пользователям:**\n\n{text}\n\n"
        "Отправить? (да / нет)",
        parse_mode="Markdown"
    )
    await state.set_state("waiting_broadcast_confirm")


@dp.message(F.text & ~F.command)
async def process_broadcast_confirm(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "waiting_broadcast_confirm":
        return

    if not await db.is_owner(message.from_user.id) and not await db.is_admin(message.from_user.id):
        return

    answer = message.text.strip().lower()
    data = await state.get_data()
    text = data.get("broadcast_text")

    if answer not in ["да", "yes", "y", "отправить"]:
        await message.answer("Рассылка отменена.")
        await state.clear()
        await message.answer("Меню администратора:", reply_markup=get_admin_menu_keyboard())
        return

    # Получаем всех approved пользователей
    approved_users = await db.get_approved_users()  # нужно будет добавить эту функцию в database.py

    sent = 0
    failed = 0

    for user in approved_users:
        try:
            await bot.send_message(user["telegram_id"], text)
            sent += 1
        except Exception:
            failed += 1

    await message.answer(
        f"✅ Рассылка завершена.\n\n"
        f"Отправлено: {sent}\n"
        f"Не доставлено: {failed}"
    )

    await state.clear()
    await message.answer("Меню администратора:", reply_markup=get_admin_menu_keyboard())

@dp.callback_query(F.data.startswith("approve:"))
async def approve_user(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Только владелец может одобрять пользователей.", show_alert=True)
        return

    target_id = int(callback.data.split(":")[1])
    await db.update_user_status(target_id, "approved")

    # Уведомляем нового пользователя
    try:
        await bot.send_message(
            target_id,
            "🎉 Поздравляем! Владелец одобрил твой доступ к боту.\n"
            "Теперь ты можешь пользоваться всеми функциями."
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить пользователя {target_id}: {e}")

    await callback.message.edit_text(
        f"✅ Пользователь {target_id} одобрен.",
        reply_markup=None
    )
    await callback.answer("Доступ разрешён")

@dp.callback_query(F.data.startswith("deny:"))
async def deny_user(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Только владелец может отклонять заявки.", show_alert=True)
        return

    target_id = int(callback.data.split(":")[1])
    await db.update_user_status(target_id, "restricted")

    try:
        await bot.send_message(target_id, "❌ Владелец отклонил заявку на доступ.")
    except Exception:
        pass

    await callback.message.edit_text(f"❌ Пользователь {target_id} отклонён (статус restricted).")
    await callback.answer("Заявка отклонена")

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await db.is_owner(message.from_user.id):
        await message.answer("🚫 Эта команда только для владельца.")
        return

    await message.answer(
        "⚙️ <b>Админ-меню</b>\n\n"
        "Здесь ты можешь управлять пользователями, добавлять объявления для мониторинга и т.д.\n\n"
        "Выбери действие:",
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "admin:menu")
async def admin_menu_callback(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    await callback.message.edit_text(
        "⚙️ <b>Админ-меню</b>",
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin:list_users")
async def list_users(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Только владелец.", show_alert=True)
        return

    users = await db.get_all_users()
    if not users:
        text = "Пользователей пока нет."
    else:
        text = "👥 <b>Список пользователей:</b>\n\n"
        for u in users:
            status_emoji = {
                "approved": "✅",
                "pending": "⏳",
                "restricted": "🚫"
            }.get(u["status"], "❓")
            text += (
                f"{status_emoji} <b>{u['full_name']}</b> (@{u['username'] or 'нет'})\n"
                f"   ID: <code>{u['telegram_id']}</code> | Статус: {u['status']}\n\n"
            )

    # Добавляем кнопки для каждого пользователя (первые 5 для простоты)
    keyboard_buttons = []
    for u in users[:5]:  # ограничим, чтобы не было слишком длинно
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"Управлять {u['full_name'][:20]}",
                callback_data=f"manage_user:{u['telegram_id']}"
            )
        ])
    keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin:menu")])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "admin:pending_requests")
async def admin_pending_requests(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id) and not await db.is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    pending = await db.get_pending_users()

    if not pending:
        text = "📋 Заявок на вступление пока нет."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin:menu")]])
    else:
        text = "📋 <b>Заявки на вступление</b>\n\n"
        for u in pending:
            text += (
                f"👤 <b>{u['full_name']}</b>\n"
                f"📍 Точка: {u['branch_short_name'] or 'не указана'}\n"
                f"📱 Телефон: {u['phone'] or 'не указан'}\n"
                f"🆔 ID: <code>{u['telegram_id']}</code>\n\n"
            )

        # Кнопки для управления первыми заявками
        kb_buttons = []
        for u in pending[:5]:
            kb_buttons.append([
                InlineKeyboardButton(text=f"✅ Одобрить {u['full_name'][:15]}", callback_data=f"set_status:{u['telegram_id']}:approved"),
                InlineKeyboardButton(text=f"❌ Отклонить", callback_data=f"set_status:{u['telegram_id']}:restricted")
            ])
        kb_buttons.append([InlineKeyboardButton(text="🔙 Назад в админ-меню", callback_data="admin:menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("manage_user:"))
async def manage_user(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    target_id = int(callback.data.split(":")[1])
    user = await db.get_user(target_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    status = user["status"]
    role = user["role"] if user["role"] else "user"
    text = (
        f"👤 <b>{user['full_name']}</b>\n"
        f"Username: @{user['username'] or 'нет'}\n"
        f"Telegram ID: <code>{target_id}</code>\n"
        f"Статус: <b>{status}</b>\n"
        f"Роль: <b>{role}</b>\n"
        f"Присоединился: {user['joined_at']}\n\n"
        "Выбери новое действие:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_user_status_keyboard(target_id, status, role),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("set_status:"))
async def set_user_status(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Только владелец.", show_alert=True)
        return

    parts = callback.data.split(":")
    target_id = int(parts[1])
    new_status = parts[2]

    await db.update_user_status(target_id, new_status)

    # Уведомляем пользователя об изменении статуса
    try:
        if new_status == "approved":
            await bot.send_message(target_id, "✅ Твой доступ к боту восстановлен/одобрен владельцем.")
        elif new_status == "restricted":
            await bot.send_message(target_id, "🚫 Владелец ограничил твой доступ к боту.")
    except Exception:
        pass

    await callback.answer(f"Статус изменён на {new_status}")
    # Возвращаемся к управлению этим пользователем
    user = await db.get_user(target_id)
    text = (
        f"👤 <b>{user['full_name']}</b>\n"
        f"Статус: <b>{new_status}</b>\n\n"
        "Действие выполнено."
    )
    await callback.message.edit_text(text, reply_markup=get_user_status_keyboard(target_id, new_status, user["role"] if user["role"] else "user"), parse_mode="HTML")


@dp.callback_query(F.data.startswith("set_role:"))
async def set_user_role(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Только владелец может менять роли.", show_alert=True)
        return

    parts = callback.data.split(":")
    target_id = int(parts[1])
    new_role = parts[2]

    await db.update_user_role(target_id, new_role)

    try:
        if new_role == "admin":
            await bot.send_message(target_id, "👑 Владелец выдал тебе права администратора.")
        else:
            await bot.send_message(target_id, "👤 Твои права администратора сняты.")
    except:
        pass

    await callback.answer(f"Роль изменена на {new_role}")
    user = await db.get_user(target_id)
    text = (
        f"👤 <b>{user['full_name']}</b>\n"
        f"Роль: <b>{new_role}</b>\n\n"
        "Действие выполнено."
    )
    await callback.message.edit_text(text, reply_markup=get_user_status_keyboard(target_id, user["status"], new_role), parse_mode="HTML")

@dp.callback_query(F.data == "admin:refresh")
async def refresh_admin(callback: CallbackQuery):
    await callback.answer("Обновлено")
    await admin_menu_callback(callback)


# ===================== ОБРАБОТЧИКИ ДЛЯ ОДОБРЕННЫХ ПОЛЬЗОВАТЕЛЕЙ =====================

@dp.callback_query(F.data == "user:menu")
async def user_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await db.has_access(user_id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return
    await callback.message.edit_text(
        "📋 <b>Главное меню</b>\n\nВыбери раздел:",
        reply_markup=get_approved_user_menu(),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "user:my_stores")
async def my_stores(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await db.has_access(user_id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return

    stores = await db.get_all_stores(enabled_only=True)
    if not stores:
        await callback.message.edit_text(
            "🏪 Пока нет добавленных филиалов.\n"
            "Владелец должен добавить их в админ-меню.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="user:menu")]
            ])
        )
        await callback.answer()
        return

    subscribed = await db.get_user_subscriptions(user_id)
    subscribed_set = set(subscribed)

    text = (
        "📍 <b>Мои филиалы</b>\n\n"
        "Выбери адреса, по которым хочешь получать уведомления о сообщениях.\n"
        "Можно выбрать несколько филиалов.\n\n"
        "Нажми на филиал, чтобы включить/выключить подписку:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_stores_toggle_keyboard(user_id, stores, subscribed_set),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_store:"))
async def toggle_store_subscription(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await db.has_access(user_id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return

    store_id = int(callback.data.split(":")[1])
    subscribed = await db.get_user_subscriptions(user_id)

    if store_id in subscribed:
        await db.unsubscribe_user(user_id, store_id)
        action = "отписан от"
    else:
        await db.subscribe_user(user_id, store_id)
        action = "подписан на"

    # Обновляем клавиатуру
    stores = await db.get_all_stores(enabled_only=True)
    new_subscribed = await db.get_user_subscriptions(user_id)
    new_set = set(new_subscribed)

    await callback.message.edit_reply_markup(
        reply_markup=get_stores_toggle_keyboard(user_id, stores, new_set)
    )
    await callback.answer(f"Ты {action} этому филиалу")

@dp.callback_query(F.data == "user:my_stores_save")
async def save_stores(callback: CallbackQuery):
    await callback.answer("Подписки сохранены!")
    await user_menu(callback)


# ===================== БЫСТРЫЕ ОТВЕТЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ =====================

@dp.callback_query(F.data == "user:quick_replies")
async def user_quick_replies(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await db.has_access(user_id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return

    replies = await db.get_all_quick_replies_for_user(user_id)

    text = "💬 <b>Мои быстрые ответы</b>\n\n"
    text += "Глобальные (доступны всем) + твои личные шаблоны.\n\n"

    if not replies:
        text += "Пока нет быстрых ответов. Добавь первый!"
    else:
        for r in replies:
            owner_mark = "🌐 " if r["telegram_id"] is None else "👤 "
            text += f"{owner_mark}<b>{r['title']}</b>\n{r['text'][:80]}...\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить свой быстрый ответ", callback_data="user:add_quick_reply")],
        [InlineKeyboardButton(text="🗑️ Управление (удалить)", callback_data="user:manage_quick_replies")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="user:menu")]
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "user:add_quick_reply")
async def user_add_quick_reply_start(callback: CallbackQuery, state: FSMContext):
    if not await db.has_access(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return
    await callback.message.edit_text(
        "✏️ Введи **название** кнопки (коротко, например: «Цена», «Время работы»):"
    )
    await state.set_state("waiting_quick_title")  # простой строковый state для примера
    await callback.answer()

# Упрощённая обработка добавления (для демонстрации)
@dp.message(F.text & ~F.command)
async def handle_quick_reply_input(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state and current_state.startswith("waiting_registration_"):
        return
    if current_state == "waiting_quick_title":
        await state.update_data(title=message.text.strip())
        await message.answer("Теперь введи **текст** ответа (можно с переносами строк):")
        await state.set_state("waiting_quick_text")
    elif current_state == "waiting_quick_text":
        data = await state.get_data()
        title = data.get("title")
        text = message.text.strip()
        user_id = message.from_user.id

        await db.add_quick_reply(telegram_id=user_id, title=title, text=text)
        await message.answer(f"✅ Быстрый ответ «{title}» добавлен!")
        await state.clear()
        # Показать меню быстрых ответов заново
        replies = await db.get_all_quick_replies_for_user(user_id)
        text_out = "💬 <b>Мои быстрые ответы</b>\n\n"
        for r in replies:
            owner_mark = "🌐 " if r["telegram_id"] is None else "👤 "
            text_out += f"{owner_mark}<b>{r['title']}</b>\n{r['text'][:60]}...\n\n"
        await message.answer(text_out, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Мои быстрые ответы", callback_data="user:quick_replies")]
        ]), parse_mode="HTML")


# ===================== УПРАВЛЕНИЕ ЗАКАЗАМИ АВИТО =====================

@dp.callback_query(F.data == "user:orders")
async def user_orders_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await db.has_access(user_id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return

    text = (
        "📦 <b>Управление заказами Авито</b>\n\n"
        "Здесь ты видишь все заказы, сроки отправки и можешь быстро перейти в чат с клиентом.\n\n"
        "Выбери раздел:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Активные заказы", callback_data="orders:active")],
        [InlineKeyboardButton(text="✅ Доставленные", callback_data="orders:delivered")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="user:menu")]
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "orders:active")
async def show_active_orders(callback: CallbackQuery):
    orders = await db.get_active_orders()

    if not orders:
        text = "🟢 Активных заказов пока нет."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="user:orders")]])
    else:
        text = "🟢 <b>Активные заказы</b>\n\n"
        kb_buttons = []
        for order in orders:
            profile = order["profile_name"] if order["profile_name"] else "Неизвестный профиль"
            text += (
                f"📦 <b>{order['item_title']}</b>\n"
                f"📍 Профиль: <b>{profile}</b>\n"
                f"👤 {order['buyer_name']}\n"
                f"📅 Срок отправки: <b>{order['ship_by_date']}</b>\n"
                f"Статус: {order['status']}\n\n"
            )
            kb_buttons.append([
                InlineKeyboardButton(text=f"💬 Чат с {order['buyer_name'][:15]}", callback_data=f"order:chat:{order['id']}")
            ])
            if order['status'] == 'active':
                kb_buttons.append([
                    InlineKeyboardButton(text="🚚 Отметить отправленным", callback_data=f"order:ship:{order['id']}")
                ])

        kb_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="user:orders")])
        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "orders:delivered")
async def show_delivered_orders(callback: CallbackQuery):
    orders = await db.get_delivered_orders()

    if not orders:
        text = "✅ Доставленных заказов пока нет."
    else:
        text = "✅ <b>Доставленные заказы</b>\n\n"
        for order in orders:
            profile = order["profile_name"] if order["profile_name"] else "Неизвестный профиль"
            text += (
                f"📦 <b>{order['item_title']}</b>\n"
                f"📍 Профиль: <b>{profile}</b>\n"
                f"👤 {order['buyer_name']}\n"
                f"📅 {order['ship_by_date']}\n\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="user:orders")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("order:ship:"))
async def mark_order_shipped(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    await db.update_order_status(order_id, "shipped")
    await callback.answer("Статус изменён на 'отправлен'")
    await show_active_orders(callback)  # обновляем список

@dp.callback_query(F.data.startswith("order:chat:"))
async def open_order_chat(callback: CallbackQuery):
    order_id = int(callback.data.split(":")[2])
    order = await db.get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    chat_id = order["chat_id"]
    messages = await db.get_chat_messages(chat_id)
    profile = order.get("profile_name", "Неизвестный профиль")

    text = f"💬 <b>Чат с {order['buyer_name']}</b>\n📦 {order['item_title']}\n📍 Профиль: <b>{profile}</b>\n\n"

    if not messages:
        text += "История сообщений пока пустая. (В реальной версии здесь будет полная переписка из Авито)"
        # Добавим тестовые сообщения для демонстрации
        await db.add_chat_message(chat_id, "client", "Здравствуйте, когда сможете отправить?")
        await db.add_chat_message(chat_id, "seller", "Добрый день! Можем отправить завтра до 18:00.")
        messages = await db.get_chat_messages(chat_id)

    for msg in messages:
        if msg["sender"] == "client":
            text += f"👤 <b>Клиент:</b> {msg['text']}\n"
        else:
            text += f"🏪 <b>Мы:</b> {msg['text']}\n"
        if msg["timestamp"]:
            text += f"_{msg['timestamp']}_\n\n"

    text += "\n(Здесь будет возможность отвечать и удалять сообщения)"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Ответить (позже)", callback_data=f"order:reply:{order_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить последнее сообщение (позже)", callback_data=f"order:delete_last:{order_id}")],
        [InlineKeyboardButton(text="🔙 Назад к заказам", callback_data="orders:active")]
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ===================== АДМИН: УПРАВЛЕНИЕ ФИЛИАЛАМИ =====================

@dp.callback_query(F.data == "admin:stores")
async def admin_stores_menu(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Только владелец", show_alert=True)
        return

    stores = await db.get_all_stores(enabled_only=False)
    text = "🏪 <b>Управление филиалами</b>\n\n"
    if not stores:
        text += "Пока нет филиалов. Добавь первый."
    else:
        for s in stores[:10]:
            status = "✅" if s["enabled"] else "🚫"
            text += f"{status} {s['short_name'] or s['name']} (id: {s['id']})\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить новый филиал", callback_data="admin:add_store")],
        [InlineKeyboardButton(text="📋 Показать все", callback_data="admin:list_stores")],
        [InlineKeyboardButton(text="🔙 Назад в админ-меню", callback_data="admin:menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin:add_store")
async def admin_add_store_start(callback: CallbackQuery, state: FSMContext):
    if not await db.is_owner(callback.from_user.id):
        await callback.answer("Только владелец", show_alert=True)
        return
    await callback.message.edit_text(
        "✏️ Введи название филиала (полный адрес):\n\n"
        "Пример: Ростов-на-Дону, ул. Ленина, д. 15\n"
        "Или коротко: Батайск-Центр"
    )
    await state.set_state("waiting_for_store_name")
    await callback.answer()

# Простой обработчик текста для добавления магазина (FSM)
@dp.message(F.text & ~F.command)
async def process_add_store_name(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != "waiting_for_store_name":
        return
    if not await db.is_owner(message.from_user.id):
        return
    name = message.text.strip()
    store_id = await db.add_store(name=name, short_name=name.split(",")[0] if "," in name else name)
    await message.answer(f"✅ Филиал добавлен (id: {store_id})\n\n{name}")
    await state.clear()
    # Показать админ меню заново
    await message.answer("Меню управления филиалами:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 Управление филиалами", callback_data="admin:stores")]
    ]))

# ===================== УПРАВЛЕНИЕ РАССЫЛКАМИ (с типами) =====================

@dp.callback_query(F.data == "admin:mailings")
async def admin_mailings_menu(callback: CallbackQuery):
    if not await db.is_owner(callback.from_user.id) and not await db.is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    text = (
        "📨 <b>Управление рассылками</b>\n\n"
        "Выберите тип рассылки:\n\n"
        "• <b>Единоразовая</b> — отправить сразу во все непрочитанные чаты\n"
        "• <b>По времени</b> — запланировать отправку на конкретное время\n"
        "• <b>По периоду (триггер)</b> — автоматически отправлять текст, когда от покупателя приходит новое сообщение\n\n"
        "Также можно посмотреть активные рассылки."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Единоразовая рассылка", callback_data="mailing:one_time")],
        [InlineKeyboardButton(text="⏰ Рассылка по времени", callback_data="mailing:scheduled")],
        [InlineKeyboardButton(text="🔄 Рассылка по триггеру (новое сообщение)", callback_data="mailing:triggered")],
        [InlineKeyboardButton(text="📋 Активные рассылки", callback_data="mailing:list")],
        [InlineKeyboardButton(text="🔙 Назад в админ-меню", callback_data="admin:menu")]
    ])

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# FSM states for mailings (using string states for simplicity, can be improved)
@dp.callback_query(F.data.startswith("mailing:"))
async def mailing_type_start(callback: CallbackQuery, state: FSMContext):
    if not await db.is_owner(callback.from_user.id) and not await db.is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    mailing_type = callback.data.split(":")[1]

    if mailing_type == "one_time":
        await state.update_data(mailing_type="one_time")
        await callback.message.edit_text("✏️ Введите текст для единоразовой рассылки:")
        await state.set_state("waiting_mailing_text")
    elif mailing_type == "scheduled":
        await state.update_data(mailing_type="scheduled")
        await callback.message.edit_text("✏️ Введите текст для рассылки по времени:")
        await state.set_state("waiting_mailing_text_scheduled")
    elif mailing_type == "triggered":
        await state.update_data(mailing_type="triggered")
        await callback.message.edit_text("✏️ Введите текст, который бот будет автоматически отправлять при новом сообщении от покупателя:")
        await state.set_state("waiting_mailing_text_triggered")
    elif mailing_type == "list":
        mailings = await db.get_active_mailings()
        if not mailings:
            text = "Активных рассылок пока нет."
        else:
            text = "📋 <b>Активные рассылки:</b>\n\n"
            for m in mailings:
                text += f"ID: {m['id']} | Тип: {m['type']} | Текст: {m['text'][:50]}...\n"
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin:mailings")]]), parse_mode="HTML")
        await callback.answer()
        return

    await callback.answer()

@dp.message(F.text & ~F.command)
async def handle_mailing_text(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state and current_state.startswith("waiting_registration_"):
        return
    user_id = message.from_user.id

    if current_state == "waiting_mailing_text":
        # One-time
        text = message.text.strip()
        mailing_id = await db.create_mailing(user_id, "one_time", text)
        await message.answer(f"✅ Единоразовая рассылка создана (ID: {mailing_id}).\n\nВ реальной версии она сразу отправится во все непрочитанные чаты всех профилей.")
        await state.clear()
        # TODO: Здесь вызвать реальную отправку через AvitoClient для всех аккаунтов

    elif current_state == "waiting_mailing_text_scheduled":
        await state.update_data(text=message.text.strip())
        await message.answer("⏰ Введите время отправки в формате YYYY-MM-DD HH:MM (например 2026-07-10 14:00):")
        await state.set_state("waiting_mailing_schedule_time")

    elif current_state == "waiting_mailing_text_triggered":
        await state.update_data(text=message.text.strip())
        await message.answer("⏰ Хотите ограничить рассылку по времени? (да/нет)\n\nПример: только с 9:00 до 20:00 по будням.")
        await state.set_state("waiting_mailing_trigger_time_confirm")

@dp.message(F.text & ~F.command)
async def handle_mailing_schedule(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == "waiting_mailing_schedule_time":
        schedule_time = message.text.strip()
        data = await state.get_data()
        text = data.get("text")
        user_id = message.from_user.id

        mailing_id = await db.create_mailing(user_id, "scheduled", text, schedule_time=schedule_time)
        await message.answer(f"✅ Рассылка по времени создана (ID: {mailing_id}).\n\nЗапланирована на {schedule_time}.\n\n(Для реального выполнения нужно подключить планировщик вроде APScheduler).")
        await state.clear()


@dp.message(F.text & ~F.command)
async def handle_mailing_trigger_time(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state and current_state.startswith("waiting_registration_"):
        return
    user_id = message.from_user.id

    if current_state == "waiting_mailing_trigger_time_confirm":
        answer = message.text.strip().lower()
        data = await state.get_data()
        text = data.get("text")

        if answer in ["да", "yes", "y", "давай"]:
            await state.update_data(text=text)
            await message.answer("Введите время начала в формате HH:MM (например 09:00):")
            await state.set_state("waiting_mailing_trigger_time_start")
        else:
            # No restrictions
            mailing_id = await db.create_mailing(user_id, "triggered", text, trigger_condition="new_buyer_message")
            await message.answer(f"✅ Триггерная рассылка создана (ID: {mailing_id}). Без ограничений по времени.")
            await state.clear()

    elif current_state == "waiting_mailing_trigger_time_start":
        await state.update_data(time_start=message.text.strip())
        await message.answer("Введите время окончания в формате HH:MM (например 20:00):")
        await state.set_state("waiting_mailing_trigger_time_end")

    elif current_state == "waiting_mailing_trigger_time_end":
        await state.update_data(time_end=message.text.strip())
        await message.answer("Введите дни (1=Пн,7=Вс) через запятую или 'all' (например 1,2,3,4,5):")
        await state.set_state("waiting_mailing_trigger_days")

    elif current_state == "waiting_mailing_trigger_days":
        days = message.text.strip()
        data = await state.get_data()
        text = data.get("text")
        time_start = data.get("time_start")
        time_end = data.get("time_end")

        mailing_id = await db.create_mailing(
            user_id, "triggered", text,
            trigger_condition="new_buyer_message",
            time_start=time_start, time_end=time_end, days_of_week=days
        )
        await message.answer(
            f"✅ Триггерная рассылка с временными рамками создана (ID: {mailing_id}).\n\n"
            f"Текст: {text}\nВремя: {time_start}-{time_end}\nДни: {days}"
        )
        await state.clear()


# ===================== РЕГИСТРАЦИЯ НОВЫХ ПОЛЬЗОВАТЕЛЕЙ =====================

@dp.message(F.text & ~F.command)
async def handle_registration(message: Message, state: FSMContext):
    current_state = await state.get_state()
    text = message.text.strip()

    # Клавиатура "Продолжить"
    continue_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Продолжить")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    if current_state == "waiting_registration_full_name":
        if text == "Продолжить":
            return  # игнор, если нажал слишком рано
        await state.update_data(full_name=text)
        await message.answer(
            "📍 Введите **краткое название точки** (филиала), например: «Ростов-Центр» или «Батайск-1»:",
            reply_markup=continue_kb
        )
        await state.set_state("waiting_registration_branch")

    elif current_state == "waiting_registration_branch":
        if text == "Продолжить":
            return
        await state.update_data(branch_short_name=text)
        await message.answer(
            "📱 Введите ваш **номер телефона** (с кодом страны, например +7...):",
            reply_markup=continue_kb
        )
        await state.set_state("waiting_registration_phone")

    elif current_state == "waiting_registration_phone":
        if text == "Продолжить":
            # Сохраняем и отправляем заявку
            data = await state.get_data()
            telegram_id = data.get("telegram_id")
            username = data.get("username", "")
            full_name = data.get("full_name")
            branch_short_name = data.get("branch_short_name")
            phone = data.get("phone", text)

            await db.create_or_update_user(
                telegram_id=telegram_id,
                username=username,
                full_name=full_name,
                branch_short_name=branch_short_name,
                phone=phone,
                status="pending"
            )

            try:
                await bot.send_message(
                    OWNER_TELEGRAM_ID,
                    f"🆕 **Новая заявка на доступ к боту!**\n\n"
                    f"👤 **ФИО:** {full_name}\n"
                    f"📍 **Точка/Филиал:** {branch_short_name}\n"
                    f"📱 **Телефон:** {phone}\n"
                    f"🔗 **Username:** @{username}\n"
                    f"🆔 **Telegram ID:** {telegram_id}\n\n"
                    f"Проверьте данные и подтвердите доступ:",
                    reply_markup=get_approval_keyboard(telegram_id),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить заявку владельцу: {e}")

            await message.answer(
                "✅ Спасибо! Ваши данные отправлены администратору для проверки.\n\n"
                "Как только доступ будет одобрен, бот пришлёт уведомление.",
                reply_markup=ReplyKeyboardMarkup(remove_keyboard=True)
            )
            await state.clear()
            return

        # Сохраняем телефон и показываем кнопку "Продолжить"
        await state.update_data(phone=text)
        await message.answer(
            "Нажмите кнопку **Продолжить**, чтобы отправить заявку.",
            reply_markup=continue_kb
        )


# ===================== Подключение роутеров (регистрация имеет высокий приоритет) =====================
dp.include_router(registration_router)   # Регистрация первой — высокий приоритет

# ===================== Запуск =====================
async def main():
    await db.init_db()
    logger.info("Бот запускается...")

    # Здесь позже добавим фоновую задачу polling Avito
    # asyncio.create_task(start_avito_polling())

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
