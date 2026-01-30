import os
import logging
import asyncio
import random
import string
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, 
    InlineKeyboardButton, BotCommand, Bot
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler, CallbackContext
)

# ---------- تنظیمات اولیه ----------
TOKEN = os.getenv("BOT_TOKEN", "7084280622:AAGlwBy4FmMM3mc4OjjLQqa00Cg4t3jJzNg")
CHANNEL_USERNAME = "@teazvpn"
ADMIN_ID = 5542927340
TRON_ADDRESS = "TJ4xrwKzKjk6FgKfuuqwah3Az5Ur22kJb"
BANK_CARD = "6037 9975 9717 2684"

# تنظیمات Railway
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_STATIC_URL")
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{RAILWAY_PUBLIC_DOMAIN}{WEBHOOK_PATH}" if RAILWAY_PUBLIC_DOMAIN else None

# تنظیمات لاگینگ
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
    ]
)

logger = logging.getLogger(__name__)

# ---------- FastAPI App ----------
app = FastAPI(title="Teaz VPN Bot", version="2.0")

# ---------- Health Endpoints ----------
@app.get("/")
async def root():
    return {
        "status": "running",
        "service": "Teaz VPN Telegram Bot",
        "platform": "Railway",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health():
    try:
        await db_execute("SELECT 1", fetchone=True)
        return {
            "status": "healthy",
            "database": "connected",
            "bot": "running",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.get("/ping")
async def ping():
    return {"pong": True, "timestamp": datetime.now().isoformat()}

# ---------- Telegram Application ----------
application = Application.builder().token(TOKEN).build()

# ---------- PostgreSQL Connection Pool ----------
import psycopg2
from psycopg2 import pool
import tempfile
import subprocess

# Railway به صورت خودکار DATABASE_URL را تنظیم می‌کند
DATABASE_URL = os.getenv("DATABASE_URL")

# برای سازگاری با Railway و Neon
if not DATABASE_URL:
    DATABASE_URL = os.getenv("POSTGRESQL_URL") or os.getenv("NEON_DATABASE_URL")

db_pool = None

def init_db_pool():
    """ایجاد connection pool برای دیتابیس"""
    global db_pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    
    try:
        logger.info("Initializing database connection pool...")
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=DATABASE_URL,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5
        )
        logger.info("✅ Database pool initialized successfully")
        
        # تست اتصال
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        db_version = cursor.fetchone()
        logger.info(f"Connected to PostgreSQL: {db_version[0]}")
        cursor.close()
        db_pool.putconn(conn)
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize database pool: {e}")
        raise

def close_db_pool():
    """بستن connection pool"""
    global db_pool
    if db_pool:
        db_pool.closeall()
        db_pool = None
        logger.info("Database pool closed")

def _db_execute_sync(query, params=(), fetch=False, fetchone=False, returning=False):
    """تابع همگام برای اجرای کوئری"""
    conn = None
    cursor = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute(query, params)
        
        result = None
        if returning:
            result = cursor.fetchone()[0] if cursor.rowcount > 0 else None
        elif fetchone:
            result = cursor.fetchone()
        elif fetch:
            result = cursor.fetchall()
        
        if not query.strip().lower().startswith("select"):
            conn.commit()
            
        return result
    except Exception as e:
        logger.error(f"Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            db_pool.putconn(conn)

async def db_execute(query, params=(), fetch=False, fetchone=False, returning=False):
    """تابع ناهمگام برای اجرای کوئری"""
    return await asyncio.to_thread(
        _db_execute_sync, query, params, fetch, fetchone, returning
    )

# ---------- ساخت جداول دیتابیس ----------
async def create_tables():
    """ساخت جداول مورد نیاز در دیتابیس"""
    try:
        # جدول کاربران
        await db_execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                balance BIGINT DEFAULT 0,
                invited_by BIGINT,
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_agent BOOLEAN DEFAULT FALSE,
                is_new_user BOOLEAN DEFAULT TRUE
            )
        """)
        
        # جدول پرداخت‌ها
        await db_execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount BIGINT,
                status TEXT,
                type TEXT,
                payment_method TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # جدول اشتراک‌ها
        await db_execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                payment_id INTEGER,
                plan TEXT,
                config TEXT,
                status TEXT DEFAULT 'pending',
                start_date TIMESTAMP,
                duration_days INTEGER
            )
        """)
        
        # جدول کدهای تخفیف
        await db_execute("""
            CREATE TABLE IF NOT EXISTS coupons (
                code TEXT PRIMARY KEY,
                discount_percent INTEGER,
                user_id BIGINT,
                is_used BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expiry_date TIMESTAMP GENERATED ALWAYS AS (created_at + INTERVAL '3 days') STORED
            )
        """)
        
        # جدول کانفیگ‌های رایگان
        await db_execute("""
            CREATE TABLE IF NOT EXISTS free_configs (
                id SERIAL PRIMARY KEY,
                file_id TEXT NOT NULL,
                file_name TEXT,
                file_size INTEGER,
                mime_type TEXT,
                uploaded_by BIGINT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_approved BOOLEAN DEFAULT FALSE,
                approved_by BIGINT,
                approved_at TIMESTAMP,
                download_count INTEGER DEFAULT 0,
                successful_count INTEGER DEFAULT 0,
                unsuccessful_count INTEGER DEFAULT 0,
                mci_success INTEGER DEFAULT 0,
                mtn_success INTEGER DEFAULT 0,
                rightel_success INTEGER DEFAULT 0,
                mokhaberat_success INTEGER DEFAULT 0,
                shatel_success INTEGER DEFAULT 0,
                samantel_success INTEGER DEFAULT 0
            )
        """)
        
        # جدول بازخورد کانفیگ‌ها
        await db_execute("""
            CREATE TABLE IF NOT EXISTS config_feedback (
                id SERIAL PRIMARY KEY,
                config_id INTEGER REFERENCES free_configs(id),
                user_id BIGINT,
                worked BOOLEAN,
                operator TEXT,
                feedback_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # جدول دانلودهای کاربران
        await db_execute("""
            CREATE TABLE IF NOT EXISTS user_downloads (
                user_id BIGINT,
                config_id INTEGER REFERENCES free_configs(id),
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, config_id)
            )
        """)
        
        logger.info("✅ All database tables created successfully")
        
    except Exception as e:
        logger.error(f"❌ Error creating tables: {e}")
        raise

# ---------- توابع کمکی ----------
def generate_coupon_code(length=8):
    """تولید کد تخفیف تصادفی"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

