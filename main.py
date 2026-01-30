import os
import logging
import asyncio
import random
import string
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, 
    InlineKeyboardButton, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, 
    filters, CallbackQueryHandler
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
    handlers=[logging.StreamHandler()]
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
    return {
        "status": "healthy",
        "bot": "running",
        "timestamp": datetime.now().isoformat()
    }

# ---------- Telegram Application ----------
application = Application.builder().token(TOKEN).build()

# ---------- PostgreSQL Connection Pool ----------
import psycopg2
from psycopg2 import pool

# تنظیمات دیتابیس برای Railway
# Railway به صورت خودکار DATABASE_URL را تنظیم می‌کند
# اما اگر وجود نداشت، می‌توانیم از متغیرهای دیگر استفاده کنیم
def get_database_url():
    """دریافت آدرس دیتابیس از متغیرهای محیطی"""
    # اولویت‌بندی متغیرهای محیطی
    url = os.getenv("DATABASE_URL")
    if url:
        logger.info("Using DATABASE_URL from environment")
        return url
    
    url = os.getenv("POSTGRESQL_URL")
    if url:
        logger.info("Using POSTGRESQL_URL from environment")
        return url
    
    url = os.getenv("NEON_DATABASE_URL")
    if url:
        logger.info("Using NEON_DATABASE_URL from environment")
        return url
    
    # برای توسعه محلی
    url = os.getenv("LOCAL_DB_URL")
    if url:
        logger.info("Using LOCAL_DB_URL from environment")
        return url
    
    logger.warning("No database URL found in environment variables")
    return None

DATABASE_URL = get_database_url()

# اگر دیتابیس موجود نیست، از حالت حافظه استفاده می‌کنیم
USE_MEMORY_DB = DATABASE_URL is None

db_pool = None
memory_db = {}  # دیتابیس درون حافظه برای حالت تست

