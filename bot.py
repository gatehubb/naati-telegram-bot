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
from datetime import datetime

# سازگاری با نسخه‌های مختلف پایتون جهت مدیریت منطقه زمانی
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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# کلیدهای محیطی
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8708901411:AAEg1MJrXj4t8zs_KOuYwHMfAW1kZemQTew")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "2377451")

# ایجاد برنامه Flask جهت بیدار نگه داشتن سرویس
app = Flask(__name__)

@app.route('/')
def home():
    return "NAATI Checker Bot is running live!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ایجاد دیتابیس و جدول پایش‌ها و خطاها
DB_FILE = "naati_monitor.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monitors (
            chat_id INTEGER PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_tracker (
            chat_id INTEGER PRIMARY KEY,
            error_count INTEGER DEFAULT 0,
            first_error_time REAL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

init_db()

# توابع مدیریت دیتابیس
def add_monitor(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO monitors (chat_id) VALUES (?)", (chat_id,))
    cursor.execute("INSERT OR REPLACE INTO error_tracker (chat_id, error_count, first_error_time) VALUES (?, 0, 0)", (chat_id,))
    conn.commit()
    conn.close()

def remove_monitor(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM monitors WHERE chat_id = ?", (chat_id,))
    cursor.execute("DELETE FROM error_tracker WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

def get_all_monitors():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT chat_id FROM monitors")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def record_error_and_check_cancel(chat_id):
    """
    بررسی و ثبت خطاهای متوالی در بازه ۱ ساعته
    در صورت رسیدن به ۵ خطا، True برمی‌گرداند تا پایش لغو شود.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT error_count, first_error_time FROM error_tracker WHERE chat_id = ?", (chat_id,))
    row = cursor.fetchone()
    
    current_time = time.time()
    if not row or row[1] == 0 or (current_time - row[1] > 3600):
        # اگر اولین خطا است یا بیش از ۱ ساعت گذشته، شمارنده بازنشانی می‌شود
        new_count = 1
        first_time = current_time
    else:
        new_count = row[0] + 1
        first_time = row[1]

    if new_count >= 5:
        # لغو پایش و پاکسازی خطاهایش
        cursor.execute("DELETE FROM monitors WHERE chat_id = ?", (chat_id,))
        cursor.execute("DELETE FROM error_tracker WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        return True
    else:
        cursor.execute("INSERT OR REPLACE INTO error_tracker (chat_id, error_count, first_error_time) VALUES (?, ?, ?)",
                       (chat_id, new_count, first_time))
        conn.commit()
        conn.close()
        return False

def reset_error_tracker(chat_id):
    """بازنشانی شمارنده خطا در صورت اجرای موفق پایش"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE error_tracker SET error_count = 0, first_error_time = 0 WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()

# تابع تبدیل تاریخ میلادی به شمسی
def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = (gy + 3) if gy > 0 else (gy + 4)
    days = (365 * gy) + ((gy2) // 4) - ((gy2) // 100) + ((gy2) // 400) + gd + g_d_m[gm - 1]
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        days += 1
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd

def convert_date_string(date_str):
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
        months = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
        return f"{jd} {months[jm-1]} {jy}"
    except Exception:
        return date_str

# تابع اصلی استخراج تاریخ‌ها با Playwright
async def fetch_naati_dates():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("https://cclpratice.com/ccl-test-date", timeout=60000)
            
            # منتظر فعال شدن المنت انتخاب زبان می‌مانیم تا خطای Timeout صادر نشود
            await page.wait_for_selector("select#language-test-date:not([disabled])", timeout=15000)
            await page.select_option("select#language-test-date", value="Persian")
            
            await page.wait_for_timeout(3000)
            
            # استخراج محتوای جدول
            rows = await page.query_selector_all("table tr")
            results = []
            for row in rows:
                text = await row.inner_text()
                if text and "Persian" in text:
                    results.append(text.strip())
            return results
        finally:
            await browser.close()

# دستور start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 استخراج و انتخاب تاریخ از NAATI", callback_data="fetch_dates")],
        [InlineKeyboardButton("🔔 فعال‌سازی پایش خودکار", callback_data="enable_monitor"),
         InlineKeyboardButton("🔕 لغو پایش خودکار", callback_data="disable_monitor")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! به دستیار هوشمند پایش آزمون NAATI CCL خوش آمدید.\nلطفاً گزینه مورد نظر خود را انتخاب کنید:",
        reply_markup=reply_markup
    )

# مدیریت دکمه‌های شیشه‌ای
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "fetch_dates":
        await query.edit_message_text("⏳ در حال استخراج زنده تاریخ‌های آزمون از NAATI...")
        try:
            dates = await fetch_naati_dates()
            reset_error_tracker(chat_id)
            if dates:
                formatted_dates = "\n".join([f"• {convert_date_string(d)}" for d in dates])
                await query.edit_message_text(f"✅ تاریخ‌های موجود آزمون NAATI:\n\n{formatted_dates}")
            else:
                await query.edit_message_text("❌ در حال حاضر هیچ تاریخی برای زبان فارسی یافت نشد.")
        except Exception as e:
            error_msg = str(e)
            if "Timeout" in error_msg and "language-test-date" in error_msg:
                should_cancel = record_error_and_check_cancel(chat_id)
                if should_cancel:
                    keyboard = [[InlineKeyboardButton("🔄 فعال‌سازی مجدد پایش", callback_data="enable_monitor")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.edit_message_text(
                        "⚠️ به علت بروز ۵ بار خطای متوالی در ارتباط با سایت NAATI در یک ساعت گذشته، پایش خودکار شما کنسل شد.\n"
                        "جهت ادامه باید مجدداً پایش را فعال کنید.",
                        reply_markup=reply_markup
                    )
                    return
            await query.edit_message_text(f"❌ خطا در استخراج اطلاعات: {e}")

    elif query.data == "enable_monitor":
        add_monitor(chat_id)
        keyboard = [[InlineKeyboardButton("🔕 لغو پایش خودکار", callback_data="disable_monitor")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("✅ پایش خودکار هر ۵ دقیقه یک‌بار فعال شد.", reply_markup=reply_markup)

    elif query.data == "disable_monitor":
        remove_monitor(chat_id)
        await query.edit_message_text("🔕 پایش خودکار با موفقیت غیرفعال شد.")

# جاب پایش دوره‌ای (هر ۵ دقیقه)
async def auto_monitor_job(context: ContextTypes.DEFAULT_TYPE):
    monitors = get_all_monitors()
    if not monitors:
        return

    try:
        dates = await fetch_naati_dates()
        for chat_id in monitors:
            reset_error_tracker(chat_id)
            if dates:
                formatted_dates = "\n".join([f"• {convert_date_string(d)}" for d in dates])
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔔 **بروزرسانی جدید تاریخ‌های NAATI:**\n\n{formatted_dates}",
                    parse_mode="Markdown"
                )
    except Exception as e:
        error_msg = str(e)
        if "Timeout" in error_msg and "language-test-date" in error_msg:
            for chat_id in monitors:
                should_cancel = record_error_and_check_cancel(chat_id)
                if should_cancel:
                    keyboard = [[InlineKeyboardButton("🔄 فعال‌سازی مجدد پایش", callback_data="enable_monitor")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    try:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text="⚠️ **پایش خودکار کنسل شد**\n\nبه علت بروز ۵ بار خطای متوالی در دریافت اطلاعات از سایت NAATI در یک ساعت گذشته، پایش شما متوقف گردید.\nدر صورت تمایل می‌توانید مجدداً آن را فعال کنید.",
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

def main():
    # اجرای Flask در Thread جداگانه
    threading.Thread(target=run_flask, daemon=True).start()

    # ساخت Application تلگرام
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    # افزودن Job برای پایش ۵ دقیقه‌ای
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(auto_monitor_job, interval=300, first=10)

    application.run_polling()

if __name__ == "__main__":
    main()
