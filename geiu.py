import asyncio
import logging
import sqlite3
import os
import json
import requests
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_IDS = [6997318168]  # ⬅️ ВАШ ID ОТКРЫТО
CRYPTOBOT_TOKEN = os.environ.get("CRYPTOBOT_TOKEN", "")

# Настройки
CARD_NUMBER = "2200700527205453"
STAR_RATE = 1.5  # 1 звезда = 1.5 RUB
USD_RATE = 85.0  # 1 USD = 85 RUB

PREMIUM_PRICES = {
    "3m": {"rub": 1124.11, "name": "3 месяца"},
    "6m": {"rub": 1498.81, "name": "6 месяцев"}, 
    "1y": {"rub": 2716.59, "name": "1 год"}
}

REPUTATION_CHANNEL = "https://t.me/+3pbAABRgo1ljOTJi"
NEWS_CHANNEL = "https://t.me/NewsDigistars"
SUPPORT_USER = "swordSar"

# ========== CRYPTOBOT ==========
class CryptoBotAPI:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://pay.crypt.bot/api"
    
    async def create_invoice(self, amount, description=""):
        """Создать счет для оплаты"""
        try:
            url = f"{self.base_url}/createInvoice"
            headers = {"Crypto-Pay-API-Token": self.token}
            
            amount_usdt = amount / 85.0
            
            data = {
                "asset": "USDT",
                "amount": str(round(amount_usdt, 2)),
                "description": description[:1024],
                "paid_btn_name": "openBot",
                "paid_btn_url": "https://t.me/DigiStoreBot",
                "payload": f"order_{int(datetime.now().timestamp())}",
                "allow_anonymous": False
            }
            
            response = requests.post(url, json=data, headers=headers, timeout=30)
            result = response.json()
            
            if result.get("ok"):
                invoice = result["result"]
                return {
                    "success": True,
                    "invoice_id": invoice["invoice_id"],
                    "pay_url": invoice["pay_url"],
                    "amount": invoice["amount"],
                    "asset": invoice["asset"]
                }
            else:
                return {"success": False, "error": result.get("error", {}).get("name", "Unknown error")}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def check_invoice_status(self, invoice_id):
        """Проверить статус инвойса в CryptoBot"""
        try:
            url = f"{self.base_url}/getInvoices"
            headers = {"Crypto-Pay-API-Token": self.token}
            
            params = {"invoice_ids": invoice_id}
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            result = response.json()
            
            if result.get("ok"):
                invoice = result["result"]["items"][0]
                return {
                    "success": True,
                    "status": invoice["status"],
                    "paid_at": invoice.get("paid_at"),
                    "amount": invoice.get("amount")
                }
            else:
                return {"success": False, "error": result.get("error", {}).get("name", "Unknown error")}
                
        except Exception as e:
            return {"success": False, "error": str(e)}

# Инициализируем CryptoBot если есть токен
cryptobot = CryptoBotAPI(CRYPTOBOT_TOKEN) if CRYPTOBOT_TOKEN else None

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self, db_name="digistore.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_type TEXT,
            recipient TEXT,
            details TEXT,
            amount_rub REAL,
            payment_method TEXT,
            status TEXT DEFAULT 'pending',
            invoice_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        self.conn.commit()
    
    def add_user(self, user_id, username, full_name):
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
            (user_id, username, full_name)
        )
        self.conn.commit()
    
    def add_order(self, user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id=None):
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO orders 
            (user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id) 
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, order_type, recipient, details, amount_rub, payment_method, invoice_id)
        )
        order_id = cursor.lastrowid
        self.conn.commit()
        return order_id
    
    def update_order_status(self, order_id, status):
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (status, order_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
    
    def update_invoice_id(self, order_id, invoice_id):
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET invoice_id = ? WHERE id = ?",
            (invoice_id, order_id)
        )
        self.conn.commit()
    
    def add_payment_photo(self, order_id, file_id):
        """Сохранить photo_file_id в details заказа"""
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE orders SET details = json_set(details, '$.payment_photo', ?) WHERE id = ?",
            (file_id, order_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0
    
    def get_active_orders(self):
        """Все активные заказы (не выполненные и не отмененные)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, user_id, order_type, recipient, details, amount_rub, 
                   payment_method, status, created_at 
            FROM orders 
            WHERE status NOT IN ('completed', 'cancelled')
            ORDER BY created_at DESC
        """)
        return cursor.fetchall()
    
    def get_order(self, order_id):
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT user_id, order_type, recipient, details, amount_rub, 
                   payment_method, status, invoice_id, created_at 
            FROM orders WHERE id = ?
        """, (order_id,))
        return cursor.fetchone()

# ========== ИНИЦИАЛИЗАЦИЯ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db = Database()

user_states = {}
admin_confirmations = {}  # Для подтверждения выполнения заказа

# ========== КЛАВИАТУРЫ ==========
def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Купить звезды", callback_data="buy_stars")],
        [InlineKeyboardButton(text="👑 Купить премиум", callback_data="buy_premium")],
        [InlineKeyboardButton(text="💱 Обмен валют", callback_data="exchange")],
        [InlineKeyboardButton(text="📊 Информация", callback_data="info")],
        [InlineKeyboardButton(text="🆘 Тех поддержка", url=f"https://t.me/{SUPPORT_USER}")]
    ])

def back_to_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def admin_menu_kb():
    """Упрощенное админ меню - только 2 пункта"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Активные заказы", callback_data="admin_active_orders")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
    ])