class MemoryDB:
    """کلاس شبیه‌ساز دیتابیس درون حافظه"""
    def __init__(self):
        self.users = {}
        self.payments = {}
        self.subscriptions = {}
        self.coupons = {}
        self.free_configs = {}
        self.config_feedback = {}
        self.user_downloads = {}
        self.payment_counter = 1
        self.sub_counter = 1
        self.config_counter = 1
        self.feedback_counter = 1
    
    async def execute(self, query, params=(), fetch=False, fetchone=False, returning=False):
        """شبیه‌سازی اجرای کوئری"""
        query_lower = query.strip().lower()
        
        try:
            # SELECT queries
            if query_lower.startswith("select"):
                if "from users where user_id" in query_lower:
                    user_id = params[0]
                    user = self.users.get(user_id)
                    if fetchone:
                        return (user,) if user else None
                    return [user] if user else []
                
                elif "from users" in query_lower:
                    if fetch:
                        return list(self.users.values())
                    return []
                
                elif "from payments" in query_lower:
                    if fetch:
                        return list(self.payments.values())
                    return []
                
                elif "from subscriptions" in query_lower:
                    if fetch:
                        return list(self.subscriptions.values())
                    return []
                
                elif "from coupons" in query_lower:
                    if fetch:
                        return list(self.coupons.values())
                    return []
                
                elif "from free_configs" in query_lower:
                    if fetch:
                        return list(self.free_configs.values())
                    return []
            
            # INSERT queries
            elif query_lower.startswith("insert"):
                if "into users" in query_lower:
                    user_id = params[0]
                    username = params[1]
                    invited_by = params[2] if len(params) > 2 else None
                    
                    self.users[user_id] = {
                        'user_id': user_id,
                        'username': username,
                        'balance': 0,
                        'invited_by': invited_by,
                        'phone': None,
                        'created_at': datetime.now(),
                        'is_agent': False,
                        'is_new_user': True
                    }
                    
                    if returning:
                        return user_id
                
                elif "into payments" in query_lower:
                    payment_id = self.payment_counter
                    self.payment_counter += 1
                    
                    self.payments[payment_id] = {
                        'id': payment_id,
                        'user_id': params[0],
                        'amount': params[1],
                        'status': 'pending',
                        'type': params[2],
                        'payment_method': params[3],
                        'description': params[4] if len(params) > 4 else '',
                        'created_at': datetime.now()
                    }
                    
                    if returning:
                        return payment_id
                
                elif "into subscriptions" in query_lower:
                    sub_id = self.sub_counter
                    self.sub_counter += 1
                    
                    self.subscriptions[sub_id] = {
                        'id': sub_id,
                        'user_id': params[0],
                        'payment_id': params[1],
                        'plan': params[2],
                        'config': None,
                        'status': 'pending',
                        'start_date': datetime.now(),
                        'duration_days': params[3] if len(params) > 3 else 30
                    }
                    
                    if returning:
                        return sub_id
                
                elif "into coupons" in query_lower:
                    code = params[0]
                    self.coupons[code] = {
                        'code': code,
                        'discount_percent': params[1],
                        'user_id': params[2] if len(params) > 2 else None,
                        'is_used': False,
                        'created_at': datetime.now(),
                        'expiry_date': datetime.now() + timedelta(days=3)
                    }
                
                elif "into free_configs" in query_lower:
                    config_id = self.config_counter
                    self.config_counter += 1
                    
                    self.free_configs[config_id] = {
                        'id': config_id,
                        'file_id': params[0],
                        'file_name': params[1],
                        'file_size': params[2],
                        'mime_type': params[3],
                        'uploaded_by': params[4],
                        'uploaded_at': datetime.now(),
                        'is_approved': False,
                        'approved_by': None,
                        'approved_at': None,
                        'download_count': 0,
                        'successful_count': 0,
                        'unsuccessful_count': 0
                    }
                    
                    if returning:
                        return config_id
                
                elif "into config_feedback" in query_lower:
                    feedback_id = self.feedback_counter
                    self.feedback_counter += 1
                    
                    self.config_feedback[feedback_id] = {
                        'id': feedback_id,
                        'config_id': params[0],
                        'user_id': params[1],
                        'worked': params[2],
                        'operator': params[3] if len(params) > 3 else None,
                        'feedback_at': datetime.now()
                    }
                
                elif "into user_downloads" in query_lower:
                    key = (params[0], params[1])
                    self.user_downloads[key] = {
                        'user_id': params[0],
                        'config_id': params[1],
                        'downloaded_at': datetime.now()
                    }
            
            # UPDATE queries
            elif query_lower.startswith("update"):
                if "users set" in query_lower:
                    if "balance = coalesce(balance,0) +" in query_lower:
                        user_id = params[1]
                        amount = params[0]
                        if user_id in self.users:
                            self.users[user_id]['balance'] += amount
                    
                    elif "balance = coalesce(balance,0) -" in query_lower:
                        user_id = params[1]
                        amount = params[0]
                        if user_id in self.users:
                            self.users[user_id]['balance'] = max(0, self.users[user_id]['balance'] - amount)
                    
                    elif "is_agent = true" in query_lower:
                        user_id = params[0]
                        if user_id in self.users:
                            self.users[user_id]['is_agent'] = True
                    
                    elif "is_new_user = false" in query_lower:
                        user_id = params[0]
                        if user_id in self.users:
                            self.users[user_id]['is_new_user'] = False
                    
                    elif "phone =" in query_lower:
                        user_id = params[1]
                        phone = params[0]
                        if user_id in self.users:
                            self.users[user_id]['phone'] = phone
                
                elif "payments set status =" in query_lower:
                    payment_id = params[1]
                    status = params[0]
                    if payment_id in self.payments:
                        self.payments[payment_id]['status'] = status
                
                elif "subscriptions set config =" in query_lower:
                    config = params[0]
                    payment_id = params[1]
                    
                    # پیدا کردن اشتراک با payment_id
                    for sub_id, sub in self.subscriptions.items():
                        if sub['payment_id'] == payment_id:
                            self.subscriptions[sub_id]['config'] = config
                            self.subscriptions[sub_id]['status'] = 'active'
                            break
                
                elif "subscriptions set status =" in query_lower:
                    sub_id = params[1]
                    status = params[0]
                    if sub_id in self.subscriptions:
                        self.subscriptions[sub_id]['status'] = status
                
                elif "free_configs set is_approved = true" in query_lower:
                    approved_by = params[0]
                    config_id = params[1]
                    if config_id in self.free_configs:
                        self.free_configs[config_id]['is_approved'] = True
                        self.free_configs[config_id]['approved_by'] = approved_by
                        self.free_configs[config_id]['approved_at'] = datetime.now()
                
                elif "free_configs set download_count = download_count + 1" in query_lower:
                    config_id = params[0]
                    if config_id in self.free_configs:
                        self.free_configs[config_id]['download_count'] += 1
                
                elif "free_configs set successful_count = successful_count + 1" in query_lower:
                    config_id = params[0]
                    if config_id in self.free_configs:
                        self.free_configs[config_id]['successful_count'] += 1
                
                elif "free_configs set unsuccessful_count = unsuccessful_count + 1" in query_lower:
                    config_id = params[0]
                    if config_id in self.free_configs:
                        self.free_configs[config_id]['unsuccessful_count'] += 1
                
                elif "coupons set is_used = true" in query_lower:
                    code = params[0]
                    if code in self.coupons:
                        self.coupons[code]['is_used'] = True
            
            # DELETE queries
            elif query_lower.startswith("delete"):
                if "from free_configs where id =" in query_lower:
                    config_id = params[0]
                    if config_id in self.free_configs:
                        del self.free_configs[config_id]
                
                elif "from users where user_id =" in query_lower:
                    user_id = params[0]
                    if user_id in self.users:
                        del self.users[user_id]
            
            return None
            
        except Exception as e:
            logger.error(f"MemoryDB error: {e}")
            raise

