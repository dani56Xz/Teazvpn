import os
import logging
import asyncio
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from fastapi import FastAPI, Request, HTTPException
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, 
    InlineKeyboardButton, BotCommand, Bot
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, CallbackContext
)
import json

# ========== تنظیمات اولیه ==========
TOKEN = os.getenv("BOT_TOKEN", "7084280622:AAGlwBy4FmMM3mc4OjjLQqa00Cg4t3jJzNg")
CHANNEL_USERNAME = "@teazvpn"
ADMIN_ID = 5542927340
TRON_ADDRESS = "TJ4xrwKzKjk6FgKfuuqwah3Az5Ur22kJb"
BANK_CARD = "6037 9975 9717 2684"

# تنظیمات Railway
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_STATIC_URL", os.getenv("RAILWAY_PUBLIC_DOMAIN"))
PORT = int(os.getenv("PORT", 8080))
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"https://{RAILWAY_PUBLIC_DOMAIN}{WEBHOOK_PATH}" if RAILWAY_PUBLIC_DOMAIN else None

# ========== تنظیمات لاگینگ ==========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ========== FastAPI App ==========
app = FastAPI(title="Teaz VPN Bot", version="3.0")

# ========== Health Endpoints ==========
@app.get("/")
async def root():
    return {
        "status": "running",
        "service": "Teaz VPN Telegram Bot",
        "platform": "Railway",
        "timestamp": datetime.now().isoformat(),
        "webhook": WEBHOOK_URL is not None
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "bot": "running",
        "database": "memory",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/stats")
async def stats():
    """آمار سرویس"""
    return {
        "users": len(memory_storage["users"]),
        "payments": len(memory_storage["payments"]),
        "subscriptions": len(memory_storage["subscriptions"]),
        "coupons": len(memory_storage["coupons"]),
        "configs": len(memory_storage["free_configs"]),
        "timestamp": datetime.now().isoformat()
    }

# ========== Telegram Application ==========
application = Application.builder().token(TOKEN).build()

# ========== ذخیره‌سازی در حافظه ==========
class MemoryStorage:
    """ذخیره‌سازی داده‌ها در حافظه"""
    def __init__(self):
        self.data = {
            "users": {},  # {user_id: user_data}
            "payments": {},  # {payment_id: payment_data}
            "subscriptions": {},  # {subscription_id: subscription_data}
            "coupons": {},  # {code: coupon_data}
            "free_configs": {},  # {config_id: config_data}
            "config_feedback": [],  # لیست بازخوردها
            "user_downloads": {},  # {(user_id, config_id): download_data}
            "counters": {
                "payment_id": 1,
                "subscription_id": 1,
                "config_id": 1,
                "feedback_id": 1
            }
        }
    
    def get_next_id(self, counter_name: str) -> int:
        """دریافت ID بعدی"""
        current = self.data["counters"][counter_name]
        self.data["counters"][counter_name] += 1
        return current

# ایجاد نمونه ذخیره‌سازی
memory_storage = MemoryStorage()

# ========== توابع دیتابیس حافظه ==========
async def db_execute(query: str, params: tuple = (), fetch: bool = False, 
                    fetchone: bool = False, returning: bool = False) -> Any:
    """اجرای کوئری روی دیتابیس حافظه"""
    try:
        query_lower = query.strip().lower()
        
        # SELECT queries
        if query_lower.startswith("select"):
            # SELECT FROM users WHERE user_id = ?
            if "from users where user_id" in query_lower:
                user_id = params[0]
                user = memory_storage.data["users"].get(user_id)
                if fetchone:
                    return (user,) if user else None
                elif fetch:
                    return [user] if user else []
            
            # SELECT FROM users
            elif "from users" in query_lower:
                if fetch:
                    return list(memory_storage.data["users"].values())
                return []
            
            # SELECT FROM payments
            elif "from payments" in query_lower:
                if fetch:
                    return list(memory_storage.data["payments"].values())
                return []
            
            # SELECT FROM subscriptions
            elif "from subscriptions" in query_lower:
                if fetch:
                    return list(memory_storage.data["subscriptions"].values())
                return []
            
            # SELECT FROM coupons WHERE code = ?
            elif "from coupons where code" in query_lower:
                code = params[0]
                coupon = memory_storage.data["coupons"].get(code)
                if fetchone:
                    if coupon:
                        return (coupon["discount_percent"], coupon.get("user_id"), 
                                coupon["is_used"], coupon["expiry_date"])
                    return None
            
            # SELECT COUNT(*) FROM ...
            elif "select count(*)" in query_lower:
                if "from users" in query_lower:
                    return [(len(memory_storage.data["users"]),)]
                elif "from payments" in query_lower:
                    return [(len(memory_storage.data["payments"]),)]
                elif "from subscriptions" in query_lower:
                    return [(len(memory_storage.data["subscriptions"]),)]
                elif "from coupons" in query_lower:
                    return [(len(memory_storage.data["coupons"]),)]
            
            # SELECT SUM(amount) FROM payments WHERE status = 'approved'
            elif "select sum(amount)" in query_lower:
                if "from payments where status = 'approved'" in query_lower:
                    total = sum(p["amount"] for p in memory_storage.data["payments"].values() 
                               if p["status"] == "approved")
                    return [(total or 0,)]
        
        # INSERT queries
        elif query_lower.startswith("insert"):
            # INSERT INTO users
            if "into users" in query_lower:
                user_id = params[0]
                username = params[1]
                invited_by = params[2] if len(params) > 2 else None
                
                memory_storage.data["users"][user_id] = {
                    "user_id": user_id,
                    "username": username,
                    "balance": 0,
                    "invited_by": invited_by,
                    "phone": None,
                    "created_at": datetime.now(),
                    "is_agent": False,
                    "is_new_user": True
                }
                
                if returning:
                    return user_id
            
            # INSERT INTO payments
            elif "into payments" in query_lower:
                payment_id = memory_storage.get_next_id("payment_id")
                
                memory_storage.data["payments"][payment_id] = {
                    "id": payment_id,
                    "user_id": params[0],
                    "amount": params[1],
                    "status": "pending",
                    "type": params[2],
                    "payment_method": params[3],
                    "description": params[4] if len(params) > 4 else "",
                    "created_at": datetime.now()
                }
                
                if returning:
                    return payment_id
            
            # INSERT INTO subscriptions
            elif "into subscriptions" in query_lower:
                subscription_id = memory_storage.get_next_id("subscription_id")
                
                memory_storage.data["subscriptions"][subscription_id] = {
                    "id": subscription_id,
                    "user_id": params[0],
                    "payment_id": params[1],
                    "plan": params[2],
                    "config": None,
                    "status": "pending",
                    "start_date": datetime.now(),
                    "duration_days": params[3] if len(params) > 3 else 30
                }
                
                if returning:
                    return subscription_id
            
            # INSERT INTO coupons
            elif "into coupons" in query_lower:
                code = params[0]
                memory_storage.data["coupons"][code] = {
                    "code": code,
                    "discount_percent": params[1],
                    "user_id": params[2] if len(params) > 2 else None,
                    "is_used": False,
                    "created_at": datetime.now(),
                    "expiry_date": datetime.now() + timedelta(days=3)
                }
            
            # INSERT INTO free_configs
            elif "into free_configs" in query_lower:
                config_id = memory_storage.get_next_id("config_id")
                
                memory_storage.data["free_configs"][config_id] = {
                    "id": config_id,
                    "file_id": params[0],
                    "file_name": params[1],
                    "file_size": params[2],
                    "mime_type": params[3],
                    "uploaded_by": params[4],
                    "uploaded_at": datetime.now(),
                    "is_approved": False,
                    "approved_by": None,
                    "approved_at": None,
                    "download_count": 0,
                    "successful_count": 0,
                    "unsuccessful_count": 0
                }
                
                if returning:
                    return config_id
            
            # INSERT INTO config_feedback
            elif "into config_feedback" in query_lower:
                feedback_id = memory_storage.get_next_id("feedback_id")
                
                feedback = {
                    "id": feedback_id,
                    "config_id": params[0],
                    "user_id": params[1],
                    "worked": params[2],
                    "operator": params[3] if len(params) > 3 else None,
                    "feedback_at": datetime.now()
                }
                
                memory_storage.data["config_feedback"].append(feedback)
                
                # بروزرسانی آمار کانفیگ
                config_id = params[0]
                if config_id in memory_storage.data["free_configs"]:
                    config = memory_storage.data["free_configs"][config_id]
                    if params[2]:  # worked = True
                        config["successful_count"] += 1
                    else:
                        config["unsuccessful_count"] += 1
            
            # INSERT INTO user_downloads
            elif "into user_downloads" in query_lower:
                user_id = params[0]
                config_id = params[1]
                key = (user_id, config_id)
                
                memory_storage.data["user_downloads"][key] = {
                    "user_id": user_id,
                    "config_id": config_id,
                    "downloaded_at": datetime.now()
                }
                
                # افزایش تعداد دانلود
                if config_id in memory_storage.data["free_configs"]:
                    memory_storage.data["free_configs"][config_id]["download_count"] += 1
        
        # UPDATE queries
        elif query_lower.startswith("update"):
            # UPDATE users SET balance = COALESCE(balance, 0) + ?
            if "users set balance = coalesce(balance, 0) +" in query_lower:
                user_id = params[1]
                amount = params[0]
                if user_id in memory_storage.data["users"]:
                    memory_storage.data["users"][user_id]["balance"] += amount
            
            # UPDATE users SET balance = COALESCE(balance, 0) - ?
            elif "users set balance = coalesce(balance, 0) -" in query_lower:
                user_id = params[1]
                amount = params[0]
                if user_id in memory_storage.data["users"]:
                    memory_storage.data["users"][user_id]["balance"] = max(
                        0, memory_storage.data["users"][user_id]["balance"] - amount
                    )
            
            # UPDATE users SET is_agent = TRUE
            elif "users set is_agent = true" in query_lower:
                user_id = params[0]
                if user_id in memory_storage.data["users"]:
                    memory_storage.data["users"][user_id]["is_agent"] = True
            
            # UPDATE users SET is_new_user = FALSE
            elif "users set is_new_user = false" in query_lower:
                user_id = params[0]
                if user_id in memory_storage.data["users"]:
                    memory_storage.data["users"][user_id]["is_new_user"] = False
            
            # UPDATE payments SET status = ?
            elif "payments set status =" in query_lower:
                payment_id = params[1]
                status = params[0]
                if payment_id in memory_storage.data["payments"]:
                    memory_storage.data["payments"][payment_id]["status"] = status
            
            # UPDATE subscriptions SET config = ?, status = 'active'
            elif "subscriptions set config =" in query_lower:
                config = params[0]
                payment_id = params[1]
                
                for sub in memory_storage.data["subscriptions"].values():
                    if sub["payment_id"] == payment_id:
                        sub["config"] = config
                        sub["status"] = "active"
                        break
            
            # UPDATE subscriptions SET status = ?
            elif "subscriptions set status =" in query_lower:
                subscription_id = params[1]
                status = params[0]
                if subscription_id in memory_storage.data["subscriptions"]:
                    memory_storage.data["subscriptions"][subscription_id]["status"] = status
            
            # UPDATE free_configs SET is_approved = TRUE
            elif "free_configs set is_approved = true" in query_lower:
                approved_by = params[0]
                config_id = params[1]
                if config_id in memory_storage.data["free_configs"]:
                    config = memory_storage.data["free_configs"][config_id]
                    config["is_approved"] = True
                    config["approved_by"] = approved_by
                    config["approved_at"] = datetime.now()
            
            # UPDATE coupons SET is_used = TRUE
            elif "coupons set is_used = true" in query_lower:
                code = params[0]
                if code in memory_storage.data["coupons"]:
                    memory_storage.data["coupons"][code]["is_used"] = True
        
        # DELETE queries
        elif query_lower.startswith("delete"):
            # DELETE FROM free_configs WHERE id = ?
            if "from free_configs where id =" in query_lower:
                config_id = params[0]
                if config_id in memory_storage.data["free_configs"]:
                    del memory_storage.data["free_configs"][config_id]
            
            # DELETE FROM users WHERE user_id = ?
            elif "from users where user_id =" in query_lower:
                user_id = params[0]
                if user_id in memory_storage.data["users"]:
                    del memory_storage.data["users"][user_id]
        
        return None
        
    except Exception as e:
        logger.error(f"Database error: {e}")
        raise

# ========== توابع کمکی ==========
def generate_coupon_code(length: int = 8) -> str:
    """تولید کد تخفیف تصادفی"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

async def send_long_message(chat_id: int, text: str, context: ContextTypes.DEFAULT_TYPE, 
                          reply_markup=None, parse_mode=None):
    """ارسال پیام‌های طولانی"""
    max_length = 4000
    if len(text) <= max_length:
        await context.bot.send_message(
            chat_id=chat_id, text=text, 
            reply_markup=reply_markup, parse_mode=parse_mode
        )
        return
    
    parts = []
    while text:
        if len(text) > max_length:
            split_pos = text.rfind('\n', 0, max_length)
            if split_pos == -1:
                split_pos = max_length
            parts.append(text[:split_pos])
            text = text[split_pos:].lstrip()
        else:
            parts.append(text)
            text = ""
    
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            await context.bot.send_message(
                chat_id=chat_id, text=part,
                reply_markup=reply_markup, parse_mode=parse_mode
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text=part)

# ========== کیبوردها ==========
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد اصلی"""
    keyboard = [
        [KeyboardButton("🇮🇷 کانفیگ های رایگان مردم")],
        [KeyboardButton("💰 موجودی"), KeyboardButton("💳 خرید اشتراک")],
        [KeyboardButton("🎁 اشتراک تست رایگان"), KeyboardButton("☎️ پشتیبانی")],
        [KeyboardButton("💵 اعتبار رایگان"), KeyboardButton("📂 اشتراک‌های من")],
        [KeyboardButton("💡 راهنمای اتصال"), KeyboardButton("🧑‍💼 درخواست نمایندگی")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_free_configs_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد بخش کانفیگ رایگان"""
    keyboard = [
        [KeyboardButton("📥 دریافت کانفیگ")],
        [KeyboardButton("📤 ارسال کانفیگ")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_operator_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد انتخاب اپراتور"""
    keyboard = [
        [KeyboardButton("همراه اول"), KeyboardButton("ایرانسل")],
        [KeyboardButton("رایتل"), KeyboardButton("مخابرات")],
        [KeyboardButton("شاتل"), KeyboardButton("سامانتل")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_feedback_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد بازخورد کانفیگ"""
    keyboard = [
        [KeyboardButton("کار کرد✅"), KeyboardButton("کار نکرد❌")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_balance_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد بخش موجودی"""
    keyboard = [
        [KeyboardButton("نمایش موجودی"), KeyboardButton("افزایش موجودی")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_subscription_keyboard(is_agent: bool = False) -> ReplyKeyboardMarkup:
    """کیبورد انتخاب پلن اشتراک"""
    if is_agent:
        keyboard = [
            [KeyboardButton("🥉۱ ماهه | ۷۰,۰۰۰ تومان | نامحدود | ۲ کاربره")],
            [KeyboardButton("🥈۳ ماهه | ۲۱۰,۰۰۰ تومان | نامحدود | ۲ کاربره")],
            [KeyboardButton("🥇۶ ماهه | ۳۸۰,۰۰۰ تومان | نامحدود | ۲ کاربره")],
            [KeyboardButton("⬅️ بازگشت به منو")]
        ]
    else:
        keyboard = [
            [KeyboardButton("🥉۱ ماهه | ۹۰ هزار تومان | نامحدود | ۲ کاربره")],
            [KeyboardButton("🥈۳ ماهه | ۲۵۰ هزار تومان | نامحدود | ۲ کاربره")],
            [KeyboardButton("🥇۶ ماهه | ۴۵۰ هزار تومان | نامحدود | ۲ کاربره")],
            [KeyboardButton("⬅️ بازگشت به منو")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_payment_method_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد روش پرداخت"""
    keyboard = [
        [KeyboardButton("🏦 کارت به کارت")],
        [KeyboardButton("💎 پرداخت با ترون")],
        [KeyboardButton("💰 پرداخت با موجودی")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد بازگشت"""
    return ReplyKeyboardMarkup([[KeyboardButton("⬅️ بازگشت به منو")]], resize_keyboard=True)

def get_connection_guide_keyboard() -> ReplyKeyboardMarkup:
    """کیبورد راهنمای اتصال"""
    keyboard = [
        [KeyboardButton("📗 اندروید")],
        [KeyboardButton("📕 آیفون/مک")],
        [KeyboardButton("📘 ویندوز")],
        [KeyboardButton("📙 لینوکس")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== توابع دیتابیس ==========
async def is_user_member(user_id: int) -> bool:
    """بررسی عضویت کاربر در کانال"""
    try:
        member = await application.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Error checking membership for {user_id}: {e}")
        return True  # برای تست، همیشه True برمی‌گرداند

async def ensure_user(user_id: int, username: str, invited_by: int = None) -> bool:
    """ثبت یا به‌روزرسانی کاربر"""
    try:
        user = await db_execute(
            "SELECT user_id FROM users WHERE user_id = %s",
            (user_id,), fetchone=True
        )
        
        if not user:
            # کاربر جدید
            await db_execute(
                "INSERT INTO users (user_id, username, invited_by) VALUES (%s, %s, %s)",
                (user_id, username, invited_by)
            )
            logger.info(f"New user registered: {user_id}")
            
            # اعتبار برای دعوت‌کننده
            if invited_by and invited_by != user_id:
                await add_balance(invited_by, 10000)
        
        return True
    except Exception as e:
        logger.error(f"Error ensuring user {user_id}: {e}")
        return False

async def is_user_agent(user_id: int) -> bool:
    """بررسی نماینده بودن کاربر"""
    try:
        result = await db_execute(
            "SELECT is_agent FROM users WHERE user_id = %s",
            (user_id,), fetchone=True
        )
        return result[0] if result else False
    except Exception as e:
        logger.error(f"Error checking agent status for {user_id}: {e}")
        return False

async def set_user_agent(user_id: int) -> bool:
    """تنظیم کاربر به عنوان نماینده"""
    try:
        await db_execute(
            "UPDATE users SET is_agent = TRUE WHERE user_id = %s",
            (user_id,)
        )
        logger.info(f"User {user_id} set as agent")
        return True
    except Exception as e:
        logger.error(f"Error setting user {user_id} as agent: {e}")
        return False

async def get_balance(user_id: int) -> int:
    """دریافت موجودی کاربر"""
    try:
        result = await db_execute(
            "SELECT balance FROM users WHERE user_id = %s",
            (user_id,), fetchone=True
        )
        return result[0] if result else 0
    except Exception as e:
        logger.error(f"Error getting balance for {user_id}: {e}")
        return 0

async def add_balance(user_id: int, amount: int) -> bool:
    """افزایش موجودی کاربر"""
    try:
        await db_execute(
            "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE user_id = %s",
            (amount, user_id)
        )
        logger.info(f"Added {amount} to user {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error adding balance to user {user_id}: {e}")
        return False

async def deduct_balance(user_id: int, amount: int) -> bool:
    """کاهش موجودی کاربر"""
    try:
        current_balance = await get_balance(user_id)
        if current_balance >= amount:
            await db_execute(
                "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE user_id = %s",
                (amount, user_id)
            )
            logger.info(f"Deducted {amount} from user {user_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error deducting balance from user {user_id}: {e}")
        return False

async def add_payment(user_id: int, amount: int, ptype: str, 
                     payment_method: str, description: str = "", 
                     coupon_code: str = None) -> Optional[int]:
    """ثبت پرداخت جدید"""
    try:
        result = await db_execute(
            "INSERT INTO payments (user_id, amount, type, payment_method, description) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, amount, ptype, payment_method, description),
            returning=True
        )
        
        if coupon_code:
            await mark_coupon_used(coupon_code)
        
        logger.info(f"Payment added: ID {result}, user {user_id}, amount {amount}")
        return result
    except Exception as e:
        logger.error(f"Error adding payment for user {user_id}: {e}")
        return None

async def add_subscription(user_id: int, payment_id: int, plan: str) -> bool:
    """ثبت اشتراک جدید"""
    try:
        duration_mapping = {
            "🥉۱ ماهه | ۹۰ هزار تومان | نامحدود | ۲ کاربره": 30,
            "🥈۳ ماهه | ۲۵۰ هزار تومان | نامحدود | ۲ کاربره": 90,
            "🥇۶ ماهه | ۴۵۰ هزار تومان | نامحدود | ۲ کاربره": 180,
            "🥉۱ ماهه | ۷۰,۰۰۰ تومان | نامحدود | ۲ کاربره": 30,
            "🥈۳ ماهه | ۲۱۰,۰۰۰ تومان | نامحدود | ۲ کاربره": 90,
            "🥇۶ ماهه | ۳۸۰,۰۰۰ تومان | نامحدود | ۲ کاربره": 180
        }
        
        duration_days = duration_mapping.get(plan, 30)
        
        await db_execute(
            "INSERT INTO subscriptions (user_id, payment_id, plan, start_date, duration_days) VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s)",
            (user_id, payment_id, plan, duration_days)
        )
        logger.info(f"Subscription added for user {user_id}, plan {plan}")
        return True
    except Exception as e:
        logger.error(f"Error adding subscription for user {user_id}: {e}")
        return False

async def update_subscription_config(payment_id: int, config: str) -> bool:
    """بروزرسانی کانفیگ اشتراک"""
    try:
        await db_execute(
            "UPDATE subscriptions SET config = %s, status = 'active' WHERE payment_id = %s",
            (config, payment_id)
        )
        logger.info(f"Config updated for payment {payment_id}")
        return True
    except Exception as e:
        logger.error(f"Error updating subscription config for payment {payment_id}: {e}")
        return False

async def update_payment_status(payment_id: int, status: str) -> bool:
    """بروزرسانی وضعیت پرداخت"""
    try:
        await db_execute(
            "UPDATE payments SET status = %s WHERE id = %s",
            (status, payment_id)
        )
        logger.info(f"Payment {payment_id} status updated to {status}")
        return True
    except Exception as e:
        logger.error(f"Error updating payment status for {payment_id}: {e}")
        return False

async def get_user_subscriptions(user_id: int) -> List[Dict]:
    """دریافت اشتراک‌های کاربر"""
    try:
        subscriptions = await db_execute(
            "SELECT id, plan, config, status, payment_id, start_date, duration_days FROM subscriptions WHERE user_id = %s",
            (user_id,), fetch=True
        )
        
        result = []
        current_time = datetime.now()
        
        for sub in subscriptions:
            sub_id, plan, config, status, payment_id, start_date, duration_days = sub
            
            if status == "active" and start_date:
                end_date = start_date + timedelta(days=duration_days)
                if current_time > end_date:
                    await db_execute(
                        "UPDATE subscriptions SET status = 'inactive' WHERE id = %s",
                        (sub_id,)
                    )
                    status = "inactive"
            
            result.append({
                'id': sub_id,
                'plan': plan,
                'config': config,
                'status': status,
                'payment_id': payment_id,
                'start_date': start_date,
                'duration_days': duration_days,
                'end_date': start_date + timedelta(days=duration_days) if start_date else None
            })
        
        return result
    except Exception as e:
        logger.error(f"Error getting subscriptions for user {user_id}: {e}")
        return []

async def create_coupon(code: str, discount_percent: int, user_id: int = None) -> bool:
    """ایجاد کد تخفیف"""
    try:
        await db_execute(
            "INSERT INTO coupons (code, discount_percent, user_id) VALUES (%s, %s, %s)",
            (code, discount_percent, user_id)
        )
        logger.info(f"Coupon created: {code} ({discount_percent}%)")
        return True
    except Exception as e:
        logger.error(f"Error creating coupon {code}: {e}")
        return False

async def validate_coupon(code: str, user_id: int) -> Tuple[Optional[int], Optional[str]]:
    """اعتبارسنجی کد تخفیف"""
    try:
        result = await db_execute(
            "SELECT discount_percent, user_id, is_used, expiry_date FROM coupons WHERE code = %s",
            (code,), fetchone=True
        )
        
        if not result:
            return None, "کد تخفیف نامعتبر است."
        
        discount_percent, coupon_user_id, is_used, expiry_date = result
        
        if is_used:
            return None, "این کد تخفیف قبلاً استفاده شده است."
        
        if datetime.now() > expiry_date:
            return None, "این کد تخفیف منقضی شده است."
        
        if coupon_user_id is not None and coupon_user_id != user_id:
            return None, "این کد تخفیف برای شما نیست."
        
        if await is_user_agent(user_id):
            return None, "نمایندگان نمی‌توانند از کد تخفیف استفاده کنند."
        
        return discount_percent, None
    except Exception as e:
        logger.error(f"Error validating coupon {code}: {e}")
        return None, "خطا در بررسی کد تخفیف."

async def mark_coupon_used(code: str) -> bool:
    """علامت‌گذاری کد تخفیف به عنوان استفاده‌شده"""
    try:
        await db_execute(
            "UPDATE coupons SET is_used = TRUE WHERE code = %s",
            (code,)
        )
        logger.info(f"Coupon {code} marked as used")
        return True
    except Exception as e:
        logger.error(f"Error marking coupon {code} as used: {e}")
        return False

# ========== توابع کانفیگ رایگان ==========
async def save_free_config(file_id: str, file_name: str, file_size: int, 
                          mime_type: str, uploaded_by: int) -> Optional[int]:
    """ذخیره کانفیگ رایگان"""
    try:
        config_id = await db_execute(
            "INSERT INTO free_configs (file_id, file_name, file_size, mime_type, uploaded_by) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (file_id, file_name, file_size, mime_type, uploaded_by),
            returning=True
        )
        logger.info(f"Free config saved: ID {config_id}")
        return config_id
    except Exception as e:
        logger.error(f"Error saving free config: {e}")
        return None

async def approve_free_config(config_id: int, approved_by: int) -> bool:
    """تایید کانفیگ رایگان"""
    try:
        await db_execute(
            "UPDATE free_configs SET is_approved = TRUE, approved_by = %s, approved_at = CURRENT_TIMESTAMP WHERE id = %s",
            (approved_by, config_id)
        )
        logger.info(f"Free config {config_id} approved by {approved_by}")
        return True
    except Exception as e:
        logger.error(f"Error approving free config {config_id}: {e}")
        return False

async def reject_free_config(config_id: int) -> bool:
    """رد کانفیگ رایگان"""
    try:
        await db_execute(
            "DELETE FROM free_configs WHERE id = %s",
            (config_id,)
        )
        logger.info(f"Free config {config_id} rejected")
        return True
    except Exception as e:
        logger.error(f"Error rejecting free config {config_id}: {e}")
        return False

async def get_random_approved_config(user_id: int) -> Optional[Dict]:
    """دریافت کانفیگ رایگان تصادفی"""
    try:
        # دریافت همه کانفیگ‌های تایید شده
        configs = await db_execute(
            "SELECT id, file_id, file_name, download_count, successful_count, unsuccessful_count FROM free_configs WHERE is_approved = TRUE",
            fetch=True
        )
        
        if not configs:
            return None
        
        # حذف کانفیگ‌هایی که کاربر قبلاً دانلود کرده
        user_downloads = [
            key for key in memory_storage.data["user_downloads"].keys() 
            if key[0] == user_id
        ]
        downloaded_config_ids = [config_id for _, config_id in user_downloads]
        
        available_configs = [
            config for config in configs 
            if config[0] not in downloaded_config_ids
        ]
        
        if not available_configs:
            return None
        
        # انتخاب تصادفی
        config = random.choice(available_configs)
        
        # ثبت دانلود
        await db_execute(
            "INSERT INTO user_downloads (user_id, config_id) VALUES (%s, %s)",
            (user_id, config[0])
        )
        
        return {
            'id': config[0],
            'file_id': config[1],
            'file_name': config[2],
            'download_count': config[3],
            'successful_count': config[4],
            'unsuccessful_count': config[5]
        }
    except Exception as e:
        logger.error(f"Error getting random config for user {user_id}: {e}")
        return None

async def save_config_feedback(config_id: int, user_id: int, worked: bool, 
                              operator: str = None) -> bool:
    """ذخیره بازخورد کانفیگ"""
    try:
        await db_execute(
            "INSERT INTO config_feedback (config_id, user_id, worked, operator) VALUES (%s, %s, %s, %s)",
            (config_id, user_id, worked, operator)
        )
        logger.info(f"Feedback saved for config {config_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving feedback for config {config_id}: {e}")
        return False

# ========== دستورات مدیریت ==========
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش آمار ربات (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    try:
        # آمار کاربران
        total_users = await db_execute(
            "SELECT COUNT(*) FROM users", fetchone=True
        )
        total_users = total_users[0] if total_users else 0
        
        agents = await db_execute(
            "SELECT COUNT(*) FROM users WHERE is_agent = TRUE", fetchone=True
        )
        agents = agents[0] if agents else 0
        
        # آمار درآمد
        total_income = await db_execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'approved'", 
            fetchone=True
        )
        total_income = total_income[0] if total_income else 0
        
        # آمار اشتراک‌ها
        total_subs = await db_execute(
            "SELECT COUNT(*) FROM subscriptions", fetchone=True
        )
        total_subs = total_subs[0] if total_subs else 0
        
        active_subs = await db_execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'", 
            fetchone=True
        )
        active_subs = active_subs[0] if active_subs else 0
        
        # آمار کانفیگ‌های رایگان
        total_configs = await db_execute(
            "SELECT COUNT(*) FROM free_configs WHERE is_approved = TRUE", 
            fetchone=True
        )
        total_configs = total_configs[0] if total_configs else 0
        
        stats_text = f"""
📊 **آمار ربات تیز VPN**

👥 **کاربران:**
├ کل کاربران: {total_users:,} نفر
├ نمایندگان: {agents:,} نفر
└ کاربران عادی: {total_users - agents:,} نفر

💰 **درآمد:**
└ کل درآمد: {total_income:,} تومان

📦 **اشتراک‌ها:**
├ کل اشتراک‌ها: {total_subs:,} عدد
├ اشتراک‌های فعال: {active_subs:,} عدد
└ نرخ فعال: {(active_subs/total_subs*100 if total_subs > 0 else 0):.1f}%

🇮🇷 **کانفیگ رایگان:**
└ کانفیگ‌های تایید شده: {total_configs:,} عدد

🔄 **آخرین به‌روزرسانی:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """
        
        await update.message.reply_text(stats_text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error generating stats: {e}")
        await update.message.reply_text("⚠️ خطا در نمایش آمار.")

async def clear_db_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاک کردن دیتابیس (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    try:
        # ریست کردن دیتابیس حافظه
        memory_storage.data = {
            "users": {},
            "payments": {},
            "subscriptions": {},
            "coupons": {},
            "free_configs": {},
            "config_feedback": [],
            "user_downloads": {},
            "counters": {
                "payment_id": 1,
                "subscription_id": 1,
                "config_id": 1,
                "feedback_id": 1
            }
        }
        
        await update.message.reply_text("✅ دیتابیس با موفقیت پاک شد.")
    except Exception as e:
        logger.error(f"Error clearing database: {e}")
        await update.message.reply_text(f"⚠️ خطا در پاک کردن دیتابیس: {str(e)}")

# ========== هندلر شروع ==========
user_states = {}  # وضعیت کاربران

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور شروع ربات"""
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    
    # بررسی عضویت در کانال
    if not await is_user_member(user_id):
        keyboard = [[InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")]]
        await update.message.reply_text(
            "❌ برای استفاده از ربات، ابتدا در کانال ما عضو شوید و سپس مجدد /start را بزنید.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # ثبت کاربر
    invited_by = context.user_data.get("invited_by")
    await ensure_user(user_id, username, invited_by)
    
    welcome_text = f"""
🌐 **به فروشگاه تیز VPN خوش آمدید، {user.first_name}!** 🌐

💎 **ویژگی‌های سرویس ما:**
✅ اتصال پرسرعت و پایدار
✅ بدون محدودیت حجمی
✅ پشتیبانی ۲۴ ساعته
✅ مناسب برای تمامی دستگاه‌ها

🎯 **گزینه مورد نظر خود را انتخاب کنید:**
    """
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    
    # پاک کردن وضعیت کاربر
    if user_id in user_states:
        del user_states[user_id]

async def start_with_param(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع با پارامتر (برای دعوت)"""
    args = context.args
    if args and len(args) > 0:
        try:
            invited_by = int(args[0])
            if invited_by != update.effective_user.id:
                context.user_data["invited_by"] = invited_by
        except:
            context.user_data["invited_by"] = None
    
    await start(update, context)

# ========== هندلر اصلی پیام‌ها ==========
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر اصلی پیام‌ها"""
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else ""
    
    logger.info(f"User {user_id}: '{text}' (state: {user_states.get(user_id)})")
    
    # بازگشت به منو
    if text in ["بازگشت به منو", "⬅️ بازگشت به منو"]:
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard())
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # پردازش بر اساس وضعیت کاربر
    state = user_states.get(user_id)
    
    # ---------- بخش کانفیگ رایگان ----------
    if text == "🇮🇷 کانفیگ های رایگان مردم":
        await update.message.reply_text(
            "🇮🇷 **بخش کانفیگ‌های رایگان مردمی**\n\n"
            "در این بخش می‌توانید:\n"
            "✅ کانفیگ‌های رایگان کاربران را دریافت کنید\n"
            "✅ کانفیگ متصل خود را برای دیگران ارسال کنید\n\n"
            "لطفا یک گزینه انتخاب کنید:",
            reply_markup=get_free_configs_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif text == "📥 دریافت کانفیگ":
        config = await get_random_approved_config(user_id)
        
        if not config:
            await update.message.reply_text(
                "⚠️ **در حال حاضر کانفیگ رایگان جدیدی موجود نیست!**\n\n"
                "ممکن است:\n"
                "• همه کانفیگ‌ها را دریافت کرده‌اید\n"
                "• هنوز کانفیگی توسط کاربران ارسال نشده\n"
                "• کانفیگ‌های ارسالی در انتظار تایید هستند\n\n"
                "می‌توانید کانفیگ خود را برای ما ارسال کنید تا دیگران استفاده کنند.",
                reply_markup=get_free_configs_keyboard(),
                parse_mode="Markdown"
            )
            return
        
        try:
            # ارسال کانفیگ
            await context.bot.send_document(
                chat_id=user_id,
                document=config['file_id'],
                caption=f"""
📁 **کانفیگ رایگان مردمی**

📊 **آمار این کانفیگ:**
├ 📥 دانلود شده: {config['download_count'] + 1} بار
├ ✅ موفق: {config['successful_count']} بار
├ ❌ ناموفق: {config['unsuccessful_count']} بار
└ 📈 نرخ موفقیت: {(config['successful_count']/(config['successful_count']+config['unsuccessful_count'])*100 if (config['successful_count']+config['unsuccessful_count']) > 0 else 0):.1f}%

⚠️ **توجه:** این کانفیگ توسط کاربران ارسال شده و تیم تیز VPN مسئولیتی ندارد.

❓ **آیا این کانفیگ کار کرد؟**
                """,
                reply_markup=get_feedback_keyboard(),
                parse_mode="Markdown"
            )
            
            # ذخیره ID کانفیگ برای بازخورد
            context.user_data['current_config_id'] = config['id']
            user_states[user_id] = "awaiting_config_feedback"
            
        except Exception as e:
            logger.error(f"Error sending config: {e}")
            await update.message.reply_text(
                "⚠️ خطا در ارسال کانفیگ. لطفا دوباره تلاش کنید.",
                reply_markup=get_free_configs_keyboard()
            )
        return
    
    elif text == "📤 ارسال کانفیگ":
        await update.message.reply_text(
            "📤 **ارسال کانفیگ رایگان**\n\n"
            "لطفا فایل کانفیگ متصل خود را ارسال کنید.\n\n"
            "⚠️ **توجه:**\n"
            "• فقط فایل‌های کانفیگ قبول می‌شود\n"
            "• کانفیگ شما توسط ادمین بررسی می‌شود\n"
            "• پس از تایید، برای دیگر کاربران قابل دانلود خواهد بود",
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown"
        )
        user_states[user_id] = "awaiting_config_file"
        return
    
    elif state == "awaiting_config_file":
        if update.message.document:
            try:
                file = update.message.document
                file_id = file.file_id
                file_name = file.file_name or "config.v2ray"
                file_size = file.file_size or 0
                mime_type = file.mime_type or "application/octet-stream"
                
                # ذخیره کانفیگ
                config_id = await save_free_config(file_id, file_name, file_size, mime_type, user_id)
                
                if config_id:
                    await update.message.reply_text(
                        "✅ فایل شما ثبت شد و برای بررسی به ادمین ارسال شد.",
                        reply_markup=get_free_configs_keyboard()
                    )
                    
                    # اطلاع به ادمین
                    caption = f"""
📤 **کانفیگ جدید ارسال شد**

👤 **ارسال کننده:** {user_id} (@{update.effective_user.username or 'بدون یوزرنیم'})
📁 **نام فایل:** {file_name}
📊 **حجم:** {file_size:,} بایت
🆔 **کد کانفیگ:** #{config_id}

برای بررسی و تایید:
                    """
                    
                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ تایید", callback_data=f"approve_config_{config_id}"),
                            InlineKeyboardButton("❌ رد", callback_data=f"reject_config_{config_id}")
                        ]
                    ])
                    
                    await context.bot.send_document(
                        chat_id=ADMIN_ID,
                        document=file_id,
                        caption=caption,
                        parse_mode="Markdown",
                        reply_markup=keyboard
                    )
                else:
                    await update.message.reply_text(
                        "⚠️ خطا در ثبت فایل. لطفا دوباره تلاش کنید.",
                        reply_markup=get_free_configs_keyboard()
                    )
                    
            except Exception as e:
                logger.error(f"Error processing config file: {e}")
                await update.message.reply_text(
                    "⚠️ خطا در پردازش فایل. لطفا دوباره تلاش کنید.",
                    reply_markup=get_free_configs_keyboard()
                )
        else:
            await update.message.reply_text(
                "⚠️ لطفا فایل کانفیگ را به صورت فایل ارسال کنید.",
                reply_markup=get_back_keyboard()
            )
        
        if user_id in user_states:
            del user_states[user_id]
        return
    
    elif state == "awaiting_config_feedback":
        if text == "کار کرد✅":
            user_states[user_id] = "awaiting_operator_selection"
            await update.message.reply_text(
                "✅ **عالیه!**\n\n"
                "با کدام اپراتور وصل شدید؟",
                reply_markup=get_operator_keyboard()
            )
            return
        elif text == "کار نکرد❌":
            config_id = context.user_data.get('current_config_id')
            if config_id:
                await save_config_feedback(config_id, user_id, False)
                del context.user_data['current_config_id']
            
            await update.message.reply_text(
                "❌ بازخورد شما ثبت شد.\n\n"
                "متاسفیم که کانفیگ برای شما کار نکرد. می‌توانید کانفیگ دیگری دریافت کنید.",
                reply_markup=get_free_configs_keyboard()
            )
            
            if user_id in user_states:
                del user_states[user_id]
            return
        else:
            await update.message.reply_text(
                "⚠️ لطفا یکی از گزینه‌های بالا را انتخاب کنید.",
                reply_markup=get_feedback_keyboard()
            )
            return
    
    elif state == "awaiting_operator_selection":
        valid_operators = ["همراه اول", "ایرانسل", "رایتل", "مخابرات", "شاتل", "سامانتل"]
        
        if text in valid_operators:
            config_id = context.user_data.get('current_config_id')
            if config_id:
                await save_config_feedback(config_id, user_id, True, text)
                del context.user_data['current_config_id']
            
            await update.message.reply_text(
                f"✅ **با تشکر!**\n\n"
                f"بازخورد شما برای اپراتور **{text}** ثبت شد.",
                reply_markup=get_free_configs_keyboard()
            )
            
            if user_id in user_states:
                del user_states[user_id]
            return
        else:
            await update.message.reply_text(
                "⚠️ لطفا یکی از اپراتورهای بالا را انتخاب کنید.",
                reply_markup=get_operator_keyboard()
            )
            return
    
    # ---------- بخش موجودی ----------
    elif text == "💰 موجودی":
        balance = await get_balance(user_id)
        await update.message.reply_text(
            f"💰 **موجودی حساب شما:**\n\n"
            f"💎 **{balance:,} تومان**\n\n"
            "برای افزایش موجودی از گزینه «افزایش موجودی» استفاده کنید.",
            reply_markup=get_balance_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif text == "نمایش موجودی":
        balance = await get_balance(user_id)
        await update.message.reply_text(f"💰 موجودی شما: {balance:,} تومان", reply_markup=get_balance_keyboard())
        return
    
    elif text == "افزایش موجودی":
        await update.message.reply_text(
            "💳 **افزایش موجودی**\n\n"
            "لطفا مبلغ مورد نظر را به تومان وارد کنید (مثال: 100000):",
            reply_markup=get_back_keyboard(),
            parse_mode="Markdown"
        )
        user_states[user_id] = "awaiting_deposit_amount"
        return
    
    elif state == "awaiting_deposit_amount":
        if text.isdigit():
            amount = int(text)
            if amount < 10000:
                await update.message.reply_text(
                    "⚠️ مبلغ باید حداقل ۱۰,۰۰۰ تومان باشد.",
                    reply_markup=get_back_keyboard()
                )
                return
            
            payment_id = await add_payment(user_id, amount, "increase_balance", "card_to_card")
            
            if payment_id:
                await update.message.reply_text(
                    f"💳 **درخواست افزایش موجودی**\n\n"
                    f"💰 **مبلغ:** {amount:,} تومان\n"
                    f"🆔 **کد تراکنش:** #{payment_id}\n\n"
                    f"**لطفا مبلغ را واریز کنید:**\n\n"
                    f"🏦 **کارت به کارت:**\n`{BANK_CARD}`\n"
                    f"✍️ **به نام:** فرهنگ\n\n"
                    f"⚠️ **توجه:** پس از واریز، فیش پرداخت را ارسال کنید.",
                    reply_markup=get_back_keyboard(),
                    parse_mode="Markdown"
                )
                user_states[user_id] = f"awaiting_deposit_receipt_{payment_id}"
            else:
                await update.message.reply_text(
                    "⚠️ خطا در ثبت درخواست. لطفا دوباره تلاش کنید.",
                    reply_markup=get_main_keyboard()
                )
                if user_id in user_states:
                    del user_states[user_id]
        else:
            await update.message.reply_text(
                "⚠️ لطفا یک عدد معتبر وارد کنید.",
                reply_markup=get_back_keyboard()
            )
        return
    
    # ---------- پردازش فیش پرداخت ----------
    elif state and state.startswith("awaiting_deposit_receipt_"):
        payment_id = int(state.split("_")[-1])
        
        # ارسال فیش به ادمین
        caption = f"""
💳 **فیش واریزی جدید**

👤 **کاربر:** {user_id} (@{update.effective_user.username or 'بدون یوزرنیم'})
🆔 **کد تراکنش:** #{payment_id}
⏰ **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

برای بررسی:
        """
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تایید", callback_data=f"approve_{payment_id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{payment_id}")
            ]
        ])
        
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        elif update.message.document:
            file_id = update.message.document.file_id
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "⚠️ لطفا فیش پرداخت را به صورت عکس یا فایل ارسال کنید.",
                reply_markup=get_back_keyboard()
            )
            return
        
        await update.message.reply_text(
            "✅ فیش پرداخت شما برای ادمین ارسال شد.\n"
            "لطفا منتظر تایید باشید (حداکثر ۲۴ ساعت).",
            reply_markup=get_main_keyboard()
        )
        
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # ---------- بخش خرید اشتراک ----------
    elif text == "💳 خرید اشتراک":
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text(
            "🎯 **انتخاب پلن اشتراک**\n\n"
            "لطفا پلن مورد نظر خود را انتخاب کنید:",
            reply_markup=get_subscription_keyboard(is_agent),
            parse_mode="Markdown"
        )
        return
    
    elif text in [
        "🥉۱ ماهه | ۹۰ هزار تومان | نامحدود | ۲ کاربره",
        "🥈۳ ماهه | ۲۵۰ هزار تومان | نامحدود | ۲ کاربره", 
        "🥇۶ ماهه | ۴۵۰ هزار تومان | نامحدود | ۲ کاربره"
    ]:
        price_mapping = {
            "🥉۱ ماهه | ۹۰ هزار تومان | نامحدود | ۲ کاربره": 90000,
            "🥈۳ ماهه | ۲۵۰ هزار تومان | نامحدود | ۲ کاربره": 250000,
            "🥇۶ ماهه | ۴۵۰ هزار تومان | نامحدود | ۲ کاربره": 450000
        }
        
        amount = price_mapping.get(text, 0)
        user_states[user_id] = f"awaiting_payment_method_{amount}_{text}"
        
        await update.message.reply_text(
            f"💎 **پلن انتخاب شده:** {text}\n💰 **قیمت:** {amount:,} تومان\n\n💳 **روش پرداخت را انتخاب کنید:**",
            reply_markup=get_payment_method_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif state and state.startswith("awaiting_payment_method_"):
        parts = state.split("_")
        amount = int(parts[3])
        plan = "_".join(parts[4:])
        
        if text == "🏦 کارت به کارت":
            payment_id = await add_payment(user_id, amount, "buy_subscription", "card_to_card", description=plan)
            
            if payment_id:
                await add_subscription(user_id, payment_id, plan)
                
                await update.message.reply_text(
                    f"💳 **درخواست خرید اشتراک**\n\n"
                    f"🎯 **پلن:** {plan}\n"
                    f"💰 **مبلغ:** {amount:,} تومان\n"
                    f"🆔 **کد خرید:** #{payment_id}\n\n"
                    f"**لطفا مبلغ را واریز کنید:**\n\n"
                    f"🏦 **کارت به کارت:**\n`{BANK_CARD}`\n"
                    f"✍️ **به نام:** فرهنگ\n\n"
                    f"⚠️ **توجه:** پس از واریز، فیش پرداخت را ارسال کنید.",
                    reply_markup=get_back_keyboard(),
                    parse_mode="Markdown"
                )
                user_states[user_id] = f"awaiting_subscription_receipt_{payment_id}"
            else:
                await update.message.reply_text(
                    "⚠️ خطا در ثبت درخواست.",
                    reply_markup=get_main_keyboard()
                )
                if user_id in user_states:
                    del user_states[user_id]
            return
        
        elif text == "💎 پرداخت با ترون":
            payment_id = await add_payment(user_id, amount, "buy_subscription", "tron", description=plan)
            
            if payment_id:
                await add_subscription(user_id, payment_id, plan)
                
                await update.message.reply_text(
                    f"💎 **درخواست خرید اشتراک**\n\n"
                    f"🎯 **پلن:** {plan}\n"
                    f"💰 **مبلغ:** {amount:,} تومان\n"
                    f"🆔 **کد خرید:** #{payment_id}\n\n"
                    f"**لطفا مبلغ را واریز کنید:**\n\n"
                    f"💎 **آدرس ترون:**\n`{TRON_ADDRESS}`\n\n"
                    f"⚠️ **توجه:** پس از واریز، فیش پرداخت را ارسال کنید.",
                    reply_markup=get_back_keyboard(),
                    parse_mode="Markdown"
                )
                user_states[user_id] = f"awaiting_subscription_receipt_{payment_id}"
            else:
                await update.message.reply_text(
                    "⚠️ خطا در ثبت درخواست.",
                    reply_markup=get_main_keyboard()
                )
                if user_id in user_states:
                    del user_states[user_id]
            return
        
        elif text == "💰 پرداخت با موجودی":
            balance = await get_balance(user_id)
            
            if balance >= amount:
                payment_id = await add_payment(user_id, amount, "buy_subscription", "balance", description=plan)
                
                if payment_id:
                    await add_subscription(user_id, payment_id, plan)
                    await deduct_balance(user_id, amount)
                    await update_payment_status(payment_id, "approved")
                    
                    await update.message.reply_text(
                        f"✅ **خرید شما موفقیت‌آمیز بود!**\n\n"
                        f"🎯 **پلن:** {plan}\n"
                        f"💰 **مبلغ پرداختی:** {amount:,} تومان\n"
                        f"🆔 **کد خرید:** #{payment_id}\n\n"
                        f"اشتراک شما فعال شد.",
                        reply_markup=get_main_keyboard(),
                        parse_mode="Markdown"
                    )
                    
                    # اطلاع به ادمین
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"""
🛒 **خرید با موجودی**

👤 **کاربر:** {user_id} (@{update.effective_user.username or 'بدون یوزرنیم'})
🎯 **پلن:** {plan}
💰 **مبلغ:** {amount:,} تومان
🆔 **کد خرید:** #{payment_id}
                        """,
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(
                        "⚠️ خطا در ثبت خرید.",
                        reply_markup=get_main_keyboard()
                    )
            else:
                await update.message.reply_text(
                    f"⚠️ **موجودی کافی نیست!**\n\n"
                    f"💰 **موجودی شما:** {balance:,} تومان\n"
                    f"💰 **مبلغ مورد نیاز:** {amount:,} تومان\n"
                    f"💰 **کمبود:** {amount - balance:,} تومان\n\n"
                    f"لطفا ابتدا موجودی خود را افزایش دهید.",
                    reply_markup=get_main_keyboard(),
                    parse_mode="Markdown"
                )
            
            if user_id in user_states:
                del user_states[user_id]
            return
    
    elif state and state.startswith("awaiting_subscription_receipt_"):
        payment_id = int(state.split("_")[-1])
        
        # ارسال فیش به ادمین
        caption = f"""
💳 **فیش پرداخت اشتراک**

👤 **کاربر:** {user_id} (@{update.effective_user.username or 'بدون یوزرنیم'})
🆔 **کد خرید:** #{payment_id}
⏰ **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

برای بررسی:
        """
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تایید", callback_data=f"approve_{payment_id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{payment_id}")
            ]
        ])
        
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        elif update.message.document:
            file_id = update.message.document.file_id
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=file_id,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "⚠️ لطفا فیش پرداخت را ارسال کنید.",
                reply_markup=get_back_keyboard()
            )
            return
        
        await update.message.reply_text(
            "✅ فیش پرداخت شما برای ادمین ارسال شد.\n"
            "پس از تایید، اشتراک برای شما فعال خواهد شد.",
            reply_markup=get_main_keyboard()
        )
        
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # ---------- سایر بخش‌ها ----------
    elif text == "🎁 اشتراک تست رایگان":
        await update.message.reply_text(
            "🎁 **اشتراک تست رایگان**\n\n"
            "برای دریافت اشتراک تست رایگان، لطفا با پشتیبانی تماس بگیرید:\n"
            "👨‍💼 @teazadmin",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif text == "☎️ پشتیبانی":
        await update.message.reply_text(
            "📞 **پشتیبانی**\n\n"
            "👨‍💼 **ادمین:** @teazadmin\n"
            "⏰ **۲۴ ساعته**\n\n"
            "✅ پاسخگویی سریع",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif text == "💵 اعتبار رایگان":
        invite_link = f"https://t.me/teazvpn_bot?start={user_id}"
        await update.message.reply_text(
            f"💎 **کسب اعتبار رایگان**\n\n"
            f"🔗 **لینک دعوت شما:**\n`{invite_link}`\n\n"
            f"📊 **سیستم پاداش:**\n"
            f"• هر دعوت موفق: **۱۰,۰۰۰ تومان**\n"
            f"• دعوت شده باید اشتراک بخرد\n"
            f"• اعتبار بلافاصله واریز می‌شود\n\n"
            f"🎯 **لینک خود را برای دوستان بفرستید!**",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif text == "📂 اشتراک‌های من":
        subscriptions = await get_user_subscriptions(user_id)
        
        if not subscriptions:
            await update.message.reply_text(
                "📭 **شما هیچ اشتراک فعالی ندارید.**\n\n"
                "برای خرید اشتراک از منوی اصلی استفاده کنید.",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown"
            )
            return
        
        response = "📋 **لیست اشتراک‌های شما:**\n\n"
        current_time = datetime.now()
        
        for sub in subscriptions:
            response += f"🔸 **#{sub['id']}**\n"
            response += f"🎯 **پلن:** {sub['plan']}\n"
            response += f"🆔 **کد خرید:** #{sub['payment_id']}\n"
            response += f"📊 **وضعیت:** {'✅ فعال' if sub['status'] == 'active' else '⏳ در انتظار'}\n"
            
            if sub['status'] == 'active' and sub['start_date']:
                end_date = sub['start_date'] + timedelta(days=sub['duration_days'])
                remaining = (end_date - current_time).days
                response += f"⏳ **زمان باقی‌مانده:** {remaining} روز\n"
                response += f"📅 **تاریخ انقضا:** {end_date.strftime('%Y-%m-%d')}\n"
            
            if sub['config']:
                response += f"🔑 **کانفیگ:**\n`{sub['config']}`\n"
            
            response += "━━━━━━━━━━\n\n"
        
        await send_long_message(
            user_id, response, context,
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif text == "💡 راهنمای اتصال":
        await update.message.reply_text(
            "📚 **راهنمای اتصال**\n\n"
            "لطفا دستگاه خود را انتخاب کنید:",
            reply_markup=get_connection_guide_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif text in ["📗 اندروید", "📕 آیفون/مک", "📘 ویندوز", "📙 لینوکس"]:
        guides = {
            "📗 اندروید": """
📱 **راهنمای اندروید**

✅ **برنامه پیشنهادی:** V2RayNG یا Hiddify

📥 **نحوه استفاده:**
1. برنامه را از فروشگاه دانلود کنید
2. کانفیگ را کپی کنید
3. در برنامه Import کنید
4. Connect را بزنید

🚀 **پشتیبانی از تمام اپراتورها**
            """,
            "📕 آیفون/مک": """
🍎 **راهنمای آیفون/مک**

✅ **برنامه پیشنهادی:** Singbox یا Streisand

📥 **نحوه استفاده:**
1. از App Store برنامه را نصب کنید
2. کانفیگ را اضافه کنید
3. فعال کنید
4. لذت ببرید!

🔒 **امن و پایدار**
            """,
            "📘 ویندوز": """
💻 **راهنمای ویندوز**

✅ **برنامه پیشنهادی:** V2rayN

📥 **نحوه استفاده:**
1. برنامه را دانلود کنید
2. کانفیگ را وارد کنید
3. سرویس را Start کنید
4. مرورگر را باز کنید

⚡ **سرعت بالا**
            """,
            "📙 لینوکس": """
🐧 **راهنمای لینوکس**

✅ **برنامه پیشنهادی:** V2rayA

📥 **نحوه استفاده:**
1. پکیج را نصب کنید
2. کانفیگ را تنظیم کنید
3. سرویس را راه‌اندازی کنید
4. از اینترنت استفاده کنید

🔧 **برای کاربران حرفه‌ای**
            """
        }
        
        await update.message.reply_text(
            guides[text],
            reply_markup=get_connection_guide_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif text == "🧑‍💼 درخواست نمایندگی":
        await update.message.reply_text(
            "🚀 **اعطای نمایندگی رسمی تیز VPN**\n\n"
            "💎 **مزایای نمایندگی:**\n"
            "✅ خرید با قیمت نماینده (۲۰-۳۰٪ تخفیف)\n"
            "✅ پنل اختصاصی مدیریت کاربران\n"
            "✅ تعیین قیمت دلخواه برای فروش\n"
            "✅ پشتیبانی ویژه\n"
            "✅ درآمدزایی دائمی\n\n"
            "💰 **هزینه نمایندگی: ۱,۰۰۰,۰۰۰ تومان**\n\n"
            "برای اطلاعات بیشتر با پشتیبانی تماس بگیرید:\n👨‍💼 @teazadmin",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # ---------- مدیریت کانفیگ توسط ادمین ----------
    elif user_id == ADMIN_ID and state and state.startswith("awaiting_config_"):
        payment_id = int(state.split("_")[-1])
        config_text = text
        
        # یافتن کاربر خریدار
        payment = await db_execute(
            "SELECT user_id, description FROM payments WHERE id = %s",
            (payment_id,), fetchone=True
        )
        
        if payment:
            buyer_id, plan = payment
            
            # بروزرسانی اشتراک
            await update_subscription_config(payment_id, config_text)
            
            # ارسال کانفیگ به کاربر
            await context.bot.send_message(
                chat_id=buyer_id,
                text=f"""
🎉 **اشتراک شما فعال شد!**

🎯 **پلن:** {plan}
🆔 **کد خرید:** #{payment_id}
🔗 **کانفیگ:**

`{config_text}`

💎 **راهنمای اتصال را از منوی اصلی مطالعه کنید.**

✅ **مشکلی داشتید با پشتیبانی تماس بگیرید.**
                """,
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            
            await update.message.reply_text(
                f"✅ کانفیگ برای کاربر {buyer_id} ارسال شد.",
                reply_markup=get_main_keyboard()
            )
            
            logger.info(f"Config sent for payment {payment_id}")
        else:
            await update.message.reply_text(
                "⚠️ پرداخت یافت نشد.",
                reply_markup=get_main_keyboard()
            )
        
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # ---------- اگر هیچکدام از شرایط بالا برقرار نبود ----------
    await update.message.reply_text(
        "⚠️ **دستور نامعتبر است!**\n\n"
        "لطفا از دکمه‌های کیبورد استفاده کنید.",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    
    if user_id in user_states:
        del user_states[user_id]

# ========== هندلر کال‌بک ==========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر کال‌بک‌های اینلاین"""
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    
    await query.answer()
    
    # فقط ادمین مجاز است
    if user_id != ADMIN_ID:
        await query.edit_message_text("⚠️ شما مجاز نیستید.")
        return
    
    try:
        # تأیید یا رد کانفیگ رایگان
        if data.startswith("approve_config_"):
            config_id = int(data.split("_")[-1])
            
            # تأیید کانفیگ
            success = await approve_free_config(config_id, ADMIN_ID)
            
            if success:
                # یافتن ارسال کننده
                config = memory_storage.data["free_configs"].get(config_id)
                
                if config:
                    uploaded_by = config["uploaded_by"]
                    
                    # اطلاع به ارسال کننده
                    try:
                        await context.bot.send_message(
                            chat_id=uploaded_by,
                            text=f"""
✅ **کانفیگ شما تایید شد!**

📁 **فایل:** {config['file_name']}
🎯 **وضعیت:** تایید شده
👥 **اکنون برای سایر کاربران قابل دانلود است.**

💎 **با تشکر از مشارکت شما!**
                            """,
                            parse_mode="Markdown"
                        )
                    except:
                        pass
                
                await query.edit_message_text(
                    f"✅ کانفیگ #{config_id} تایید شد.",
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    "⚠️ خطا در تایید کانفیگ.",
                    parse_mode="Markdown"
                )
            
            return
        
        elif data.startswith("reject_config_"):
            config_id = int(data.split("_")[-1])
            
            # یافتن ارسال کننده
            config = memory_storage.data["free_configs"].get(config_id)
            
            if config:
                uploaded_by = config["uploaded_by"]
                
                # اطلاع به ارسال کننده
                try:
                    await context.bot.send_message(
                        chat_id=uploaded_by,
                        text=f"""
❌ **کانفیگ شما رد شد!**

📁 **فایل:** {config['file_name']}
🎯 **وضعیت:** رد شده

⚠️ **دلایل احتمالی:**
• فایل معتبر نیست
• کانفیگ کار نمی‌کند
• مشکل در فرمت فایل

💎 **می‌توانید کانفیگ جدیدی ارسال کنید.**
                        """,
                        parse_mode="Markdown"
                    )
                except:
                    pass
            
            # حذف کانفیگ
            success = await reject_free_config(config_id)
            
            if success:
                await query.edit_message_text(
                    f"❌ کانفیگ #{config_id} رد و حذف شد.",
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    "⚠️ خطا در رد کانفیگ.",
                    parse_mode="Markdown"
                )
            
            return
        
        # تأیید یا رد پرداخت
        elif data.startswith("approve_"):
            payment_id = int(data.split("_")[-1])
            
            # دریافت اطلاعات پرداخت
            payment = memory_storage.data["payments"].get(payment_id)
            
            if payment:
                buyer_id = payment["user_id"]
                amount = payment["amount"]
                ptype = payment["type"]
                
                # بروزرسانی وضعیت پرداخت
                await update_payment_status(payment_id, "approved")
                
                if ptype == "increase_balance":
                    # افزایش موجودی
                    await add_balance(buyer_id, amount)
                    
                    # اطلاع به کاربر
                    await context.bot.send_message(
                        chat_id=buyer_id,
                        text=f"""
✅ **پرداخت شما تایید شد!**

💰 **مبلغ:** {amount:,} تومان
💎 **موجودی جدید:** {(await get_balance(buyer_id)):,} تومان

💳 **از افزایش موجودی شما متشکریم!**
                        """,
                        parse_mode="Markdown"
                    )
                    
                    await query.edit_message_text(
                        f"✅ پرداخت #{payment_id} تایید شد.\n"
                        f"💰 {amount:,} تومان به موجودی کاربر اضافه شد.",
                        parse_mode="Markdown"
                    )
                
                elif ptype == "buy_subscription":
                    # اطلاع به کاربر
                    await context.bot.send_message(
                        chat_id=buyer_id,
                        text=f"""
✅ **پرداخت شما تایید شد!**

🎯 **پلن:** {payment['description']}
💰 **مبلغ:** {amount:,} تومان
🆔 **کد خرید:** #{payment_id}

⏳ **لطفا منتظر ارسال کانفیگ باشید.**
                        """,
                        parse_mode="Markdown"
                    )
                    
                    # درخواست کانفیگ از ادمین
                    await query.edit_message_text(
                        f"✅ پرداخت #{payment_id} تایید شد.\n"
                        f"🎯 پلن: {payment['description']}\n"
                        f"💰 مبلغ: {amount:,} تومان\n\n"
                        f"📤 لطفا کانفیگ را ارسال کنید:",
                        parse_mode="Markdown"
                    )
                    
                    # تنظیم وضعیت برای دریافت کانفیگ
                    user_states[ADMIN_ID] = f"awaiting_config_{payment_id}"
                
            else:
                await query.edit_message_text("⚠️ پرداخت یافت نشد.")
            
            return
        
        elif data.startswith("reject_"):
            payment_id = int(data.split("_")[-1])
            
            # دریافت اطلاعات پرداخت
            payment = memory_storage.data["payments"].get(payment_id)
            
            if payment:
                buyer_id = payment["user_id"]
                amount = payment["amount"]
                
                # بروزرسانی وضعیت
                await update_payment_status(payment_id, "rejected")
                
                # اطلاع به کاربر
                await context.bot.send_message(
                    chat_id=buyer_id,
                    text=f"""
❌ **پرداخت شما رد شد!**

💰 **مبلغ:** {amount:,} تومان
🆔 **کد تراکنش:** #{payment_id}

⚠️ **دلایل احتمالی:**
• فیش نامعتبر است
• مبلغ نادرست است
• مشکل در پرداخت

💎 **در صورت نیاز با پشتیبانی تماس بگیرید.**
                    """,
                    parse_mode="Markdown"
                )
                
                await query.edit_message_text(
                    f"❌ پرداخت #{payment_id} رد شد.",
                    parse_mode="Markdown"
                )
                
                logger.info(f"Payment {payment_id} rejected by admin")
            else:
                await query.edit_message_text("⚠️ پرداخت یافت نشد.")
            
            return
        
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await query.edit_message_text(f"⚠️ خطا: {str(e)}")

# ========== ثبت هندلرها ==========
def setup_handlers():
    """تنظیم هندلرهای ربات"""
    # هندلر دستورات
    application.add_handler(CommandHandler("start", start_with_param))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cleardb", clear_db_command))
    
    # هندلر کال‌بک‌ها
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # هندلر پیام‌ها
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, message_handler))

# ========== وب‌هوک ==========
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """هندلر وب‌هوک تلگرام"""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        
        # پردازش آپدیت
        await application.process_update(update)
        
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}, 500

# ========== راه‌اندازی ==========
@app.on_event("startup")
async def startup():
    """رویداد راه‌اندازی برنامه"""
    try:
        logger.info("🚀 Starting Teaz VPN Bot...")
        
        # راه‌اندازی بات
        await application.initialize()
        await application.start()
        
        # تنظیم وب‌هوک برای Railway
        if WEBHOOK_URL:
            await application.bot.set_webhook(
                url=WEBHOOK_URL,
                allowed_updates=Update.ALL_TYPES
            )
            logger.info(f"✅ Webhook set: {WEBHOOK_URL}")
        else:
            logger.warning("⚠️ WEBHOOK_URL not set, using polling mode")
        
        # ثبت هندلرها
        setup_handlers()
        
        # اطلاع به ادمین
        try:
            await application.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"""
🤖 **ربات تیز VPN راه‌اندازی شد!**

✅ **پلتفرم:** Railway
⏰ **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🌐 **حالت:** Memory Database
🔧 **وضعیت:** آماده به کار

🟢 **ربات فعال است!**
                """,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")
        
        logger.info("✅ Bot started successfully!")
        
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")

@app.on_event("shutdown")
async def shutdown():
    """رویداد خاموش‌سازی برنامه"""
    try:
        logger.info("🛑 Shutting down bot...")
        
        # اطلاع به ادمین
        try:
            await application.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"""
⚠️ **ربات در حال خاموش شدن...**

⏰ **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔴 **به زودی آنلاین می‌شود**
                """,
                parse_mode="Markdown"
            )
        except:
            pass
        
        # متوقف کردن بات
        await application.stop()
        await application.shutdown()
        
        logger.info("✅ Bot shut down successfully")
        
    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}")

# ========== اجرای اصلی ==========
if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting server on port {PORT}")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info"
    )