def confirm_payment_kb(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"confirm_paid_{order_id}")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])

def back_kb(target):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=target)]
    ])

# ========== ГЛАВНОЕ МЕНЮ ==========
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Команда /start"""
    user_id = message.from_user.id
    username = message.from_user.username or ""
    full_name = message.from_user.full_name
    
    db.add_user(user_id, username, full_name)
    
    caption = (
        "🪐 **Digi Store - Главное меню**\n\n"
        "C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары\n\n"
        "Выберите действие:"
    )
    
    await message.answer(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )

async def show_main_menu(message: types.Message):
    caption = (
        "🪐 **Digi Store - Главное меню**\n\n"
        "C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары\n\n"
        "Выберите действие:"
    )
    
    await message.answer(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )

# ========== ПОКУПКА ЗВЕЗД ==========
@dp.callback_query(F.data == "main_menu")
async def main_menu_handler(callback: types.CallbackQuery):
    caption = (
        "🪐 **Digi Store - Главное меню**\n\n"
        "C помощью нашего магазина вы можете:\n"
        "• ⭐️ Купить Telegram Stars\n"
        "• 👑 Купить Telegram Premium\n"
        "• 💱 Обменять рубли на доллары\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=main_menu_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "buy_stars")
async def buy_stars_handler(callback: types.CallbackQuery):
    user_states[callback.from_user.id] = {"action": "waiting_stars_recipient"}
    
    caption = (
        "⭐️ **Покупка Telegram Stars**\n\n"
        f"Курс: **1 звезда = {STAR_RATE} RUB**\n"
        "Диапазон: от 50 до 1,000,000 звезд\n\n"
        "✏️ Введите username получателя (можно с @):"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=back_kb("main_menu"),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "buy_premium")
async def buy_premium_handler(callback: types.CallbackQuery):
    price_text = ""
    for key, value in PREMIUM_PRICES.items():
        price_text += f"• {value['name']}: {value['rub']:.2f} RUB\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3 месяца", callback_data="premium_3m")],
        [InlineKeyboardButton(text="6 месяцев", callback_data="premium_6m")],
        [InlineKeyboardButton(text="1 год", callback_data="premium_1y")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    caption = (
        "👑 **Покупка Telegram Premium**\n\n"
        "Выберите период:\n\n"
        f"{price_text}"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("premium_"))
async def premium_period_handler(callback: types.CallbackQuery):
    period = callback.data.replace("premium_", "")
    
    if period in PREMIUM_PRICES:
        user_states[callback.from_user.id] = {
            "action": "waiting_premium_recipient",
            "period": period,
            "amount_rub": PREMIUM_PRICES[period]["rub"]
        }
        
        caption = (
            f"👑 **Telegram Premium - {PREMIUM_PRICES[period]['name']}**\n\n"
            f"Цена: **{PREMIUM_PRICES[period]['rub']:.2f} RUB**\n\n"
            "✏️ Введите username получателя (можно с @):"
        )
        
        await callback.message.edit_text(
            text=caption,
            reply_markup=back_kb("buy_premium"),
            parse_mode="Markdown"
        )
    
    await callback.answer()

@dp.callback_query(F.data == "exchange")
async def exchange_handler(callback: types.CallbackQuery):
    user_states[callback.from_user.id] = {"action": "waiting_exchange_amount"}
    
    caption = (
        "💱 **Обмен валют**\n\n"
        f"Курс: **1 USD = {USD_RATE} RUB**\n\n"
        "Введите сумму в рублях для обмена:\n"
        "(Минимум: 100 RUB)\n\n"
        "💳 **Оплата только картой!**"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=back_kb("main_menu"),
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.callback_query(F.data == "info")
async def info_handler(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Репутация", url=REPUTATION_CHANNEL)],
        [InlineKeyboardButton(text="📰 Новости", url=NEWS_CHANNEL)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    caption = "📊 **Информация**\n\nВыберите раздел:"
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== АДМИН ПАНЕЛЬ (УПРОЩЕННАЯ) ==========
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    """Админ панель - только кнопки"""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен")
        return
    
    caption = (
        "🛠️ **Админ панель**\n\n"
        "Выберите действие:"
    )
    
    await message.answer(
        text=caption,
        reply_markup=admin_menu_kb(),
        parse_mode="Markdown"
    )

# Показ активных заказов
@dp.callback_query(F.data == "admin_active_orders")
async def admin_active_orders_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    orders = db.get_active_orders()
    
    if not orders:
        caption = "📦 **Активные заказы**\n\nНет активных заказов"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_active_orders")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
        ])
    else:
        caption = "📦 **Активные заказы**\n\n"
        
        # Группируем заказы по статусу
        for order in orders:
            order_id, user_id, order_type, recipient, details, amount_rub, payment_method, status, created_at = order
            
            # Статусы в emoji
            status_emoji = {
                'pending': '⏳',
                'waiting_payment': '💳',
                'waiting_confirmation': '📸',
                'waiting_crypto': '💎',
                'confirmed': '✅'
            }.get(status, '❓')
            
            # Форматируем дату
            created_short = str(created_at)[:16] if created_at else "---"
            
            caption += f"{status_emoji} **Заказ #{order_id}**\n"
            caption += f"📦 Тип: {order_type}\n"
            
            if order_type == "stars":
                try:
                    details_dict = json.loads(details) if details else {}
                    stars = details_dict.get("stars", 0)
                    caption += f"⭐️ Количество: {stars} звезд\n"
                except:
                    pass
            elif order_type == "premium":
                try:
                    details_dict = json.loads(details) if details else {}
                    period = details_dict.get("period", "")
                    period_name = PREMIUM_PRICES.get(period, {}).get("name", "")
                    caption += f"👑 Период: {period_name}\n"
                except:
                    pass
            elif order_type == "exchange":
                try:
                    details_dict = json.loads(details) if details else {}
                    amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                    caption += f"💸 К выдаче: {amount_usd:.2f} USD\n"
                except:
                    pass
            
            if recipient:
                caption += f"👤 Получатель: @{recipient}\n"
            
            caption += f"💰 Сумма: {amount_rub:.2f} RUB\n"
            caption += f"💳 Метод: {payment_method}\n"
            caption += f"📅 Дата: {created_short}\n"
            caption += f"📊 Статус: {status}\n\n"
        
        keyboard_buttons = []
        for order in orders:
            order_id = order[0]
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"📦 Управление заказом #{order_id}", 
                    callback_data=f"manage_order_{order_id}"
                )
            ])
        
        keyboard_buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_active_orders")])
        keyboard_buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# Управление конкретным заказом (С ФОТО ОПЛАТЫ)
@dp.callback_query(F.data.startswith("manage_order_"))
async def manage_order_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("manage_order_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    # Получаем детали заказа
    details_dict = {}
    try:
        if details:
            details_dict = json.loads(details)
    except:
        pass
    
    # Проверяем есть ли фото оплаты
    photo_file_id = details_dict.get("payment_photo") if details_dict else None
    
    if photo_file_id and status in ["waiting_confirmation", "confirmed"]:
        # Отправляем фото оплаты админу
        try:
            photo_caption = f"📸 **Фото оплаты заказа #{order_id}**\n\n"
            photo_caption += f"🆔 Заказ: #{order_id}\n"
            photo_caption += f"📦 Тип: {order_type}\n"
            photo_caption += f"💰 Сумма: {amount_rub:.2f} RUB"
            
            await bot.send_photo(
                callback.message.chat.id,
                photo=photo_file_id,
                caption=photo_caption,
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Ошибка отправки фото: {e}")
            await callback.message.answer("❌ Не удалось загрузить фото оплаты")
    
    # Формируем информацию о заказе
    caption = f"🛠️ **Управление заказом #{order_id}**\n\n"
    
    # Информация о пользователе
    caption += f"👤 **Покупатель:**\n"
    caption += f"   ID: `{user_id}`\n"
    
    # Информация о заказе
    caption += f"\n📦 **Детали заказа:**\n"
    caption += f"   Тип: {order_type}\n"
    
    if order_type == "stars":
        stars = details_dict.get("stars", 0)
        caption += f"   ⭐️ Звезд: {stars}\n"
    elif order_type == "premium":
        period = details_dict.get("period", "")
        period_name = PREMIUM_PRICES.get(period, {}).get("name", "")
        caption += f"   👑 Период: {period_name}\n"
    elif order_type == "exchange":
        amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
        caption += f"   💸 К выдаче: {amount_usd:.2f} USD\n"
    
    if recipient:
        caption += f"   👤 Получатель: @{recipient}\n"
    
    caption += f"   💰 Сумма: {amount_rub:.2f} RUB\n"
    caption += f"   💳 Метод: {payment_method}\n"
    caption += f"   📊 Статус: {status}\n"
    
    if photo_file_id:
        caption += f"   📸 Фото оплаты: ✅ Есть\n"
    else:
        caption += f"   📸 Фото оплаты: ❌ Нет\n"
    
    # Кнопки управления
    keyboard_buttons = []
    
    if status == "waiting_confirmation":
        # Заказ ожидает проверки фото
        keyboard_buttons.append([
            InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"admin_confirm_payment_{order_id}")
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="❌ Отклонить заказ", callback_data=f"admin_reject_order_{order_id}")
        ])
    
    elif status == "waiting_crypto":
        # CryptoBot оплата
        keyboard_buttons.append([
            InlineKeyboardButton(text="💎 Проверить оплату", callback_data=f"check_crypto_{order_id}")
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="❌ Отменить заказ", callback_data=f"admin_reject_order_{order_id}")
        ])
    
    elif status == "confirmed":
        # Заказ подтвержден, можно выполнить
        keyboard_buttons.append([
            InlineKeyboardButton(text="📦 Я передал товар", callback_data=f"admin_delivered_{order_id}")
        ])
    
    else:
        # Другие статусы
        keyboard_buttons.append([
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_confirm_payment_{order_id}")
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_reject_order_{order_id}")
        ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"manage_order_{order_id}"),
        InlineKeyboardButton(text="📦 К заказам", callback_data="admin_active_orders")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.answer(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# Подтверждение оплаты (админ)
@dp.callback_query(F.data.startswith("admin_confirm_payment_"))
async def admin_confirm_payment_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_confirm_payment_", ""))
    
    # Сохраняем подтверждение
    admin_confirmations[callback.from_user.id] = {
        "action": "confirm_payment",
        "order_id": order_id
    }
    
    caption = (
        f"⚠️ **ВНИМАНИЕ!**\n\n"
        f"Вы собираетесь подтвердить оплату заказа #{order_id}.\n\n"
        f"**Перед подтверждением проверьте:**\n"
        f"1. Фото оплаты соответствует сумме\n"
        f"2. Реквизиты отправителя верны\n"
        f"3. Время оплаты корректное\n\n"
        f"Если всё верно, нажмите кнопку ниже для окончательного подтверждения."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ДА, я всё проверил и подтверждаю", callback_data=f"admin_final_confirm_{order_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"manage_order_{order_id}")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# Финальное подтверждение
@dp.callback_query(F.data.startswith("admin_final_confirm_"))
async def admin_final_confirm_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_final_confirm_", ""))
    
    # Меняем статус заказа
    db.update_order_status(order_id, "confirmed")
    
    # Уведомляем пользователя
    order = db.get_order(order_id)
    if order:
        user_id = order[0]
        try:
            await bot.send_message(
                user_id,
                f"✅ **Ваш заказ #{order_id} подтвержден!**\n\n"
                f"Товар будет отправлен в течение 15 минут - 3 часа."
            )
        except:
            pass
    
    # Удаляем подтверждение
    if callback.from_user.id in admin_confirmations:
        del admin_confirmations[callback.from_user.id]
    
    await callback.answer("✅ Заказ подтвержден!")
    
    # Возвращаем к списку заказов
    await admin_active_orders_handler(callback)

# Отклонение заказа (админ)
@dp.callback_query(F.data.startswith("admin_reject_order_"))
async def admin_reject_order_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_reject_order_", ""))
    
    # Сохраняем подтверждение
    admin_confirmations[callback.from_user.id] = {
        "action": "reject_order",
        "order_id": order_id
    }
    
    caption = (
        f"⚠️ **ВНИМАНИЕ!**\n\n"
        f"Вы собираетесь отклонить заказ #{order_id}.\n\n"
        f"**Перед отклонением проверьте:**\n"
        f"1. Причина отклонения обоснована\n"
        f"2. Пользователь будет уведомлен\n"
        f"3. Деньги будут возвращены при необходимости\n\n"
        f"Если всё верно, нажмите кнопку ниже для окончательного отклонения."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ ДА, отклоняю заказ", callback_data=f"admin_final_reject_{order_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"manage_order_{order_id}")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# Финальное отклонение
@dp.callback_query(F.data.startswith("admin_final_reject_"))
async def admin_final_reject_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_final_reject_", ""))
    
    # Меняем статус заказа
    db.update_order_status(order_id, "cancelled")
    
    # Уведомляем пользователя
    order = db.get_order(order_id)
    if order:
        user_id = order[0]
        try:
            await bot.send_message(
                user_id,
                f"❌ **Ваш заказ #{order_id} отклонен.**\n\n"
                f"По вопросам обращайтесь в поддержку."
            )
        except:
            pass
    
    # Удаляем подтверждение
    if callback.from_user.id in admin_confirmations:
        del admin_confirmations[callback.from_user.id]
    
    await callback.answer("❌ Заказ отклонен")
    
    # Возвращаем к списку заказов (заказ исчезнет из списка)
    await admin_active_orders_handler(callback)

# Админ подтвердил передачу товара
@dp.callback_query(F.data.startswith("admin_delivered_"))
async def admin_delivered_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_delivered_", ""))
    
    # Сохраняем подтверждение
    admin_confirmations[callback.from_user.id] = {
        "action": "delivered",
        "order_id": order_id
    }
    
    caption = (
        f"⚠️ **ПОДТВЕРЖДЕНИЕ ПЕРЕДАЧИ**\n\n"
        f"Вы подтверждаете, что передали товар по заказу #{order_id}?\n\n"
        f"**Перед подтверждением проверьте:**\n"
        f"1. Товар передан получателю\n"
        f"2. Получатель подтвердил получение\n"
        f"3. Всё соответствует заказу\n\n"
        f"После подтверждения заказ будет помечен как выполненный и исчезнет из списка."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ДА, товар передан", callback_data=f"admin_final_delivered_{order_id}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"manage_order_{order_id}")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# Финальное подтверждение передачи
@dp.callback_query(F.data.startswith("admin_final_delivered_"))
async def admin_final_delivered_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    order_id = int(callback.data.replace("admin_final_delivered_", ""))
    
    # Меняем статус заказа на выполненный
    db.update_order_status(order_id, "completed")
    
    # Уведомляем пользователя
    order = db.get_order(order_id)
    if order:
        user_id = order[0]
        try:
            await bot.send_message(
                user_id,
                f"🎉 **Ваш заказ #{order_id} выполнен!**\n\n"
                f"Спасибо за покупку! 😊"
            )
        except:
            pass
    
    # Удаляем подтверждение
    if callback.from_user.id in admin_confirmations:
        del admin_confirmations[callback.from_user.id]
    
    await callback.answer("✅ Заказ выполнен!")
    
    # Возвращаем к списку заказов (заказ исчезнет из списка)
    await admin_active_orders_handler(callback)

# Статистика
@dp.callback_query(F.data == "admin_stats")
async def admin_stats_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    # Простая статистика
    orders = db.get_active_orders()
    active_count = len(orders)
    
    caption = (
        f"📊 **Статистика магазина**\n\n"
        f"📦 Активных заказов: {active_count}\n\n"
        f"Для детальной статистики используйте аналитику."
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

# Назад в админ меню
@dp.callback_query(F.data == "admin_back")
async def admin_back_handler(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен")
        return
    
    caption = (
        "🛠️ **Админ панель**\n\n"
        "Выберите действие:"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=admin_menu_kb(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== ОБРАБОТКА ФОТО ОПЛАТЫ ==========
@dp.message(F.photo)
async def handle_payment_photo(message: types.Message):
    """Обработка фото оплаты"""
    user_id = message.from_user.id
    
    if user_id not in user_states:
        await message.answer("Пожалуйста, используйте кнопки меню.")
        return
    
    state = user_states[user_id]
    
    if state.get("action") == "waiting_payment_photo":
        order_id = state.get("order_id")
        order = db.get_order(order_id)
        
        if not order:
            await message.answer("❌ Заказ не найден")
            return
        
        user_id_db, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
        
        # Получаем file_id фото
        photo_file_id = message.photo[-1].file_id
        
        # Сохраняем фото в базу
        try:
            details_dict = json.loads(details) if details else {}
            details_dict["payment_photo"] = photo_file_id
            db.add_payment_photo(order_id, photo_file_id)
        except:
            pass
        
        # Обновляем статус
        db.update_order_status(order_id, "waiting_confirmation")
        
        # Удаляем состояние
        del user_states[user_id]
        
        # Уведомляем админа с фото
        for admin_id in ADMIN_IDS:
            try:
                # Сначала отправляем фото
                photo_caption = f"📸 **Новое фото оплаты | Заказ #{order_id}**"
                
                await bot.send_photo(
                    admin_id,
                    photo=photo_file_id,
                    caption=photo_caption
                )
                
                # Затем отправляем детали заказа
                admin_message = f"🆕 **Новый заказ ожидает проверки**\n\n"
                admin_message += f"🆔 Заказ: #{order_id}\n"
                admin_message += f"👤 Пользователь: {message.from_user.username or 'Нет юзернейма'}\n"
                admin_message += f"🆔 ID: {message.from_user.id}\n"
                admin_message += f"📦 Тип: {order_type}\n"
                admin_message += f"💰 Сумма: {amount_rub:.2f} RUB\n"
                
                if order_type == "exchange":
                    try:
                        details_dict = json.loads(details) if details else {}
                        amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                        admin_message += f"💸 К выдаче: {amount_usd:.2f} USD\n"
                    except:
                        pass
                else:
                    admin_message += f"👤 Получатель: {recipient}\n"
                
                admin_message += f"\nДля проверки зайдите в /admin → 📦 Активные заказы"
                
                await bot.send_message(admin_id, admin_message)
                
            except Exception as e:
                print(f"Ошибка отправки админу: {e}")
        
        # Сообщение пользователю
        if order_type == "exchange":
            try:
                details_dict = json.loads(details) if details else {}
                amount_usd = details_dict.get("amount_usd", amount_rub / USD_RATE)
                user_message = (
                    f"✅ Фото оплаты получено!\n"
                    f"💸 Вы получаете: {amount_usd:.2f} USD\n"
                    f"💰 Оплачено: {amount_rub:.2f} RUB\n\n"
                    "Заказ передан админу на проверку.\n"
                    "После проверки USD будут отправлены вам в течение 15 минут - 3 часа."
                )
            except:
                user_message = (
                    "✅ Фото оплаты получено! Заказ передан админу на проверку.\n"
                    "После проверки USD будут отправлены вам в течение 15 минут - 3 часа."
                )
        else:
            user_message = (
                "✅ Фото оплаты получено! Заказ передан админу на проверку.\n"
                "После проверки товар будет доставлен в течение 15 минут - 3 часа."
            )
        
        await message.answer(user_message)
        
        # Возвращаем в главное меню
        await show_main_menu(message)

# ========== ОПЛАТА КАРТОЙ ==========
@dp.callback_query(F.data.startswith("card_pay_"))
async def card_payment_handler(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("card_pay_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    # Обновляем статус
    db.update_order_status(order_id, "waiting_payment")
    
    caption = (
        f"💳 **Оплата картой**\n\n"
        f"🆔 Заказ: #{order_id}\n"
        f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
        f"**Реквизиты для перевода:**\n"
        f"`{CARD_NUMBER}`\n\n"
        "**Инструкция:**\n"
        "1. Переведите точную сумму\n"
        "2. Сохраните скриншот перевода\n"
        "3. Нажмите '✅ Я оплатил'\n"
        "4. Отправьте фото оплаты\n"
        "5. Админ проверит оплату\n\n"
        "✅ После проверки товар будет доставлен в течение 15 минут - 3 часа"
    )
    
    await callback.message.edit_text(
        text=caption,
        reply_markup=confirm_payment_kb(order_id),
        parse_mode="Markdown"
    )
    await callback.answer()

# ========== ОПЛАТА CRYPTOBOT ==========
@dp.callback_query(F.data.startswith("crypto_pay_"))
async def crypto_payment_handler(callback: types.CallbackQuery):
    if not cryptobot:
        await callback.answer("❌ CryptoBot временно недоступен")
        return
    
    order_id = int(callback.data.replace("crypto_pay_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    # Создаем счет в CryptoBot
    result = await cryptobot.create_invoice(
        amount=amount_rub,
        description=f"Заказ #{order_id} | {order_type}"
    )
    
    if result["success"]:
        # Сохраняем invoice_id
        db.update_invoice_id(order_id, result["invoice_id"])
        db.update_order_status(order_id, "waiting_crypto")
        
        # Рассчитываем USDT сумму
        amount_usdt = amount_rub / 85.0
        
        caption = (
            f"💎 **Оплата через CryptoBot**\n\n"
            f"🆔 Заказ: #{order_id}\n"
            f"💰 Сумма: {amount_rub:.2f} RUB\n"
            f"💱 К оплате: {amount_usdt:.2f} USDT\n\n"
            "**Для оплаты:**\n"
            "1. Нажмите кнопку ниже\n"
            "2. Оплатите счет в CryptoBot\n"
            "3. После оплаты нажмите '✅ Проверить оплату'\n\n"
            "✅ Оплата проверяется автоматически, товар доставляется в течение 15 минут - 3 часа"
        )
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Оплатить в CryptoBot", url=result["pay_url"])],
            [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_crypto_{order_id}")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(
            text=caption,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await callback.answer(f"❌ Ошибка: {result['error']}")
    
    await callback.answer()

# ========== ПРОВЕРКА CRYPTOBOT ОПЛАТЫ ==========
@dp.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto_payment(callback: types.CallbackQuery):
    if not cryptobot:
        await callback.answer("❌ CryptoBot временно недоступен")
        return
    
    order_id = int(callback.data.replace("check_crypto_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    if not invoice_id:
        await callback.answer("❌ Нет invoice_id для проверки")
        return
    
    await callback.answer("🔍 Проверяем оплату...")
    
    result = await cryptobot.check_invoice_status(invoice_id)
    
    if result["success"]:
        if result["status"] == "paid":
            # ОПЛАТА ПРОШЛА!
            db.update_order_status(order_id, "confirmed")
            
            # Уведомляем админа
            for admin_id in ADMIN_IDS:
                try:
                    admin_message = (
                        f"💎 **CryptoBot оплата ПОДТВЕРЖДЕНА**\n\n"
                        f"🆔 Заказ: #{order_id}\n"
                        f"💰 Сумма: {amount_rub:.2f} RUB\n"
                        f"📦 Тип: {order_type}\n"
                    )
                    
                    if order_type != "exchange":
                        admin_message += f"👤 Получатель: {recipient}\n"
                    
                    admin_message += f"\n✅ Статус: ОПЛАЧЕНО\n"
                    admin_message += f"👨‍💼 Перейдите в админ панель для выполнения заказа"
                    
                    await bot.send_message(admin_id, admin_message)
                except:
                    pass
            
            # Уведомляем пользователя
            try:
                await bot.send_message(
                    user_id,
                    f"✅ **Оплата подтверждена!**\n\n"
                    f"🆔 Ваш заказ: #{order_id}\n"
                    f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
                    f"Товар будет отправлен в течение 15 минут - 3 часа!"
                )
            except:
                pass
            
            # Обновляем сообщение
            caption = (
                f"💎 **Оплата подтверждена!**\n\n"
                f"🆔 Заказ: #{order_id}\n"
                f"💰 Сумма: {amount_rub:.2f} RUB\n"
                f"✅ Статус: ОПЛАЧЕНО\n\n"
                f"Админ уведомлен о платеже. Товар будет отправлен в течение 15 минут - 3 часа!"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            
            await callback.message.edit_text(
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
        elif result["status"] == "active":
            await callback.answer(
                "❌ Счет не оплачен! Пожалуйста, оплатите счет в CryptoBot.",
                show_alert=True
            )
            
        elif result["status"] == "expired":
            db.update_order_status(order_id, "cancelled")
            
            caption = f"❌ **Счет просрочен!**\n\nЗаказ #{order_id} отменен."
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
            ])
            
            await callback.message.edit_text(
                text=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
    else:
        await callback.answer(
            f"❌ Ошибка проверки: {result.get('error', 'Неизвестная ошибка')}",
            show_alert=True
        )

# ========== ПОДТВЕРЖДЕНИЕ ОПЛАТЫ КАРТОЙ ==========
@dp.callback_query(F.data.startswith("confirm_paid_"))
async def confirm_card_payment(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("confirm_paid_", ""))
    order = db.get_order(order_id)
    
    if not order:
        await callback.answer("❌ Заказ не найден")
        return
    
    user_id, order_type, recipient, details, amount_rub, payment_method, status, invoice_id, created_at = order
    
    # Добавляем ожидание фото
    user_states[callback.from_user.id] = {
        "action": "waiting_payment_photo",
        "order_id": order_id
    }
    
    await callback.message.edit_text(
        f"📸 **Пришлите фото/скриншот оплаты**\n\n"
        f"🆔 Заказ: #{order_id}\n"
        f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
        "Пожалуйста, отправьте скриншот перевода.\n"
        "После отправки фото заказ будет передан админу на проверку.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data=f"cancel_photo_{order_id}")]
        ])
    )
    
    await callback.answer()

# Отмена отправки фото
@dp.callback_query(F.data.startswith("cancel_photo_"))
async def cancel_photo_handler(callback: types.CallbackQuery):
    order_id = int(callback.data.replace("cancel_photo_", ""))
    
    if callback.from_user.id in user_states:
        del user_states[callback.from_user.id]
    
    await card_payment_handler(callback)

# ========== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ ==========
@dp.message(F.text)
async def handle_text_messages(message: types.Message):
    if message.text.startswith('/'):
        return
    
    user_id = message.from_user.id
    
    if user_id in user_states and user_states[user_id].get("action") == "waiting_payment_photo":
        await message.answer("📸 Пожалуйста, отправьте фото/скриншот оплаты")
        return
    
    text = message.text.strip()
    
    if user_id not in user_states:
        await message.answer("Используйте меню", reply_markup=main_menu_kb())
        return
    
    state = user_states[user_id]
    action = state.get("action")
    
    if action == "waiting_stars_recipient":
        recipient = text.strip()
        
        if recipient.startswith('@'):
            recipient = recipient[1:]
            
        if not recipient:
            await message.answer("❌ Введите username получателя (можно с @)")
            return
        
        state["recipient"] = recipient
        state["action"] = "waiting_stars_amount"
        
        await message.answer(
            f"✅ Получатель: @{recipient}\n\n"
            "Теперь введите количество звезд (от 50 до 1,000,000):",
            reply_markup=back_kb("buy_stars")
        )
    
    elif action == "waiting_stars_amount":
        try:
            stars = int(text)
            if stars < 50 or stars > 1000000:
                await message.answer("❌ Количество звезд должно быть от 50 до 1,000,000")
                return
            
            amount_rub = stars * STAR_RATE
            recipient = state.get("recipient", "")
            
            state["stars_amount"] = stars
            state["amount_rub"] = amount_rub
            
            # Создаем заказ
            order_id = db.add_order(
                user_id, "stars", recipient, 
                json.dumps({"stars": stars}), 
                amount_rub, "card"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перевод на карту", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_stars")]
            ])
            
            if cryptobot:
                keyboard.inline_keyboard.insert(0, [
                    InlineKeyboardButton(text="💎 CryptoBot", callback_data=f"crypto_pay_{order_id}")
                ])
            
            await message.answer(
                f"✅ {stars} звезд для @{recipient}\n"
                f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
                "Выберите способ оплаты:",
                reply_markup=keyboard
            )
            
        except ValueError:
            await message.answer("❌ Пожалуйста, введите число")
    
    elif action == "waiting_premium_recipient":
        recipient = text.strip()
        
        if recipient.startswith('@'):
            recipient = recipient[1:]
            
        period = state.get("period")
        amount_rub = state.get("amount_rub")
        
        if period and amount_rub:
            state["recipient"] = recipient
            
            order_id = db.add_order(
                user_id, "premium", recipient,
                json.dumps({"period": period}),
                amount_rub, "card"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Перевод на карту", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="buy_premium")]
            ])
            
            if cryptobot:
                keyboard.inline_keyboard.insert(0, [
                    InlineKeyboardButton(text="💎 CryptoBot", callback_data=f"crypto_pay_{order_id}")
                ])
            
            await message.answer(
                f"✅ {PREMIUM_PRICES[period]['name']} для @{recipient}\n"
                f"💰 Сумма: {amount_rub:.2f} RUB\n\n"
                "Выберите способ оплаты:",
                reply_markup=keyboard
            )
    
    elif action == "waiting_exchange_amount":
        try:
            amount_rub = float(text)
            if amount_rub < 100:
                await message.answer("❌ Минимальная сумма: 100 RUB")
                return
            
            amount_usd = amount_rub / USD_RATE
            
            order_id = db.add_order(
                user_id, "exchange", "",
                json.dumps({
                    "amount_rub": amount_rub, 
                    "amount_usd": amount_usd,
                    "exchange_rate": USD_RATE
                }),
                amount_rub, "card"
            )
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Оплатить картой", callback_data=f"card_pay_{order_id}")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="exchange")]
            ])
            
            await message.answer(
                f"✅ **Обмен валют**\n"
                f"📊 Курс: 1 USD = {USD_RATE} RUB\n"
                f"💸 Вы получаете: {amount_usd:.2f} USD\n"
                f"💰 К оплате: {amount_rub:.2f} RUB\n\n"
                "💳 **Оплата только картой!**\n"
                "После оплаты пришлите скриншот перевода.",
                reply_markup=keyboard
            )
            
        except ValueError:
            await message.answer("❌ Пожалуйста, введите число")

# ========== ЗАПУСК БОТА ==========
async def main():
    print("=" * 50)
    print("🚀 Digi Store Bot запускается...")
    print("=" * 50)
    
    if not BOT_TOKEN:
        print("❌ ОШИБКА: BOT_TOKEN не найден!")
        print("ℹ️  Установите переменную окружения BOT_TOKEN")
        exit(1)
    
    print(f"🤖 Бот: ✅ Настроен")
    print(f"👑 Админ ID: {ADMIN_IDS}")
    print(f"💎 CryptoBot: {'✅ Настроен' if CRYPTOBOT_TOKEN else '❌ Нет токена'}")
    print(f"💳 Карта: {CARD_NUMBER}")
    print("=" * 50)
    print("✅ Админ панель упрощена:")
    print("👉 /admin - админ панель (2 кнопки)")
    print("👉 📦 Активные заказы - просмотр ВСЕХ заказов с фото")
    print("👉 📊 Статистика - простая статистика")
    print("=" * 50)
    print("📸 Админ видит фото оплаты при управлении заказом!")
    print("=" * 50)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())