# ایجاد نمونه دیتابیس حافظه
memory_db_instance = MemoryDB() if USE_MEMORY_DB else None

def init_db_pool():
    """راه‌اندازی اتصال دیتابیس"""
    global db_pool
    
    if USE_MEMORY_DB:
        logger.info("⚠️ Using in-memory database (no DATABASE_URL found)")
        return
    
    try:
        logger.info(f"Initializing database connection to: {DATABASE_URL[:50]}...")
        db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=DATABASE_URL
        )
        logger.info("✅ Database pool initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize database pool: {e}")
        raise

def close_db_pool():
    """بستن اتصال دیتابیس"""
    global db_pool
    if db_pool:
        db_pool.closeall()
        logger.info("Database pool closed")

async def db_execute(query, params=(), fetch=False, fetchone=False, returning=False):
    """اجرای کوئری (با پشتیبانی از حافظه)"""
    if USE_MEMORY_DB:
        return await memory_db_instance.execute(query, params, fetch, fetchone, returning)
    
    # استفاده از دیتابیس واقعی
    import psycopg2
    conn = None
    cur = None
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute(query, params)
        
        result = None
        if returning:
            result = cur.fetchone()[0] if cur.rowcount > 0 else None
        elif fetchone:
            result = cur.fetchone()
        elif fetch:
            result = cur.fetchall()
        
        if not query.strip().lower().startswith("select"):
            conn.commit()
        
        return result
    except Exception as e:
        logger.error(f"Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            db_pool.putconn(conn)

# ---------- ساخت جداول دیتابیس ----------
async def create_tables():
    """ساخت جداول مورد نیاز"""
    if USE_MEMORY_DB:
        logger.info("⚠️ Skipping table creation (using memory database)")
        return
    
    try:
        # ساخت جداول (فقط اگر در دیتابیس واقعی هستیم)
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
                unsuccessful_count INTEGER DEFAULT 0
            )
        """)
        
        await db_execute("""
            CREATE TABLE IF NOT EXISTS config_feedback (
                id SERIAL PRIMARY KEY,
                config_id INTEGER,
                user_id BIGINT,
                worked BOOLEAN,
                operator TEXT,
                feedback_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db_execute("""
            CREATE TABLE IF NOT EXISTS user_downloads (
                user_id BIGINT,
                config_id INTEGER,
                downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, config_id)
            )
        """)
        
        logger.info("✅ Database tables created successfully")
    except Exception as e:
        logger.error(f"❌ Error creating tables: {e}")

# ---------- توابع کمکی ----------
def generate_coupon_code(length=8):
    """تولید کد تخفیف تصادفی"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ---------- کیبوردها ----------
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🇮🇷 کانفیگ های رایگان مردم")],
        [KeyboardButton("💰 موجودی"), KeyboardButton("💳 خرید اشتراک")],
        [KeyboardButton("🎁 اشتراک تست رایگان"), KeyboardButton("☎️ پشتیبانی")],
        [KeyboardButton("💵 اعتبار رایگان"), KeyboardButton("📂 اشتراک‌های من")],
        [KeyboardButton("💡 راهنمای اتصال"), KeyboardButton("🧑‍💼 درخواست نمایندگی")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_free_configs_keyboard():
    keyboard = [
        [KeyboardButton("📥 دریافت کانفیگ")],
        [KeyboardButton("📤 ارسال کانفیگ")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_operator_keyboard():
    keyboard = [
        [KeyboardButton("همراه اول"), KeyboardButton("ایرانسل")],
        [KeyboardButton("رایتل"), KeyboardButton("مخابرات")],
        [KeyboardButton("شاتل"), KeyboardButton("سامانتل")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_feedback_keyboard():
    keyboard = [
        [KeyboardButton("کار کرد✅"), KeyboardButton("کار نکرد❌")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_balance_keyboard():
    keyboard = [
        [KeyboardButton("نمایش موجودی"), KeyboardButton("افزایش موجودی")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_subscription_keyboard(is_agent=False):
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
    keyboard = [
        [KeyboardButton("🏦 کارت به کارت")],
        [KeyboardButton("💎 پرداخت با ترون")],
        [KeyboardButton("💰 پرداخت با موجودی")],
        [KeyboardButton("⬅️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("⬅️ بازگشت به منو")]], resize_keyboard=True)

# ---------- توابع دیتابیس ----------
async def is_user_member(user_id):
    """بررسی عضویت کاربر در کانال"""
    try:
        member = await application.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

async def ensure_user(user_id, username, invited_by=None):
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
        logger.error(f"Error ensuring user: {e}")
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
        logger.error(f"Error checking agent status: {e}")
        return False

async def set_user_agent(user_id):
    """تنظیم کاربر به عنوان نماینده"""
    try:
        await db_execute(
            "UPDATE users SET is_agent = TRUE WHERE user_id = %s",
            (user_id,)
        )
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
        logger.error(f"Error getting balance: {e}")
        return 0

async def add_balance(user_id, amount):
    """افزایش موجودی کاربر"""
    try:
        await db_execute(
            "UPDATE users SET balance = COALESCE(balance, 0) + %s WHERE user_id = %s",
            (amount, user_id)
        )
    except Exception as e:
        logger.error(f"Error adding balance: {e}")

async def deduct_balance(user_id, amount):
    """کاهش موجودی کاربر"""
    try:
        await db_execute(
            "UPDATE users SET balance = COALESCE(balance, 0) - %s WHERE user_id = %s",
            (amount, user_id)
        )
    except Exception as e:
        logger.error(f"Error deducting balance: {e}")

async def add_payment(user_id, amount, ptype, payment_method, description="", coupon_code=None):
    """ثبت پرداخت جدید"""
    try:
        result = await db_execute(
            "INSERT INTO payments (user_id, amount, type, payment_method, description) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, amount, ptype, payment_method, description),
            returning=True
        )
        
        if coupon_code:
            await mark_coupon_used(coupon_code)
            
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
            "INSERT INTO subscriptions (user_id, payment_id, plan, start_date, duration_days) VALUES (%s, %s, %s, CURRENT_TIMESTAMP, %s)",
            (user_id, payment_id, plan, duration_days)
        )
    except Exception as e:
        logger.error(f"Error adding subscription: {e}")

async def update_subscription_config(payment_id, config):
    """بروزرسانی کانفیگ اشتراک"""
    try:
        await db_execute(
            "UPDATE subscriptions SET config = %s, status = 'active' WHERE payment_id = %s",
            (config, payment_id)
        )
    except Exception as e:
        logger.error(f"Error updating subscription config: {e}")

async def update_payment_status(payment_id, status):
    """بروزرسانی وضعیت پرداخت"""
    try:
        await db_execute(
            "UPDATE payments SET status = %s WHERE id = %s",
            (status, payment_id)
        )
    except Exception as e:
        logger.error(f"Error updating payment status: {e}")

async def create_coupon(code, discount_percent, user_id=None):
    """ایجاد کد تخفیف"""
    try:
        await db_execute(
            "INSERT INTO coupons (code, discount_percent, user_id) VALUES (%s, %s, %s)",
            (code, discount_percent, user_id)
        )
    except Exception as e:
        logger.error(f"Error creating coupon: {e}")

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
        
        return discount_percent, None
    except Exception as e:
        logger.error(f"Error validating coupon: {e}")
        return None, "خطا در بررسی کد تخفیف."

async def mark_coupon_used(code):
    """علامت‌گذاری کد تخفیف به عنوان استفاده‌شده"""
    try:
        await db_execute(
            "UPDATE coupons SET is_used = TRUE WHERE code = %s",
            (code,)
        )
    except Exception as e:
        logger.error(f"Error marking coupon as used: {e}")

# ---------- دستورات اصلی ----------
user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور شروع"""
    user = update.effective_user
    user_id = user.id
    username = user.username or ""
    
    # چک عضویت در کانال
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
    
    await update.message.reply_text(
        "🌐 به فروشگاه تیز VPN خوش آمدید!\n\nیک گزینه را انتخاب کنید:",
        reply_markup=get_main_keyboard()
    )
    
    if user_id in user_states:
        del user_states[user_id]

async def start_with_param(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """شروع با پارامتر"""
    args = context.args
    if args and len(args) > 0:
        try:
            invited_by = int(args[0])
            if invited_by != update.effective_user.id:
                context.user_data["invited_by"] = invited_by
        except:
            context.user_data["invited_by"] = None
    
    await start(update, context)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر پیام‌ها"""
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else ""
    
    # بازگشت به منو
    if text in ["بازگشت به منو", "⬅️ بازگشت به منو"]:
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard())
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # بخش کانفیگ رایگان
    if text == "🇮🇷 کانفیگ های رایگان مردم":
        await update.message.reply_text(
            "🇮🇷 بخش کانفیگ‌های رایگان مردمی\n\nیک گزینه را انتخاب کنید:",
            reply_markup=get_free_configs_keyboard()
        )
        return
    
    elif text == "📥 دریافت کانفیگ":
        # در نسخه ساده، فقط یک پیام نشان می‌دهیم
        await update.message.reply_text(
            "⚠️ این قابلیت در حال توسعه است.\nبه زودی فعال می‌شود.",
            reply_markup=get_free_configs_keyboard()
        )
        return
    
    elif text == "📤 ارسال کانفیگ":
        await update.message.reply_text(
            "⚠️ این قابلیت در حال توسعه است.\nبه زودی فعال می‌شود.",
            reply_markup=get_free_configs_keyboard()
        )
        return
    
    # بخش موجودی
    elif text == "💰 موجودی":
        balance = await get_balance(user_id)
        await update.message.reply_text(
            f"💰 موجودی شما: {balance:,} تومان",
            reply_markup=get_balance_keyboard()
        )
        return
    
    elif text == "نمایش موجودی":
        balance = await get_balance(user_id)
        await update.message.reply_text(f"💰 موجودی شما: {balance:,} تومان", reply_markup=get_balance_keyboard())
        return
    
    elif text == "افزایش موجودی":
        await update.message.reply_text(
            "💳 لطفا مبلغ واریزی را به تومان وارد کنید (مثال: 100000):",
            reply_markup=get_back_keyboard()
        )
        user_states[user_id] = "awaiting_deposit_amount"
        return
    
    elif user_states.get(user_id) == "awaiting_deposit_amount":
        if text.isdigit():
            amount = int(text)
            payment_id = await add_payment(user_id, amount, "increase_balance", "card_to_card")
            
            if payment_id:
                await update.message.reply_text(
                    f"💳 درخواست افزایش موجودی\n\n"
                    f"💰 مبلغ: {amount:,} تومان\n"
                    f"🆔 کد تراکنش: #{payment_id}\n\n"
                    f"لطفا مبلغ را واریز کنید:\n\n"
                    f"🏦 کارت به کارت:\n{BANK_CARD}\n"
                    f"✍️ به نام: فرهنگ\n\n"
                    f"⚠️ پس از واریز، فیش را ارسال کنید.",
                    reply_markup=get_back_keyboard()
                )
                user_states[user_id] = f"awaiting_deposit_receipt_{payment_id}"
            else:
                await update.message.reply_text("⚠️ خطا در ثبت درخواست.", reply_markup=get_main_keyboard())
                if user_id in user_states:
                    del user_states[user_id]
        else:
            await update.message.reply_text("⚠️ لطفا عدد وارد کنید.", reply_markup=get_back_keyboard())
        return
    
    # پردازش فیش پرداخت
    elif user_states.get(user_id, "").startswith("awaiting_deposit_receipt_"):
        payment_id = int(user_states[user_id].split("_")[-1])
        
        # ارسال فیش به ادمین
        caption = f"💳 فیش واریزی\n👤 کاربر: {user_id}\n💰 مبلغ: ...\n🆔 کد: #{payment_id}"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ تایید", callback_data=f"approve_{payment_id}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{payment_id}")
            ]
        ])
        
        if update.message.photo:
            await context.bot.send_photo(ADMIN_ID, update.message.photo[-1].file_id, caption=caption, reply_markup=keyboard)
        elif update.message.document:
            await context.bot.send_document(ADMIN_ID, update.message.document.file_id, caption=caption, reply_markup=keyboard)
        else:
            await update.message.reply_text("⚠️ لطفا فیش را ارسال کنید.", reply_markup=get_back_keyboard())
            return
        
        await update.message.reply_text(
            "✅ فیش شما برای ادمین ارسال شد.\nلطفا منتظر تایید باشید.",
            reply_markup=get_main_keyboard()
        )
        
        if user_id in user_states:
            del user_states[user_id]
        return
    
    # بخش خرید اشتراک
    elif text == "💳 خرید اشتراک":
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text(
            "💳 پلن را انتخاب کنید:",
            reply_markup=get_subscription_keyboard(is_agent)
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
            f"💎 پلن انتخاب شده: {text}\n💰 قیمت: {amount:,} تومان\n\n💳 روش پرداخت را انتخاب کنید:",
            reply_markup=get_payment_method_keyboard()
        )
        return
    
    elif user_states.get(user_id, "").startswith("awaiting_payment_method_"):
        parts = user_states[user_id].split("_")
        amount = int(parts[3])
        plan = "_".join(parts[4:])
        
        if text == "🏦 کارت به کارت":
            payment_id = await add_payment(user_id, amount, "buy_subscription", "card_to_card", description=plan)
            
            if payment_id:
                await add_subscription(user_id, payment_id, plan)
                
                await update.message.reply_text(
                    f"💳 درخواست خرید اشتراک\n\n"
                    f"🎯 پلن: {plan}\n"
                    f"💰 مبلغ: {amount:,} تومان\n"
                    f"🆔 کد خرید: #{payment_id}\n\n"
                    f"لطفا مبلغ را واریز کنید:\n\n"
                    f"🏦 کارت به کارت:\n{BANK_CARD}\n"
                    f"✍️ به نام: فرهنگ\n\n"
                    f"⚠️ پس از واریز، فیش را ارسال کنید.",
                    reply_markup=get_back_keyboard()
                )
                user_states[user_id] = f"awaiting_subscription_receipt_{payment_id}"
            else:
                await update.message.reply_text("⚠️ خطا در ثبت درخواست.", reply_markup=get_main_keyboard())
                if user_id in user_states:
                    del user_states[user_id]
            return
        
        elif text == "💎 پرداخت با ترون":
            payment_id = await add_payment(user_id, amount, "buy_subscription", "tron", description=plan)
            
            if payment_id:
                await add_subscription(user_id, payment_id, plan)
                
                await update.message.reply_text(
                    f"💎 درخواست خرید اشتراک\n\n"
                    f"🎯 پلن: {plan}\n"
                    f"💰 مبلغ: {amount:,} تومان\n"
                    f"🆔 کد خرید: #{payment_id}\n\n"
                    f"لطفا مبلغ را واریز کنید:\n\n"
                    f"💎 آدرس ترون:\n{TRON_ADDRESS}\n\n"
                    f"⚠️ پس از واریز، فیش را ارسال کنید.",
                    reply_markup=get_back_keyboard()
                )
                user_states[user_id] = f"awaiting_subscription_receipt_{payment_id}"
            else:
                await update.message.reply_text("⚠️ خطا در ثبت درخواست.", reply_markup=get_main_keyboard())
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
                        f"✅ خرید شما موفقیت‌آمیز بود!\n\n"
                        f"🎯 پلن: {plan}\n"
                        f"💰 مبلغ: {amount:,} تومان\n"
                        f"🆔 کد خرید: #{payment_id}\n\n"
                        f"اشتراک شما فعال شد.",
                        reply_markup=get_main_keyboard()
                    )
                    
                    # اطلاع به ادمین
                    await context.bot.send_message(
                        ADMIN_ID,
                        f"🛒 خرید با موجودی\n👤 کاربر: {user_id}\n🎯 پلن: {plan}\n💰 مبلغ: {amount:,}\n🆔 کد: #{payment_id}"
                    )
                else:
                    await update.message.reply_text("⚠️ خطا در ثبت خرید.", reply_markup=get_main_keyboard())
            else:
                await update.message.reply_text(
                    f"⚠️ موجودی کافی نیست!\n💰 موجودی شما: {balance:,} تومان\n💰 مورد نیاز: {amount:,} تومان",
                    reply_markup=get_main_keyboard()
                )
            
            if user_id in user_states:
                del user_states[user_id]
            return
    
    # سایر بخش‌ها
    elif text == "🎁 اشتراک تست رایگان":
        await update.message.reply_text(
            "🎁 برای دریافت اشتراک تست رایگان، لطفا با پشتیبانی تماس بگیرید:\n👨‍💼 @teazadmin",
            reply_markup=get_main_keyboard()
        )
        return
    
    elif text == "☎️ پشتیبانی":
        await update.message.reply_text(
            "📞 پشتیبانی:\n👨‍💼 ادمین: @teazadmin\n⏰ ۲۴ ساعته",
            reply_markup=get_main_keyboard()
        )
        return
    
    elif text == "💵 اعتبار رایگان":
        invite_link = f"https://t.me/teazvpn_bot?start={user_id}"
        await update.message.reply_text(
            f"💎 کسب اعتبار رایگان\n\n"
            f"🔗 لینک دعوت شما:\n{invite_link}\n\n"
            f"📊 سیستم پاداش:\n"
            f"• هر دعوت موفق: ۱۰,۰۰۰ تومان\n"
            f"• دعوت شده باید اشتراک بخرد\n"
            f"• اعتبار بلافاصله واریز می‌شود",
            reply_markup=get_main_keyboard()
        )
        return
    
    elif text == "📂 اشتراک‌های من":
        # نسخه ساده
        await update.message.reply_text(
            "📭 شما هیچ اشتراک فعالی ندارید.\nبرای خرید اشتراک از منوی اصلی استفاده کنید.",
            reply_markup=get_main_keyboard()
        )
        return
    
    elif text == "💡 راهنمای اتصال":
        await update.message.reply_text(
            "📚 راهنمای اتصال\n\n"
            "📱 اندروید: V2RayNG\n"
            "🍎 آیفون: Singbox\n"
            "💻 ویندوز: V2rayN\n"
            "🐧 لینوکس: V2rayA",
            reply_markup=get_main_keyboard()
        )
        return
    
    elif text == "🧑‍💼 درخواست نمایندگی":
        await update.message.reply_text(
            "🚀 اعطای نمایندگی\n\n"
            "💰 هزینه: ۱,۰۰۰,۰۰۰ تومان\n"
            "✅ مزایا:\n"
            "• خرید با قیمت نماینده\n"
            "• پنل اختصاصی\n"
            "• درآمدزایی\n\n"
            "برای اطلاعات بیشتر با پشتیبانی تماس بگیرید.",
            reply_markup=get_main_keyboard()
        )
        return
    
    # اگر هیچکدام از شرایط بالا برقرار نبود
    await update.message.reply_text(
        "⚠️ دستور نامعتبر است!\nلطفا از دکمه‌های کیبورد استفاده کنید.",
        reply_markup=get_main_keyboard()
    )
    
    if user_id in user_states:
        del user_states[user_id]

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر کال‌بک‌ها"""
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data
    
    await query.answer()
    
    # فقط ادمین
    if user_id != ADMIN_ID:
        await query.edit_message_text("⚠️ شما مجاز نیستید.")
        return
    
    try:
        # تأیید پرداخت
        if data.startswith("approve_"):
            payment_id = int(data.split("_")[-1])
            
            await update_payment_status(payment_id, "approved")
            
            # پیدا کردن کاربر
            result = await db_execute(
                "SELECT user_id, amount, type FROM payments WHERE id = %s",
                (payment_id,), fetchone=True
            )
            
            if result:
                buyer_id, amount, ptype = result
                
                if ptype == "increase_balance":
                    await add_balance(buyer_id, amount)
                    await context.bot.send_message(
                        buyer_id,
                        f"✅ پرداخت شما تایید شد!\n💰 {amount:,} تومان به موجودی شما اضافه شد."
                    )
                
                elif ptype == "buy_subscription":
                    await context.bot.send_message(
                        buyer_id,
                        f"✅ پرداخت شما تایید شد!\n🎯 اشتراک شما فعال شد.\n🆔 کد خرید: #{payment_id}"
                    )
            
            await query.edit_message_text(f"✅ پرداخت #{payment_id} تایید شد.")
            return
        
        # رد پرداخت
        elif data.startswith("reject_"):
            payment_id = int(data.split("_")[-1])
            
            await update_payment_status(payment_id, "rejected")
            
            await query.edit_message_text(f"❌ پرداخت #{payment_id} رد شد.")
            return
    
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await query.edit_message_text(f"⚠️ خطا: {str(e)}")

# ---------- ثبت هندلرها ----------
application.add_handler(CommandHandler("start", start_with_param))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, message_handler))

