import asyncio
import html
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

# سازگاری کامل zoneinfo
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from flask import Flask
from playwright.async_api import async_playwright
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# تنظیمات Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# کلیدهای محیطی
BOT_TOKEN = os.getenv("BOT_TOKEN", "8708901411:AAEg1MJrXj4t8zs_KOuYwHMfAW1kZemQTew")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "2377451")
DB_NAME = "naati_bot.db"

# راه‌اندازی سرور Flask جهت زنده نگه داشتن Render
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "NAATI Monitor Bot is Active", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ==================== دیتابیس ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_monitors (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            interval INTEGER,
            last_run TIMESTAMP,
            consecutive_errors INTEGER DEFAULT 0,
            first_error_time TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def add_monitor(user_id, chat_id, interval=300):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO active_monitors 
        (user_id, chat_id, interval, last_run, consecutive_errors, first_error_time) 
        VALUES (?, ?, ?, ?, 0, NULL)
    """, (user_id, chat_id, interval, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def remove_monitor(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM active_monitors WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_all_monitors():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, chat_id, interval, consecutive_errors, first_error_time FROM active_monitors")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_monitor_error_status(user_id, has_error):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    
    if not has_error:
        cursor.execute("""
            UPDATE active_monitors 
            SET consecutive_errors = 0, first_error_time = NULL 
            WHERE user_id = ?
        """, (user_id,))
    else:
        cursor.execute("SELECT consecutive_errors, first_error_time FROM active_monitors WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            c_errors, f_time = row
            c_errors += 1
            if not f_time:
                f_time = now_str
            cursor.execute("""
                UPDATE active_monitors 
                SET consecutive_errors = ?, first_error_time = ? 
                WHERE user_id = ?
            """, (c_errors, f_time, user_id))
            
    conn.commit()
    conn.close()

# ==================== مدیریت خطاهای هوشمند ====================
def simplify_error_message(error_str: str) -> str:
    """تبدیل خطاهای طولانی Playwright به نام‌های کوتاه و خوانا"""
    if "language-test-date" in error_str or "select_option" in error_str:
        return "ERR_TIMEOUT_LANG_DISABLED (عدم پاسخگویی منوی انتخاب زبان سایت NAATI)"
    elif "Timeout" in error_str:
        return "ERR_SITE_TIMEOUT (کندی یا عدم پاسخگویی سرور NAATI)"
    elif "net::ERR_" in error_str:
        return "ERR_NETWORK_CONNECTION (اختلال در اتصال شبکه به سایت NAATI)"
    else:
        first_line = error_str.split("\n")[0]
        return f"ERR_UNKNOWN ({first_line[:80]}...)"

# ==================== وب اسکرپینگ (Playwright) ====================
async def scrape_naati_dates():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = await context.new_page()
        
        try:
            await page.goto("https://cclpanel.com/test-date-checker/", timeout=60000)
            
            select_locator = page.locator("#language-test-date")
            await select_locator.wait_for(state="attached", timeout=30000)
            
            for _ in range(15):
                is_disabled = await select_locator.is_disabled()
                if not is_disabled:
                    break
                await asyncio.sleep(1)
                
            await select_locator.select_option(value="Persian", timeout=15000)
            await page.wait_for_selector(".test-date-item, .no-dates-message, #results-container", timeout=20000)
            
            content = await page.content()
            await browser.close()
            return True, content, None
            
        except Exception as e:
            await browser.close()
            simplified_err = simplify_error_message(str(e))
            return False, None, simplified_err

# ==================== دستورات تلگرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔍 استخراج و پایش تاریخ‌های جدید", callback_data="start_monitor")],
        [InlineKeyboardButton("⛔ لغو پایش فعال", callback_data="stop_monitor")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! به دستیار هوشمند پایش آزمون NAATI CCL خوش آمدید.\nلطفاً گزینه مورد نظر خود را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if query.data == "start_monitor":
        add_monitor(user_id, chat_id)
        await query.edit_message_text("✅ پایش خودکار با موفقیت فعال شد. ربات هر ۵ دقیقه وضعیت سایت را بررسی می‌کند.")
    elif query.data == "stop_monitor":
        remove_monitor(user_id)
        await query.edit_message_text("❌ پایش خودکار شما غیرفعال شد.")

# ==================== پنل مدیریت ادمین ====================
async def admin_cancel_monitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if not args or args[0] != ADMIN_PASSWORD:
        await update.message.reply_text("⛔ رمز عبور ادمین اشتباه است.")
        return

    monitors = get_all_monitors()
    if not monitors:
        await update.message.reply_text("هیچ پایش فعالی در سیستم ثبت نشده است.")
        return

    if len(args) == 1:
        msg = "📋 **لیست پایش‌های فعال:**\n\n"
        for m in monitors:
            msg += f"👤 User ID: `{m[0]}` | خطاها: {m[3]}\n"
        msg += "\nبرای لغو یک پایش مشخص، دستور زیر را بزنید:\n"
        msg += f"`/admin_cancel_monitors {ADMIN_PASSWORD} <USER_ID>`"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        target_user_id = int(args[1])
        remove_monitor(target_user_id)
        await update.message.reply_text(f"✅ پایش کاربر `{target_user_id}` با موفقیت لغو شد.", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_user_id, text="⚠️ پایش خودکار شما توسط مدیریت سیستم متوقف شد.")
        except Exception:
            pass

# ==================== پردازشگر پایش زمان‌بندی‌شده ====================
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    monitors = get_all_monitors()
    if not monitors:
        return

    for user_id, chat_id, interval, consecutive_errors, first_error_time in monitors:
        success, content, error_name = await scrape_naati_dates()
        
        if success:
            update_monitor_error_status(user_id, has_error=False)
        else:
            update_monitor_error_status(user_id, has_error=True)
            logger.warning(f"Error monitoring for user {user_id}: {error_name}")
            
            if first_error_time:
                first_err_dt = datetime.fromisoformat(first_error_time)
                if datetime.now() - first_err_dt >= timedelta(hours=1):
                    remove_monitor(user_id)
                    cancel_msg = (
                        f"⚠️ **پایش خودکار متوقف شد!**\n\n"
                        f"به دلیل بروز خطای مداوم زیر در طول ۱ ساعت گذشته، روند پایش لغو گردید:\n"
                        f"❌ `کد خطا: {error_name}`\n\n"
                        f"لطفاً مجدداً از طریق دستور /start پایش را فعال کنید."
                    )
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=cancel_msg, parse_mode="Markdown")
                    except Exception as e:
                        logger.error(f"Failed to send cancellation message to {chat_id}: {e}")

# ==================== اصلی ====================
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin_cancel_monitors", admin_cancel_monitors))
    application.add_handler(CallbackQueryHandler(button_handler))

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(monitor_job, interval=300, first=10)

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