async def send_long_message(chat_id, text, context, reply_markup=None, parse_mode=None):
    """ارسال پیام‌های طولانی"""
    max_length = 4000
    if len(text) <= max_length:
        await context.bot.send_message(
            chat_id=chat_id, 
            text=text, 
            reply_markup=reply_markup, 
            parse_mode=parse_mode
        )
        return
    
    parts = []
    while len(text) > 0:
        if len(text) > max_length:
            part = text[:max_length]
            text = text[max_length:]
        else:
            part = text
            text = ""
        parts.append(part)
    
    for i, part in enumerate(parts):
        if i == len(parts) - 1:
            await context.bot.send_message(
                chat_id=chat_id,
                text=part,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        else:
            await context.bot.send_message(chat_id=chat_id, text=part)

# ---------- کیبوردها ----------
def get_main_keyboard():
    """کیبورد اصلی"""
    keyboard = [
        [KeyboardButton("🇮🇷 کانفیگ های رایگان مردم")],
        [KeyboardButton("💰 موجودی"), KeyboardButton("💳 خرید اشتراک")],
        [KeyboardButton("🎁 اشتراک تست رایگان"), KeyboardButton("☎️ پشتیبانی")],
        [KeyboardButton("💵 اعتبار رایگان"), KeyboardButton("📂 اشتراک‌های من")],
        [KeyboardButton("💡 راهنمای اتصال"), KeyboardButton("🧑‍💼 درخواست نمایندگی")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_free_configs_keyboard():
    """کیبورد بخش کانفیگ رایگان"""
    keyboard = [
        [KeyboardButton("📥 دریافت کانفیگ")],
        [KeyboardButton("📤 ارسال کانفیگ")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_operator_keyboard():
    """کیبورد انتخاب اپراتور"""
    keyboard = [
        [KeyboardButton("همراه اول"), KeyboardButton("ایرانسل")],
        [KeyboardButton("رایتل"), KeyboardButton("مخابرات")],
        [KeyboardButton("شاتل"), KeyboardButton("سامانتل")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_feedback_keyboard():
    """کیبورد بازخورد کانفیگ"""
    keyboard = [
        [KeyboardButton("کار کرد✅"), KeyboardButton("کار نکرد❌")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_balance_keyboard():
    """کیبورد بخش موجودی"""
    keyboard = [
        [KeyboardButton("نمایش موجودی"), KeyboardButton("افزایش موجودی")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_subscription_keyboard(is_agent=False):
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

def get_payment_method_keyboard():
    """کیبورد روش پرداخت"""
    keyboard = [
        [KeyboardButton("🏦 کارت به کارت")],
        [KeyboardButton("💎 پرداخت با ترون")],
        [KeyboardButton("💰 پرداخت با موجودی")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_keyboard():
    """کیبورد بازگشت"""
    return ReplyKeyboardMarkup([[KeyboardButton("⬅️ بازگشت به منو")]], resize_keyboard=True)

def get_connection_guide_keyboard():
    """کیبورد راهنمای اتصال"""
    keyboard = [
        [KeyboardButton("📗 اندروید")],
        [KeyboardButton("📕 آیفون/مک")],
        [KeyboardButton("📘 ویندوز")],
        [KeyboardButton("📙 لینوکس")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_coupon_recipient_keyboard():
    """کیبورد گیرنده کد تخفیف"""
    keyboard = [
        [KeyboardButton("📢 برای همه")],
        [KeyboardButton("👤 برای یک نفر")],
        [KeyboardButton("🎯 درصد خاصی از کاربران")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_notification_type_keyboard():
    """کیبورد نوع اطلاع‌رسانی"""
    keyboard = [
        [KeyboardButton("📢 پیام به همه کاربران")],
        [KeyboardButton("🧑‍💼 پیام به نمایندگان")],
        [KeyboardButton("👤 پیام به یک نفر")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------- توابع دیتابیس ----------
async def is_user_member(user_id):
    """بررسی عضویت کاربر در کانال"""
    try:
        member = await application.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Error checking membership for {user_id}: {e}")
        return False

async def ensure_user(user_id, username, invited_by=None):
    """ثبت یا به‌روزرسانی کاربر"""
    try:
        user = await db_execute(
            "SELECT user_id, is_new_user FROM users WHERE user_id = %s",
            (user_id,), fetchone=True
        )
        
        if not user:
            # کاربر جدید
            await db_execute(
                """INSERT INTO users (user_id, username, invited_by, is_agent, is_new_user) 
                   VALUES (%s, %s, %s, FALSE, TRUE)""",
                (user_id, username, invited_by)
            )
            logger.info(f"New user registered: {user_id}")
            
            # اعتبار برای دعوت‌کننده
            if invited_by and invited_by != user_id:
                await add_balance(invited_by, 10000)
                
        elif user[1]:  # کاربر قدیمی که new_user است
            await db_execute(
                "UPDATE users SET is_new_user = FALSE WHERE user_id = %s",
                (user_id,)
            )
            
        return True
    except Exception as e:
        logger.error(f"Error ensuring user {user_id}: {e}")
        return False

async def is_user_agent(user_id):
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

async def set_user_agent(user_id):
    """تنظیم کاربر به عنوان نماینده"""
    try:
        await db_execute(
            "UPDATE users SET is_agent = TRUE WHERE user_id = %s",
            (user_id,)
        )
        logger.info(f"User {user_id} set as agent")
    except Exception as e:
        logger.error(f"Error setting user as agent: {e}")

async def get_balance(user_id):
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

async def add_balance(user_id, amount):
    """افزایش موجودی کاربر"""
    try:
        await db_execute(
            "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE user_id = %s",
            (amount, user_id)
        )
        logger.info(f"Added {amount} to user {user_id}")
    except Exception as e:
        logger.error(f"Error adding balance: {e}")

async def deduct_balance(user_id, amount):
    """کاهش موجودی کاربر"""
    try:
        await db_execute(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE user_id = %s",
            (amount, user_id)
        )
        logger.info(f"Deducted {amount} from user {user_id}")
    except Exception as e:
        logger.error(f"Error deducting balance: {e}")

async def add_payment(user_id, amount, ptype, payment_method, description="", coupon_code=None):
    """ثبت پرداخت جدید"""
    try:
        result = await db_execute(
            """INSERT INTO payments (user_id, amount, status, type, payment_method, description) 
               VALUES (%s, %s, 'pending', %s, %s, %s) RETURNING id""",
            (user_id, amount, ptype, payment_method, description),
            returning=True
        )
        
        if coupon_code:
            await mark_coupon_used(coupon_code)
            
        logger.info(f"Payment added: ID {result}, user {user_id}, amount {amount}")
        return result
    except Exception as e:
        logger.error(f"Error adding payment: {e}")
        return None

async def add_subscription(user_id, payment_id, plan):
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
            """INSERT INTO subscriptions (user_id, payment_id, plan, status, start_date, duration_days) 
               VALUES (%s, %s, %s, 'pending', CURRENT_TIMESTAMP, %s)""",
            (user_id, payment_id, plan, duration_days)
        )
        logger.info(f"Subscription added: user {user_id}, plan {plan}")
    except Exception as e:
        logger.error(f"Error adding subscription: {e}")
        raise

async def update_subscription_config(payment_id, config):
    """بروزرسانی کانفیگ اشتراک"""
    try:
        await db_execute(
            "UPDATE subscriptions SET config = %s, status = 'active' WHERE payment_id = %s",
            (config, payment_id)
        )
        logger.info(f"Config updated for payment {payment_id}")
    except Exception as e:
        logger.error(f"Error updating subscription config: {e}")

async def update_payment_status(payment_id, status):
    """بروزرسانی وضعیت پرداخت"""
    try:
        await db_execute(
            "UPDATE payments SET status = %s WHERE id = %s",
            (status, payment_id)
        )
        logger.info(f"Payment {payment_id} status updated to {status}")
    except Exception as e:
        logger.error(f"Error updating payment status: {e}")

async def get_user_subscriptions(user_id):
    """دریافت اشتراک‌های کاربر"""
    try:
        subscriptions = await db_execute(
            """SELECT s.id, s.plan, s.config, s.status, s.payment_id, 
                      s.start_date, s.duration_days
               FROM subscriptions s
               WHERE s.user_id = %s
               ORDER BY s.status DESC, s.start_date DESC""",
            (user_id,), fetch=True
        )
        
        result = []
        current_time = datetime.now()
        
        for sub in subscriptions:
            sub_id, plan, config, status, payment_id, start_date, duration_days = sub
            
            if status == "active" and start_date:
                end_date = start_date + timedelta(days=duration_days or 30)
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
                'duration_days': duration_days
            })
        
        return result
    except Exception as e:
        logger.error(f"Error getting subscriptions for {user_id}: {e}")
        return []

async def create_coupon(code, discount_percent, user_id=None):
    """ایجاد کد تخفیف"""
    try:
        await db_execute(
            "INSERT INTO coupons (code, discount_percent, user_id, is_used) VALUES (%s, %s, %s, FALSE)",
            (code, discount_percent, user_id)
        )
        logger.info(f"Coupon created: {code} ({discount_percent}%)")
    except Exception as e:
        logger.error(f"Error creating coupon: {e}")
        raise

async def validate_coupon(code, user_id):
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
        logger.error(f"Error validating coupon: {e}")
        return None, "خطا در بررسی کد تخفیف."

async def mark_coupon_used(code):
    """علامت‌گذاری کد تخفیف به عنوان استفاده‌شده"""
    try:
        await db_execute("UPDATE coupons SET is_used = TRUE WHERE code = %s", (code,))
        logger.info(f"Coupon {code} marked as used")
    except Exception as e:
        logger.error(f"Error marking coupon as used: {e}")

# ---------- توابع کانفیگ رایگان ----------
async def save_free_config(file_id, file_name, file_size, mime_type, uploaded_by):
    """ذخیره کانفیگ رایگان"""
    try:
        config_id = await db_execute(
            """INSERT INTO free_configs (file_id, file_name, file_size, mime_type, uploaded_by) 
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (file_id, file_name, file_size, mime_type, uploaded_by),
            returning=True
        )
        logger.info(f"Free config saved: ID {config_id}")
        return config_id
    except Exception as e:
        logger.error(f"Error saving free config: {e}")
        return None

async def approve_free_config(config_id, approved_by):
    """تایید کانفیگ رایگان"""
    try:
        await db_execute(
            "UPDATE free_configs SET is_approved = TRUE, approved_by = %s, approved_at = CURRENT_TIMESTAMP WHERE id = %s",
            (approved_by, config_id)
        )
        logger.info(f"Free config {config_id} approved by {approved_by}")
        return True
    except Exception as e:
        logger.error(f"Error approving free config: {e}")
        return False

async def reject_free_config(config_id):
    """رد کانفیگ رایگان"""
    try:
        await db_execute("DELETE FROM free_configs WHERE id = %s", (config_id,))
        logger.info(f"Free config {config_id} rejected")
        return True
    except Exception as e:
        logger.error(f"Error rejecting free config: {e}")
        return False

async def get_random_approved_config(user_id):
    """دریافت کانفیگ رایگان تصادفی"""
    try:
        configs = await db_execute(
            """SELECT fc.id, fc.file_id, fc.file_name, fc.download_count, 
                      fc.successful_count, fc.unsuccessful_count
               FROM free_configs fc
               LEFT JOIN user_downloads ud ON fc.id = ud.config_id AND ud.user_id = %s
               WHERE fc.is_approved = TRUE AND ud.config_id IS NULL""",
            (user_id,), fetch=True
        )
        
        if not configs:
            return None
        
        config = random.choice(configs)
        
        # ثبت دانلود
        await db_execute(
            "INSERT INTO user_downloads (user_id, config_id) VALUES (%s, %s)",
            (user_id, config[0])
        )
        
        await db_execute(
            "UPDATE free_configs SET download_count = download_count + 1 WHERE id = %s",
            (config[0],)
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
        logger.error(f"Error getting random config: {e}")
        return None

async def save_config_feedback(config_id, user_id, worked, operator=None):
    """ذخیره بازخورد کانفیگ"""
    try:
        await db_execute(
            "INSERT INTO config_feedback (config_id, user_id, worked, operator) VALUES (%s, %s, %s, %s)",
            (config_id, user_id, worked, operator)
        )
        
        if worked:
            await db_execute(
                "UPDATE free_configs SET successful_count = successful_count + 1 WHERE id = %s",
                (config_id,)
            )
        else:
            await db_execute(
                "UPDATE free_configs SET unsuccessful_count = unsuccessful_count + 1 WHERE id = %s",
                (config_id,)
            )
        
        logger.info(f"Feedback saved for config {config_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving feedback: {e}")
        return False

# ---------- دستورات مدیریت ----------
async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """حذف کاربر (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    await update.message.reply_text("🆔 ایدی عددی کاربری که می‌خواهید حذف کنید را وارد کنید:")
    user_states[update.effective_user.id] = "awaiting_user_id_for_removal"

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تهیه بکاپ از دیتابیس (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    await update.message.reply_text("🔄 این قابلیت در Railway نیاز به تنظیمات اضافی دارد.")

async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازیابی دیتابیس (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    await update.message.reply_text("🔄 این قابلیت در Railway نیاز به تنظیمات اضافی دارد.")

async def notification_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال اطلاعیه (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    await update.message.reply_text(
        "📢 نوع اطلاع‌رسانی را انتخاب کنید:",
        reply_markup=get_notification_type_keyboard()
    )
    user_states[update.effective_user.id] = "awaiting_notification_type"

async def coupon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ایجاد کد تخفیف (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    await update.message.reply_text("💵 مقدار تخفیف را به درصد وارد کنید (مثال: 20):")
    user_states[update.effective_user.id] = "awaiting_coupon_discount"

async def user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش اطلاعات کاربران (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    try:
        users = await db_execute(
            "SELECT user_id, username, phone, balance, is_agent, created_at FROM users ORDER BY created_at DESC",
            fetch=True
        )
        
        if not users:
            await update.message.reply_text("📂 هیچ کاربری یافت نشد.")
            return
        
        response = "👥 لیست کاربران:\n\n"
        for user in users[:20]:  # فقط 20 کاربر اول
            user_id, username, phone, balance, is_agent, created_at = user
            username = f"@{username}" if username else "بدون یوزرنیم"
            agent_status = "نماینده" if is_agent else "ساده"
            created = created_at.strftime("%Y-%m-%d") if created_at else "نامشخص"
            
            response += f"🆔 {user_id}\n📛 {username}\n💰 {balance:,}\n👤 {agent_status}\n📅 {created}\n━━━━━━━━━━\n"
        
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Error in user_info_command: {e}")
        await update.message.reply_text("⚠️ خطا در نمایش اطلاعات کاربران.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش آمار ربات (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    try:
        # آمار کاربران
        total_users = await db_execute("SELECT COUNT(*) FROM users", fetchone=True)
        total_users = total_users[0] if total_users else 0
        
        active_users = await db_execute(
            "SELECT COUNT(DISTINCT user_id) FROM subscriptions WHERE status = 'active'",
            fetchone=True
        )
        active_users = active_users[0] if active_users else 0
        
        agents = await db_execute(
            "SELECT COUNT(*) FROM users WHERE is_agent = TRUE",
            fetchone=True
        )
        agents = agents[0] if agents else 0
        
        # آمار درآمد
        total_income = await db_execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'approved'",
            fetchone=True
        )
        total_income = total_income[0] if total_income else 0
        
        today_income = await db_execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE status = 'approved' AND created_at >= CURRENT_DATE",
            fetchone=True
        )
        today_income = today_income[0] if today_income else 0
        
        # آمار اشتراک‌ها
        total_subs = await db_execute("SELECT COUNT(*) FROM subscriptions", fetchone=True)
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
├ کاربران فعال: {active_users:,} نفر
├ نمایندگان: {agents:,} نفر
└ نرخ فعالیت: {(active_users/total_users*100 if total_users > 0 else 0):.1f}%

💰 **درآمد:**
├ کل درآمد: {total_income:,} تومان
├ درآمد امروز: {today_income:,} تومان
└ میانگین درآمد: {(total_income/max(1, total_subs)):,.0f} تومان

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
        await db_execute("DELETE FROM coupons")
        await db_execute("DELETE FROM subscriptions")
        await db_execute("DELETE FROM payments")
        await db_execute("DELETE FROM users")
        await db_execute("DELETE FROM free_configs")
        await db_execute("DELETE FROM config_feedback")
        await db_execute("DELETE FROM user_downloads")
        
        logger.info("Database cleared by admin")
        await update.message.reply_text("✅ دیتابیس با موفقیت پاک شد.")
    except Exception as e:
        logger.error(f"Error clearing database: {e}")
        await update.message.reply_text(f"⚠️ خطا در پاک کردن دیتابیس: {str(e)}")

async def debug_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """اشکال‌زدایی اشتراک‌ها (فقط ادمین)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ شما اجازه دسترسی به این دستور را ندارید.")
        return
    
    try:
        subs = await db_execute(
            """SELECT s.id, s.user_id, s.plan, s.status, s.payment_id, 
                      s.start_date, s.duration_days, u.username
               FROM subscriptions s
               LEFT JOIN users u ON s.user_id = u.user_id
               ORDER BY s.id DESC LIMIT 10""",
            fetch=True
        )
        
        if not subs:
            await update.message.reply_text("📂 هیچ اشتراکی یافت نشد.")
            return
        
        response = "🔍 **۱۰ اشتراک آخر:**\n\n"
        current_time = datetime.now()
        
        for sub in subs:
            sub_id, user_id, plan, status, payment_id, start_date, duration_days, username = sub
            username = f"@{username}" if username else f"{user_id}"
            
            remaining = ""
            if status == "active" and start_date:
                end_date = start_date + timedelta(days=duration_days or 30)
                remaining_days = (end_date - current_time).days
                remaining = f" ({remaining_days} روز باقی مانده)"
            
            response += f"**#{sub_id}** - کاربر: {username}\n"
            response += f"پلن: {plan}\n"
            response += f"وضعیت: {status}{remaining}\n"
            response += f"کد پرداخت: #{payment_id}\n"
            response += "━━━━━━━━━━\n"
        
        await update.message.reply_text(response, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in debug_subscriptions: {e}")
        await update.message.reply_text(f"⚠️ خطا: {str(e)}")

# ---------- هندلر شروع ----------
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
    
    # ارسال پیام خوش‌آمدگویی
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

# ---------- هندلر اصلی پیام‌ها ----------
user_states = {}

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر اصلی پیام‌ها"""
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else ""
    
    # لاگ پیام دریافتی
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
            "• پس از تایید، برای دیگر کاربران قابل دانلود خواهد بود\n"
            "• ارسال کانفیگ‌های نامعتبر منجر به مسدودی می‌شود",
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
                    f"**یا**\n\n"
                    f"💎 **ترون:**\n`{TRON_ADDRESS}`\n\n"
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
        "🥇۶ ماهه | ۴۵۰ هزار تومان | نامحدود | ۲ کاربره",
        "🥉۱ ماهه | ۷۰,۰۰۰ تومان | نامحدود | ۲ کاربره",
        "🥈۳ ماهه | ۲۱۰,۰۰۰ تومان | نامحدود | ۲ کاربره",
        "🥇۶ ماهه | ۳۸۰,۰۰۰ تومان | نامحدود | ۲ کاربره"
    ]:
        price_mapping = {
            "🥉۱ ماهه | ۹۰ هزار تومان | نامحدود | ۲ کاربره": 90000,
            "🥈۳ ماهه | ۲۵۰ هزار تومان | نامحدود | ۲ کاربره": 250000,
            "🥇۶ ماهه | ۴۵۰ هزار تومان | نامحدود | ۲ کاربره": 450000,
            "🥉۱ ماهه | ۷۰,۰۰۰ تومان | نامحدود | ۲ کاربره": 70000,
            "🥈۳ ماهه | ۲۱۰,۰۰۰ تومان | نامحدود | ۲ کاربره": 210000,
            "🥇۶ ماهه | ۳۸۰,۰۰۰ تومان | نامحدود | ۲ کاربره": 380000
        }
        
        amount = price_mapping.get(text, 0)
        if amount == 0:
            await update.message.reply_text(
                "⚠️ خطا در انتخاب پلن.",
                reply_markup=get_main_keyboard()
            )
            return
        
        # بررسی نماینده بودن
        is_agent = await is_user_agent(user_id)
        
        if not is_agent:
            await update.message.reply_text(
                f"💎 **پلن انتخاب شده:** {text}\n"
                f"💰 **قیمت:** {amount:,} تومان\n\n"
                "🎫 **اگر کد تخفیف دارید، وارد کنید:**\n"
                "در غیر این صورت برای ادامه روی «ادامه» کلیک کنید.",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("ادامه")],
                    [KeyboardButton("⬅️ بازگشت به منو")]
                ], resize_keyboard=True),
                parse_mode="Markdown"
            )
            user_states[user_id] = f"awaiting_coupon_code_{amount}_{text}"
        else:
            user_states[user_id] = f"awaiting_payment_method_{amount}_{text}"
            await update.message.reply_text(
                "💳 **روش پرداخت را انتخاب کنید:**",
                reply_markup=get_payment_method_keyboard(),
                parse_mode="Markdown"
            )
        return
    
    elif state and state.startswith("awaiting_coupon_code_"):
        parts = state.split("_")
        amount = int(parts[3])
        plan = "_".join(parts[4:])
        
        if text == "ادامه":
            user_states[user_id] = f"awaiting_payment_method_{amount}_{plan}"
            await update.message.reply_text(
                "💳 **روش پرداخت را انتخاب کنید:**",
                reply_markup=get_payment_method_keyboard(),
                parse_mode="Markdown"
            )
            return
        
        # اعتبارسنجی کد تخفیف
        discount, error = await validate_coupon(text.strip(), user_id)
        if error:
            await update.message.reply_text(
                f"⚠️ {error}\n\n"
                "لطفا کد معتبر وارد کنید یا برای ادامه روی «ادامه» کلیک کنید:",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("ادامه")],
                    [KeyboardButton("⬅️ بازگشت به منو")]
                ], resize_keyboard=True),
                parse_mode="Markdown"
            )
            return
        
        # محاسبه مبلغ با تخفیف
        discounted_amount = int(amount * (1 - discount / 100))
        user_states[user_id] = f"awaiting_payment_method_{discounted_amount}_{plan}_{text.strip()}"
        
        await update.message.reply_text(
            f"🎉 **کد تخفیف اعمال شد!**\n\n"
            f"💎 **پلن:** {plan}\n"
            f"💰 **قیمت اصلی:** {amount:,} تومان\n"
            f"🎫 **تخفیف:** {discount}%\n"
            f"💰 **قیمت نهایی:** {discounted_amount:,} تومان\n\n"
            f"💳 **روش پرداخت را انتخاب کنید:**",
            reply_markup=get_payment_method_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    elif state and state.startswith("awaiting_payment_method_"):
        parts = state.split("_")
        amount = int(parts[3])
        plan = "_".join(parts[4:-1]) if len(parts) > 5 else "_".join(parts[4:])
        coupon_code = parts[-1] if len(parts) > 5 and parts[-1] not in ["ترون", "کارت", "موجودی"] else None
        
        if text == "🏦 کارت به کارت":
            payment_id = await add_payment(
                user_id, amount, "buy_subscription", "card_to_card", 
                description=plan, coupon_code=coupon_code
            )
            
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
            payment_id = await add_payment(
                user_id, amount, "buy_subscription", "tron",
                description=plan, coupon_code=coupon_code
            )
            
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
                payment_id = await add_payment(
                    user_id, amount, "buy_subscription", "balance",
                    description=plan, coupon_code=coupon_code
                )
                
                if payment_id:
                    await add_subscription(user_id, payment_id, plan)
                    await deduct_balance(user_id, amount)
                    await update_payment_status(payment_id, "approved")
                    
                    await update.message.reply_text(
                        f"✅ **خرید شما موفقیت‌آمیز بود!**\n\n"
                        f"🎯 **پلن:** {plan}\n"
                        f"💰 **مبلغ پرداختی:** {amount:,} تومان\n"
                        f"🆔 **کد خرید:** #{payment_id}\n\n"
                        f"اشتراک شما فعال شد. کانفیگ تا ۱ ساعت آینده ارسال خواهد شد.",
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
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🟣 ارسال کانفیگ", callback_data=f"send_config_{payment_id}")
                        ]])
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
            "پس از تایید، کانفیگ برای شما ارسال خواهد شد.",
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
                end_date = sub['start_date'] + timedelta(days=sub['duration_days'] or 30)
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
        await handle_agency_request(update, context, user_id)
        return
    
    # ---------- دستورات ادمین ----------
    elif user_id == ADMIN_ID and state == "awaiting_coupon_discount":
        if text.isdigit():
            discount = int(text)
            if 1 <= discount <= 100:
                coupon_code = generate_coupon_code()
                user_states[user_id] = f"awaiting_coupon_recipient_{coupon_code}_{discount}"
                await update.message.reply_text(
                    f"🎫 **کد تخفیف ساخته شد**\n\n"
                    f"🔢 **کد:** `{coupon_code}`\n"
                    f"🎯 **تخفیف:** {discount}%\n\n"
                    f"برای چه کسانی ارسال شود؟",
                    reply_markup=get_coupon_recipient_keyboard(),
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    "⚠️ درصد باید بین ۱ تا ۱۰۰ باشد.",
                    reply_markup=get_back_keyboard()
                )
        else:
            await update.message.reply_text(
                "⚠️ لطفا عدد وارد کنید.",
                reply_markup=get_back_keyboard()
            )
        return
    
    elif user_id == ADMIN_ID and state and state.startswith("awaiting_coupon_recipient_"):
        parts = state.split("_")
        coupon_code = parts[3]
        discount = int(parts[4])
        
        if text == "📢 برای همه":
            await create_coupon(coupon_code, discount)
            
            # ارسال به همه کاربران غیر نماینده
            users = await db_execute(
                "SELECT user_id FROM users WHERE is_agent = FALSE",
                fetch=True
            )
            
            sent = 0
            for user in users:
                try:
                    await context.bot.send_message(
                        chat_id=user[0],
                        text=f"""
🎉 **کد تخفیف جدید!**

🔢 **کد:** `{coupon_code}`
🎯 **تخفیف:** {discount}%
⏰ **اعتبار:** ۳ روز
🔄 **یک بار مصرف**

💎 **برای خرید اشتراک استفاده کنید.**
                        """,
                        parse_mode="Markdown"
                    )
                    sent += 1
                    await asyncio.sleep(0.1)  # جلوگیری از اسپم
                except:
                    continue
            
            await update.message.reply_text(
                f"✅ کد تخفیف برای {sent} کاربر ارسال شد.",
                reply_markup=get_main_keyboard()
            )
            if user_id in user_states:
                del user_states[user_id]
            
        elif text == "👤 برای یک نفر":
            await update.message.reply_text(
                "🆔 ایدی عددی کاربر را وارد کنید:",
                reply_markup=get_back_keyboard()
            )
            user_states[user_id] = f"awaiting_coupon_user_{coupon_code}_{discount}"
            
        elif text == "🎯 درصد خاصی از کاربران":
            await update.message.reply_text(
                "📊 درصد کاربران را وارد کنید (۱-۱۰۰):",
                reply_markup=get_back_keyboard()
            )
            user_states[user_id] = f"awaiting_coupon_percent_{coupon_code}_{discount}"
            
        return
    
    elif user_id == ADMIN_ID and state and state.startswith("awaiting_coupon_user_"):
        parts = state.split("_")
        coupon_code = parts[3]
        discount = int(parts[4])
        
        if text.isdigit():
            target_id = int(text)
            await create_coupon(coupon_code, discount, target_id)
            
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"""
🎉 **کد تخفیف اختصاصی!**

🔢 **کد:** `{coupon_code}`
🎯 **تخفیف:** {discount}%
⏰ **اعتبار:** ۳ روز
🔄 **یک بار مصرف**
👤 **فقط برای شما**

💎 **برای خرید اشتراک استفاده کنید.**
                    """,
                    parse_mode="Markdown"
                )
                
                await update.message.reply_text(
                    f"✅ کد تخفیف برای کاربر {target_id} ارسال شد.",
                    reply_markup=get_main_keyboard()
                )
            except:
                await update.message.reply_text(
                    f"⚠️ ارسال به کاربر {target_id} ناموفق بود.",
                    reply_markup=get_main_keyboard()
                )
            
            if user_id in user_states:
                del user_states[user_id]
        else:
            await update.message.reply_text(
                "⚠️ ایدی عددی وارد کنید.",
                reply_markup=get_back_keyboard()
            )
        return
    
    elif user_id == ADMIN_ID and state and state.startswith("awaiting_coupon_percent_"):
        parts = state.split("_")
        coupon_code = parts[3]
        discount = int(parts[4])
        
        if text.isdigit():
            percent = int(text)
            if 1 <= percent <= 100:
                await create_coupon(coupon_code, discount)
                
                # دریافت کاربران غیر نماینده
                users = await db_execute(
                    "SELECT user_id FROM users WHERE is_agent = FALSE",
                    fetch=True
                )
                
                if users:
                    # انتخاب تصادفی درصدی از کاربران
                    count = max(1, len(users) * percent // 100)
                    selected = random.sample(users, min(count, len(users)))
                    
                    sent = 0
                    for user in selected:
                        try:
                            await context.bot.send_message(
                                chat_id=user[0],
                                text=f"""
🎉 **کد تخفیف ویژه!**

🔢 **کد:** `{coupon_code}`
🎯 **تخفیف:** {discount}%
⏰ **اعتبار:** ۳ روز
🔄 **یک بار مصرف**

💎 **برای خرید اشتراک استفاده کنید.**
                                """,
                                parse_mode="Markdown"
                            )
                            sent += 1
                            await asyncio.sleep(0.1)
                        except:
                            continue
                    
                    await update.message.reply_text(
                        f"✅ کد تخفیف برای {sent} کاربر ({percent}%) ارسال شد.",
                        reply_markup=get_main_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        "⚠️ کاربری یافت نشد.",
                        reply_markup=get_main_keyboard()
                    )
                
                if user_id in user_states:
                    del user_states[user_id]
            else:
                await update.message.reply_text(
                    "⚠️ درصد باید بین ۱ تا ۱۰۰ باشد.",
                    reply_markup=get_back_keyboard()
                )
        else:
            await update.message.reply_text(
                "⚠️ عدد وارد کنید.",
                reply_markup=get_back_keyboard()
            )
        return
    
    elif user_id == ADMIN_ID and state == "awaiting_notification_type":
        if text == "📢 پیام به همه کاربران":
            user_states[user_id] = "awaiting_notification_text_all"
            await update.message.reply_text(
                "📝 متن اطلاعیه را وارد کنید:",
                reply_markup=get_back_keyboard()
            )
        elif text == "🧑‍💼 پیام به نمایندگان":
            user_states[user_id] = "awaiting_notification_text_agents"
            await update.message.reply_text(
                "📝 متن اطلاعیه را وارد کنید:",
                reply_markup=get_back_keyboard()
            )
        elif text == "👤 پیام به یک نفر":
            user_states[user_id] = "awaiting_notification_target"
            await update.message.reply_text(
                "🆔 ایدی کاربر را وارد کنید:",
                reply_markup=get_back_keyboard()
            )
        return
    
    elif user_id == ADMIN_ID and state == "awaiting_notification_target":
        if text.isdigit():
            target_id = int(text)
            user_states[user_id] = f"awaiting_notification_text_{target_id}"
            await update.message.reply_text(
                "📝 متن اطلاعیه را وارد کنید:",
                reply_markup=get_back_keyboard()
            )
        else:
            await update.message.reply_text(
                "⚠️ ایدی عددی وارد کنید.",
                reply_markup=get_back_keyboard()
            )
        return
    
    elif user_id == ADMIN_ID and state.startswith("awaiting_notification_text"):
        notification_text = text
        
        if state == "awaiting_notification_text_all":
            users = await db_execute("SELECT user_id FROM users", fetch=True)
            target_name = "همه کاربران"
        elif state == "awaiting_notification_text_agents":
            users = await db_execute("SELECT user_id FROM users WHERE is_agent = TRUE", fetch=True)
            target_name = "نمایندگان"
        elif state.startswith("awaiting_notification_text_"):
            target_id = int(state.split("_")[-1])
            users = [[target_id]]
            target_name = f"کاربر {target_id}"
        else:
            await update.message.reply_text(
                "⚠️ خطا در پردازش.",
                reply_markup=get_main_keyboard()
            )
            if user_id in user_states:
                del user_states[user_id]
            return
        
        if not users:
            await update.message.reply_text(
                f"⚠️ کاربری ({target_name}) یافت نشد.",
                reply_markup=get_main_keyboard()
            )
            if user_id in user_states:
                del user_states[user_id]
            return
        
        await update.message.reply_text(
            f"📤 **ارسال اطلاعیه به {target_name}**\n\n"
            f"📝 **متن:**\n{notification_text}\n\n"
            f"👥 **تعداد:** {len(users)} نفر\n\n"
            f"✅ برای ارسال «بله» را بزنید.\n❌ برای لغو «خیر» را بزنید.",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("✅ بله، ارسال کن")],
                [KeyboardButton("❌ خیر، انصراف")]
            ], resize_keyboard=True),
            parse_mode="Markdown"
        )
        
        context.user_data["notification_info"] = {
            "users": users,
            "text": notification_text,
            "target": target_name
        }
        user_states[user_id] = f"confirm_notification_{target_name}"
        return
    
    elif user_id == ADMIN_ID and state.startswith("confirm_notification_"):
        if text == "✅ بله، ارسال کن":
            info = context.user_data.get("notification_info", {})
            users = info.get("users", [])
            notification_text = info.get("text", "")
            target_name = info.get("target", "")
            
            sent = 0
            failed = 0
            
            await update.message.reply_text(
                f"🔄 در حال ارسال به {len(users)} {target_name}...",
                reply_markup=None
            )
            
            for user in users:
                try:
                    await context.bot.send_message(
                        chat_id=user[0],
                        text=f"""
📢 **اطلاعیه از مدیریت:**

{notification_text}

━━━━━━━━━━
🤖 ربات تیز VPN
                        """,
                        parse_mode="Markdown"
                    )
                    sent += 1
                    await asyncio.sleep(0.1)
                except:
                    failed += 1
            
            await update.message.reply_text(
                f"✅ **ارسال اطلاعیه تکمیل شد**\n\n"
                f"👥 **هدف:** {target_name}\n"
                f"✅ **ارسال موفق:** {sent} نفر\n"
                f"❌ **ارسال ناموفق:** {failed} نفر\n"
                f"📊 **موفقیت:** {(sent/len(users)*100 if users else 0):.1f}%",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "❌ ارسال اطلاعیه لغو شد.",
                reply_markup=get_main_keyboard()
            )
        
        if "notification_info" in context.user_data:
            del context.user_data["notification_info"]
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # ---------- درخواست نمایندگی ----------
    elif state == "awaiting_agency_request":
        if text == "✅ بله، ادامه می‌دهم":
            await update.message.reply_text(
                "💎 **درخواست نمایندگی**\n\n"
                "💰 **هزینه نمایندگی:** ۱,۰۰۰,۰۰۰ تومان\n\n"
                "💳 **روش پرداخت را انتخاب کنید:**",
                reply_markup=get_payment_method_keyboard(),
                parse_mode="Markdown"
            )
            user_states[user_id] = "awaiting_agency_payment"
        else:
            await update.message.reply_text(
                "❌ درخواست نمایندگی لغو شد.",
                reply_markup=get_main_keyboard()
            )
            if user_id in user_states:
                del user_states[user_id]
        return
    
    elif state == "awaiting_agency_payment":
        if text == "🏦 کارت به کارت":
            payment_id = await add_payment(
                user_id, 1000000, "agency_request", "card_to_card",
                description="درخواست نمایندگی"
            )
            
            if payment_id:
                await update.message.reply_text(
                    "💳 **درخواست نمایندگی**\n\n"
                    "💰 **مبلغ:** ۱,۰۰۰,۰۰۰ تومان\n"
                    "🆔 **کد درخواست:** #{payment_id}\n\n"
                    "**لطفا مبلغ را واریز کنید:**\n\n"
                    "🏦 **کارت به کارت:**\n`{BANK_CARD}`\n"
                    "✍️ **به نام:** فرهنگ\n\n"
                    "⚠️ **توجه:** پس از واریز، فیش را ارسال کنید.",
                    reply_markup=get_back_keyboard(),
                    parse_mode="Markdown"
                )
                user_states[user_id] = f"awaiting_agency_receipt_{payment_id}"
            else:
                await update.message.reply_text(
                    "⚠️ خطا در ثبت درخواست.",
                    reply_markup=get_main_keyboard()
                )
                if user_id in user_states:
                    del user_states[user_id]
            return
        
        elif text == "💎 پرداخت با ترون":
            payment_id = await add_payment(
                user_id, 1000000, "agency_request", "tron",
                description="درخواست نمایندگی"
            )
            
            if payment_id:
                await update.message.reply_text(
                    "💎 **درخواست نمایندگی**\n\n"
                    "💰 **مبلغ:** ۱,۰۰۰,۰۰۰ تومان\n"
                    "🆔 **کد درخواست:** #{payment_id}\n\n"
                    "**لطفا مبلغ را واریز کنید:**\n\n"
                    "💎 **آدرس ترون:**\n`{TRON_ADDRESS}`\n\n"
                    "⚠️ **توجه:** پس از واریز، فیش را ارسال کنید.",
                    reply_markup=get_back_keyboard(),
                    parse_mode="Markdown"
                )
                user_states[user_id] = f"awaiting_agency_receipt_{payment_id}"
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
            
            if balance >= 1000000:
                payment_id = await add_payment(
                    user_id, 1000000, "agency_request", "balance",
                    description="درخواست نمایندگی"
                )
                
                if payment_id:
                    await deduct_balance(user_id, 1000000)
                    await update_payment_status(payment_id, "approved")
                    await set_user_agent(user_id)
                    
                    await update.message.reply_text(
                        "🎉 **تبریک!**\n\n"
                        "✅ **نمایندگی شما فعال شد!**\n\n"
                        "💰 **۱,۰۰۰,۰۰۰ تومان** به موجودی شما اضافه شد.\n"
                        "🧑‍💼 **حساب شما به نماینده ارتقا یافت.**\n\n"
                        "🎯 **اکنون می‌توانید:**\n"
                        "• با قیمت نمایندگی خرید کنید\n"
                        "• از پنل اختصاصی استفاده کنید\n"
                        "• کسب درآمد کنید\n\n"
                        "👨‍💼 برای اطلاعات بیشتر با پشتیبانی تماس بگیرید.",
                        reply_markup=get_main_keyboard(),
                        parse_mode="Markdown"
                    )
                    
                    # اطلاع به ادمین
                    await context.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"""
🎉 **نماینده جدید!**

👤 **کاربر:** {user_id} (@{update.effective_user.username or 'بدون یوزرنیم'})
💰 **پرداخت با موجودی**
🆔 **کد:** #{payment_id}
⏰ **زمان:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
                        """,
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(
                        "⚠️ خطا در ثبت درخواست.",
                        reply_markup=get_main_keyboard()
                    )
            else:
                await update.message.reply_text(
                    f"⚠️ **موجودی کافی نیست!**\n\n"
                    f"💰 **موجودی شما:** {balance:,} تومان\n"
                    f"💰 **مورد نیاز:** ۱,۰۰۰,۰۰۰ تومان\n"
                    f"💰 **کمبود:** {1000000 - balance:,} تومان",
                    reply_markup=get_main_keyboard(),
                    parse_mode="Markdown"
                )
            
            if user_id in user_states:
                del user_states[user_id]
            return
    
    elif state and state.startswith("awaiting_agency_receipt_"):
        payment_id = int(state.split("_")[-1])
        
        # ارسال فیش به ادمین
        caption = f"""
💼 **فیش درخواست نمایندگی**

👤 **کاربر:** {user_id} (@{update.effective_user.username or 'بدون یوزرنیم'})
💰 **مبلغ:** ۱,۰۰۰,۰۰۰ تومان
🆔 **کد درخواست:** #{payment_id}
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
                "⚠️ لطفا فیش را ارسال کنید.",
                reply_markup=get_back_keyboard()
            )
            return
        
        await update.message.reply_text(
            "✅ فیش شما برای ادمین ارسال شد.\n"
            "پس از تایید، نمایندگی شما فعال خواهد شد.",
            reply_markup=get_main_keyboard()
        )
        
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # ---------- حذف کاربر ----------
    elif user_id == ADMIN_ID and state == "awaiting_user_id_for_removal":
        if text.isdigit():
            target_id = int(text)
            
            # تأیید نهایی
            keyboard = ReplyKeyboardMarkup([
                [KeyboardButton(f"✅ بله، کاربر {target_id} را حذف کن")],
                [KeyboardButton("❌ خیر، انصراف")]
            ], resize_keyboard=True)
            
            await update.message.reply_text(
                f"⚠️ **هشدار!**\n\n"
                f"آیا مطمئن هستید که می‌خواهید کاربر {target_id} را حذف کنید؟\n\n"
                f"🔴 **این عمل غیرقابل بازگشت است!**\n"
                f"• تمام اطلاعات کاربر پاک می‌شود\n"
                f"• اشتراک‌ها حذف می‌شوند\n"
                f"• پرداخت‌ها پاک می‌شوند\n\n"
                f"برای تأیید دکمه زیر را بزنید.",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            
            context.user_data["remove_target"] = target_id
            user_states[user_id] = "confirm_user_removal"
        else:
            await update.message.reply_text(
                "⚠️ ایدی عددی وارد کنید.",
                reply_markup=get_back_keyboard()
            )
        return
    
    elif user_id == ADMIN_ID and state == "confirm_user_removal":
        if text.startswith("✅ بله"):
            target_id = context.user_data.get("remove_target")
            
            if target_id:
                try:
                    # حذف کاربر از همه جداول
                    await db_execute("DELETE FROM user_downloads WHERE user_id = %s", (target_id,))
                    await db_execute("DELETE FROM config_feedback WHERE user_id = %s", (target_id,))
                    await db_execute("DELETE FROM coupons WHERE user_id = %s", (target_id,))
                    
                    # حذف اشتراک‌های کاربر
                    await db_execute("DELETE FROM subscriptions WHERE user_id = %s", (target_id,))
                    
                    # حذف پرداخت‌های کاربر
                    await db_execute("DELETE FROM payments WHERE user_id = %s", (target_id,))
                    
                    # حذف کانفیگ‌های ارسالی کاربر
                    await db_execute("DELETE FROM free_configs WHERE uploaded_by = %s", (target_id,))
                    
                    # حذف خود کاربر
                    await db_execute("DELETE FROM users WHERE user_id = %s", (target_id,))
                    
                    await update.message.reply_text(
                        f"✅ کاربر {target_id} با موفقیت حذف شد.",
                        reply_markup=get_main_keyboard()
                    )
                    
                    logger.info(f"Admin removed user {target_id}")
                except Exception as e:
                    logger.error(f"Error removing user {target_id}: {e}")
                    await update.message.reply_text(
                        f"⚠️ خطا در حذف کاربر: {str(e)}",
                        reply_markup=get_main_keyboard()
                    )
            else:
                await update.message.reply_text(
                    "⚠️ اطلاعات کاربر یافت نشد.",
                    reply_markup=get_main_keyboard()
                )
        else:
            await update.message.reply_text(
                "❌ عملیات حذف لغو شد.",
                reply_markup=get_main_keyboard()
            )
        
        if "remove_target" in context.user_data:
            del context.user_data["remove_target"]
        if user_id in user_states:
            del user_states[user_id]
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

async def handle_agency_request(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """پردازش درخواست نمایندگی"""
    is_agent = await is_user_agent(user_id)
    
    if is_agent:
        await update.message.reply_text(
            "🧑‍💼 **شما قبلاً نماینده هستید!**\n\n"
            "می‌توانید با قیمت نمایندگی خرید کنید.",
            reply_markup=get_subscription_keyboard(True),
            parse_mode="Markdown"
        )
        return
    
    agency_info = """
🚀 **اعطای نمایندگی رسمی تیز VPN**

💎 **مزایای نمایندگی:**
✅ خرید با قیمت نماینده (۲۰-۳۰٪ تخفیف)
✅ پنل اختصاصی مدیریت کاربران
✅ تعیین قیمت دلخواه برای فروش
✅ پشتیبانی ویژه
✅ درآمدزایی دائمی

💰 **هزینه نمایندگی: ۱,۰۰۰,۰۰۰ تومان**

🎯 **پس از پرداخت:**
• ۱,۰۰۰,۰۰۰ تومان به موجودی شما اضافه می‌شود
• حساب شما به نماینده ارتقا می‌یابد
• پنل اختصاصی دریافت می‌کنید

❓ **آیا ادامه می‌دهید؟**
    """
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("✅ بله، ادامه می‌دهم")],
        [KeyboardButton("❌ خیر، انصراف")]
    ], resize_keyboard=True)
    
    await update.message.reply_text(
        agency_info,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    
    user_states[user_id] = "awaiting_agency_request"

# ---------- هندلر کال‌بک ----------
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
                config = await db_execute(
                    "SELECT uploaded_by, file_name FROM free_configs WHERE id = %s",
                    (config_id,), fetchone=True
                )
                
                if config:
                    uploaded_by, file_name = config
                    
                    # اطلاع به ارسال کننده
                    try:
                        await context.bot.send_message(
                            chat_id=uploaded_by,
                            text=f"""
✅ **کانفیگ شما تایید شد!**

📁 **فایل:** {file_name}
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
            config = await db_execute(
                "SELECT uploaded_by, file_name FROM free_configs WHERE id = %s",
                (config_id,), fetchone=True
            )
            
            if config:
                uploaded_by, file_name = config
                
                # اطلاع به ارسال کننده
                try:
                    await context.bot.send_message(
                        chat_id=uploaded_by,
                        text=f"""
❌ **کانفیگ شما رد شد!**

📁 **فایل:** {file_name}
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
            payment = await db_execute(
                """SELECT user_id, amount, type, description, payment_method 
                   FROM payments WHERE id = %s""",
                (payment_id,), fetchone=True
            )
            
            if not payment:
                await query.edit_message_text("⚠️ پرداخت یافت نشد.")
                return
            
            buyer_id, amount, ptype, description, method = payment
            
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

🎯 **پلن:** {description}
💰 **مبلغ:** {amount:,} تومان
🆔 **کد خرید:** #{payment_id}

⏳ **کانفیگ تا ۱ ساعت آینده ارسال خواهد شد.**
                    """,
                    parse_mode="Markdown"
                )
                
                # درخواست کانفیگ از ادمین
                await query.edit_message_text(
                    f"✅ پرداخت #{payment_id} تایید شد.\n"
                    f"🎯 پلن: {description}\n"
                    f"💰 مبلغ: {amount:,} تومان\n\n"
                    f"📤 لطفا کانفیگ را ارسال کنید:",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🟣 ارسال کانفیگ", callback_data=f"send_config_{payment_id}")
                    ]])
                )
                
            elif ptype == "agency_request":
                # فعال کردن نمایندگی
                await set_user_agent(buyer_id)
                await add_balance(buyer_id, amount)
                
                # اطلاع به کاربر
                await context.bot.send_message(
                    chat_id=buyer_id,
                    text=f"""
🎉 **تبریک! نمایندگی شما فعال شد!**

🧑‍💼 **حساب شما به نماینده ارتقا یافت.**
💰 **{amount:,} تومان به موجودی شما اضافه شد.**

🎯 **اکنون می‌توانید:**
• با قیمت نماینده خرید کنید
• از پنل اختصاصی استفاده کنید
• کسب درآمد کنید

👨‍💼 **برای راهنمایی بیشتر با پشتیبانی تماس بگیرید.**
                    """,
                    parse_mode="Markdown"
                )
                
                await query.edit_message_text(
                    f"✅ نمایندگی کاربر #{buyer_id} فعال شد.\n"
                    f"💰 {amount:,} تومان به موجودی او اضافه شد.",
                    parse_mode="Markdown"
                )
            
            logger.info(f"Payment {payment_id} approved by admin")
            return
        
        elif data.startswith("reject_"):
            payment_id = int(data.split("_")[-1])
            
            # دریافت اطلاعات پرداخت
            payment = await db_execute(
                "SELECT user_id, amount, type FROM payments WHERE id = %s",
                (payment_id,), fetchone=True
            )
            
            if payment:
                buyer_id, amount, ptype = payment
                
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
        
        # درخواست ارسال کانفیگ
        elif data.startswith("send_config_"):
            payment_id = int(data.split("_")[-1])
            
            await query.edit_message_text(
                f"📤 **ارسال کانفیگ برای پرداخت #{payment_id}**\n\n"
                f"لطفا کانفیگ را به صورت متن ارسال کنید.",
                parse_mode="Markdown"
            )
            
            user_states[user_id] = f"awaiting_config_{payment_id}"
            return
        
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await query.edit_message_text(f"⚠️ خطا: {str(e)}")

# ---------- ثبت هندلرها ----------
def setup_handlers():
    """تنظیم هندلرهای ربات"""
    # هندلر دستورات
    application.add_handler(CommandHandler("start", start_with_param))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("user_info", user_info_command))
    application.add_handler(CommandHandler("coupon", coupon_command))
    application.add_handler(CommandHandler("notification", notification_command))
    application.add_handler(CommandHandler("backup", backup_command))
    application.add_handler(CommandHandler("restore", restore_command))
    application.add_handler(CommandHandler("remove_user", remove_user_command))
    application.add_handler(CommandHandler("cleardb", clear_db_command))
    application.add_handler(CommandHandler("debug_subscriptions", debug_subscriptions))
    
    # هندلر کال‌بک‌ها
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # هندلر پیام‌ها
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, message_handler))

# ---------- وب‌هوک ----------
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

# ---------- تنظیم دستورات بات ----------
async def set_bot_commands():
    """تنظیم دستورات بات"""
    try:
        commands = [
            BotCommand("start", "شروع ربات"),
            BotCommand("stats", "آمار ربات (ادمین)"),
            BotCommand("user_info", "اطلاعات کاربران (ادمین)"),
            BotCommand("coupon", "ایجاد کد تخفیف (ادمین)"),
            BotCommand("notification", "ارسال اطلاعیه (ادمین)"),
            BotCommand("debug_subscriptions", "اشکال‌زدایی اشتراک‌ها (ادمین)"),
            BotCommand("cleardb", "پاک کردن دیتابیس (ادمین)"),
            BotCommand("remove_user", "حذف کاربر (ادمین)")
        ]
        
        await application.bot.set_my_commands(commands)
        logger.info("✅ Bot commands set successfully")
    except Exception as e:
        logger.error(f"Error setting bot commands: {e}")

# ---------- راه‌اندازی ----------
@app.on_event("startup")
async def startup():
    """رویداد راه‌اندازی برنامه"""
    try:
        logger.info("🚀 Starting Teaz VPN Bot on Railway...")
        
        # راه‌اندازی دیتابیس
        init_db_pool()
        
        # ساخت جداول
        await create_tables()
        
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
            logger.warning("⚠️ WEBHOOK_URL not set, using polling")
        
        # تنظیم دستورات
        await set_bot_commands()
        
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
🌐 **دامنه:** {RAILWAY_PUBLIC_DOMAIN or 'Not set'}

🟢 **آماده به کار**
                """,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")
        
        logger.info("✅ Bot started successfully on Railway!")
        
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")
        raise

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
        
        # بستن دیتابیس
        close_db_pool()
        
        logger.info("✅ Bot shut down successfully")
        
    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}")

# ---------- اجرای اصلی ----------
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8080))
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