# ---------- وب‌هوک ----------
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """هندلر وب‌هوک"""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}

# ---------- راه‌اندازی ----------
@app.on_event("startup")
async def startup():
    """رویداد راه‌اندازی"""
    try:
        logger.info("🚀 Starting Teaz VPN Bot...")
        
        # راه‌اندازی دیتابیس
        init_db_pool()
        
        # ساخت جداول
        await create_tables()
        
        # راه‌اندازی بات
        await application.initialize()
        await application.start()
        
        # تنظیم وب‌هوک
        if WEBHOOK_URL:
            await application.bot.set_webhook(WEBHOOK_URL)
            logger.info(f"✅ Webhook set: {WEBHOOK_URL}")
        else:
            logger.warning("⚠️ WEBHOOK_URL not set")
        
        # اطلاع به ادمین
        try:
            await application.bot.send_message(
                ADMIN_ID,
                f"🤖 ربات تیز VPN راه‌اندازی شد!\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"🌐 حالت: {'Memory DB' if USE_MEMORY_DB else 'PostgreSQL'}"
            )
        except:
            pass
        
        logger.info("✅ Bot started successfully!")
        
    except Exception as e:
        logger.error(f"❌ Startup error: {e}")

@app.on_event("shutdown")
async def shutdown():
    """رویداد خاموش‌سازی"""
    try:
        logger.info("🛑 Shutting down bot...")
        await application.stop()
        await application.shutdown()
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
