import asyncio
import logging
import os
import re
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta

from flask import Flask
from playwright.async_api import async_playwright
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ==================== تنظیمات LOGGING ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== کلیدها و ثابت‌ها ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8708901411:AAFMxrPf-imYHkuHhKA4Mg5ss-WrTQ78f_I")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "2377451")
DB_NAME = "naati_bot.db"

# ==================== SERVER جهت زنده نگه داشتن RENDER ====================
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "NAATI Monitor Bot is Online", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ==================== تبدیل تاریخ میلادی به شمسی ====================
def gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = (gy + 1) if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + g_d_m[gm - 1] + gd - 1
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

def parse_and_format_date(date_str):
    try:
        clean_str = re.sub(r'[^\w\s]', '', date_str).strip()
        dt = datetime.strptime(clean_str, "%d %B %Y")
        jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
        
        days_left = (dt.date() - datetime.now().date()).days
        days_left_str = f"{days_left} روز دیگر" if days_left >= 0 else "گذشته"
        
        months_fa = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
        shamsi_str = f"{jd} {months_fa[jm-1]} {jy}"
        
        return f"📅 {date_str} ({shamsi_str}) - ⏳ {days_left_str}"
    except Exception:
        return f"📅 {date_str}"

# ==================== مدیریت پایگاه داده ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS active_monitors (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER,
            selected_dates TEXT,
            interval INTEGER DEFAULT 300,
            last_run TIMESTAMP,
            consecutive_errors INTEGER DEFAULT 0,
            first_error_time TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

def add_or_update_monitor(user_id, chat_id, selected_dates):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    dates_str = ",".join(selected_dates)
    cursor.execute("""
        INSERT OR REPLACE INTO active_monitors 
        (user_id, chat_id, selected_dates, interval, last_run, consecutive_errors, first_error_time) 
        VALUES (?, ?, ?, 300, ?, 0, NULL)
    """, (user_id, chat_id, dates_str, datetime.now().isoformat()))
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
    cursor.execute("SELECT user_id, chat_id, selected_dates, consecutive_errors, first_error_time FROM active_monitors")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_error_status(user_id, has_error):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    
    if not has_error:
        cursor.execute("UPDATE active_monitors SET consecutive_errors = 0, first_error_time = NULL WHERE user_id = ?", (user_id,))
    else:
        cursor.execute("SELECT consecutive_errors, first_error_time FROM active_monitors WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            c_errors, f_time = row
            c_errors += 1
            if not f_time:
                f_time = now_str
            cursor.execute("UPDATE active_monitors SET consecutive_errors = ?, first_error_time = ? WHERE user_id = ?", (c_errors, f_time, user_id))
            
    conn.commit()
    conn.close()

def simplify_error(error_str: str) -> str:
    if "language-test-date" in error_str or "select_option" in error_str:
        return "ERR_TIMEOUT_LANG_DISABLED (عدم پاسخگویی منوی انتخاب زبان)"
    elif "Timeout" in error_str:
        return "ERR_SITE_TIMEOUT (کندی در پاسخگویی سرور NAATI)"
    elif "net::ERR_" in error_str:
        return "ERR_NETWORK_DISCONNECTED (خطای اتصال شبکه)"
    else:
        first_line = error_str.split("\n")[0]
        return f"ERR_UNKNOWN ({first_line[:50]}...)"

# ==================== بررسی و نصب خودکار کرومیوم ====================
def ensure_chromium_installed():
    try:
        subprocess.run(["playwright", "install", "chromium"], check=True)
    except Exception as e:
        logger.error(f"Failed to auto-install chromium: {e}")

# ==================== اسکرپر با قابلیت نمایش لایو مراحل ====================
async def scrape_naati_dates(status_update_fn=None):
    base_text = "⏳ **در حال اتصال به سایت NAATI و استخراج آخرین تاریخ‌های فعال...**\n**لطفاً شکیبا باشید.**\n\n"
    
    steps = [
        "ورود به سامانه NAATI",
        "در حال بارگذاری منوی انتخاب زبان",
        "اعمال فیلتر زبان فارسی (Persian)",
        "استخراج و پردازش مقادیر ظرفیت"
    ]
    
    async def update_step(step_index):
        if not status_update_fn:
            return
        progress_text = base_text
        for idx, step_name in enumerate(steps):
            if idx < step_index:
                progress_text += f"✅ {step_name}\n"
            elif idx == step_index:
                progress_text += f"⏳ {step_name}...\n"
            else:
                progress_text += f"⚪ {step_name}\n"
        try:
            await status_update_fn(progress_text)
        except Exception as e:
            logger.error(f"Status update error: {e}")

    # اطمینان از وجود داشتن مرورگر
    ensure_chromium_installed()

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
        except Exception as launch_err:
            logger.error(f"Browser launch failed, attempting reinstall: {launch_err}")
            ensure_chromium_installed()
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )

        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = await context.new_page()
        
        try:
            await update_step(0)
            await page.goto("https://cclpanel.com/test-date-checker/", timeout=40000, wait_until="domcontentloaded")
            
            await update_step(1)
            select_locator = page.locator("#language-test-date")
            await select_locator.wait_for(state="attached", timeout=15000)
            
            for _ in range(10):
                if not await select_locator.is_disabled():
                    break
                await asyncio.sleep(1)
                
            await update_step(2)
            await select_locator.select_option(value="Persian", timeout=10000)
            await page.wait_for_selector(".test-date-item, .no-dates-message, #results-container", timeout=15000)
            
            await update_step(3)
            items = await page.query_selector_all(".test-date-item")
            extracted_dates = []
            
            if items:
                for item in items:
                    txt = await item.inner_text()
                    txt_clean = txt.strip()
                    if txt_clean:
                        extracted_dates.append(txt_clean)
            else:
                all_text = await page.inner_text("#results-container")
                lines = [line.strip() for line in all_text.split("\n") if line.strip()]
                extracted_dates = [l for l in lines if "No test dates" not in l]
            
            if status_update_fn:
                final_progress = base_text + "\n".join([f"✅ {s}" for s in steps])
                try:
                    await status_update_fn(final_progress)
                except Exception:
                    pass
            
            await browser.close()
            return True, extracted_dates, None
            
        except Exception as e:
            await browser.close()
            return False, [], simplify_error(str(e))

# ==================== دستورات ربات تلگرام ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 **دستیار هوشمند پایش آزمون NAATI CCL**\n\n"
        "به ربات پایش لحظه‌ای ظرفیت آزمون‌های NAATI خوش آمدید.\n\n"
        "**امکانات ربات:**\n"
        "• دریافت زنده تاریخ‌های فعال آزمون فارسی\n"
        "• پایش تک یک تاریخ خاص همراه با اعلام تاریخ‌های جدید\n"
        "• پایش همزمان چندین تاریخ (تا ۴ تاریخ)\n"
        "• پایش اتوماتیک هر ۵ دقیقه یک‌بار و ارسال آنی هشدار تغییر ظرفیت\n\n"
        "جهت شروع، روی دکمه استخراج و انتخاب تاریخ کلیک کنید:"
    )
    
    keyboard = [
        [InlineKeyboardButton("⚪ استخراج و انتخاب تاریخ از NAATI", callback_data="fetch_dates")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if query.data == "fetch_dates":
        initial_msg = (
            "⏳ **در حال اتصال به سایت NAATI و استخراج آخرین تاریخ‌های فعال...**\n"
            "**لطفاً شکیبا باشید.**\n\n"
            "⚪ ورود به سامانه NAATI\n"
            "⚪ در حال بارگذاری منوی انتخاب زبان\n"
            "⚪ اعمال فیلتر زبان فارسی (Persian)\n"
            "⚪ استخراج و پردازش مقادیر ظرفیت"
        )
        await query.edit_message_text(initial_msg, parse_mode="Markdown")

        async def update_status_text(new_text):
            try:
                await query.edit_message_text(new_text, parse_mode="Markdown")
            except Exception:
                pass

        success, dates, error_msg = await scrape_naati_dates(status_update_fn=update_status_text)
        
        if not success:
            keyboard = [[InlineKeyboardButton("🔄 تلاش مجدد", callback_data="fetch_dates")]]
            await query.edit_message_text(
                f"❌ **خطا در دریافت اطلاعات:**\n`{error_msg}`\n\nلطفاً چند لحظه بعد مجدداً تلاش کنید.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        if not dates:
            keyboard = [[InlineKeyboardButton("🔄 بروزرسانی مجدد", callback_data="fetch_dates")]]
            await query.edit_message_text(
                "⚠️ **در حال حاضر هیچ تاریخ آزمون فعالی برای زبان فارسی ثبت نشده است.**",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

        context.user_data["extracted_dates"] = dates
        context.user_data["selected_indices"] = []

        msg = "📋 **تاریخ‌های فعال یافت شده:**\n\n"
        keyboard = []
        for idx, d in enumerate(dates):
            formatted_date = parse_and_format_date(d)
            msg += f"{idx + 1}. {formatted_date}\n"
            keyboard.append([InlineKeyboardButton(f"پایش تاریخ {idx + 1}", callback_data=f"toggle_date_{idx}")])

        keyboard.append([InlineKeyboardButton("🚀 پایش همه تاریخ‌ها", callback_data="monitor_all")])
        keyboard.append([InlineKeyboardButton("❌ لغو پایش‌های فعال", callback_data="stop_monitor")])

        await query.edit_message_text(
            msg + "\n👇 جهت انتخاب تاریخ برای پایش خودکار، دکمه مورد نظر را لمس کنید:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif query.data.startswith("toggle_date_"):
        idx = int(query.data.split("_")[2])
        extracted = context.user_data.get("extracted_dates", [])
        
        if idx < len(extracted):
            selected = context.user_data.get("selected_indices", [])
            
            if idx in selected:
                selected.remove(idx)
            else:
                if len(selected) >= 4:
                    await query.answer("⚠️ حداکثر می‌توانید ۴ تاریخ را همزمان انتخاب کنید.", show_alert=True)
                    return
                selected.append(idx)
            
            context.user_data["selected_indices"] = selected
            
            if selected:
                chosen_dates = [extracted[i] for i in selected]
                add_or_update_monitor(user_id, chat_id, chosen_dates)
                await query.answer(f"✅ پایش برای {len(chosen_dates)} تاریخ فعال شد.", show_alert=True)
            else:
                remove_monitor(user_id)
                await query.answer("❌ پایش غیرفعال شد.", show_alert=True)

    elif query.data == "monitor_all":
        extracted = context.user_data.get("extracted_dates", [])
        if extracted:
            chosen_dates = extracted[:4]
            add_or_update_monitor(user_id, chat_id, chosen_dates)
            await query.edit_message_text(
                f"✅ **پایش خودکار با موفقیت فعال شد. ربات هر ۵ دقیقه وضعیت سایت را بررسی می‌کند.**\n\nتاریخ‌های تحت پایش:\n" +
                "\n".join([parse_and_format_date(d) for d in chosen_dates]),
                parse_mode="Markdown"
            )

    elif query.data == "stop_monitor":
        remove_monitor(user_id)
        await query.edit_message_text("❌ **پایش خودکار شما غیرفعال شد.**")

# ==================== پنل مدیریت ادمین ====================
async def admin_cancel_monitors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args or args[0] != ADMIN_PASSWORD:
        await update.message.reply_text("⛔ رمز عبور مدیریت اشتباه است.")
        return

    monitors = get_all_monitors()
    if not monitors:
        await update.message.reply_text("هیچ پایش فعالی در دیتابیس وجود ندارد.")
        return

    if len(args) == 1:
        msg = "📋 **لیست پایش‌های فعال جهت مدیریت:**\n\n"
        for m in monitors:
            msg += f"👤 کاربر: `{m[0]}` | تاریخ‌ها: {m[2]} | خطاها: {m[3]}\n"
        msg += f"\nبرای لغو یک پایش دستور زیر را وارد کنید:\n`/admin_cancel_monitors {ADMIN_PASSWORD} <USER_ID>`"
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        target_user = int(args[1])
        remove_monitor(target_user)
        await update.message.reply_text(f"✅ پایش کاربر `{target_user}` لغو گردید.", parse_mode="Markdown")

# ==================== موتور پایش زمان‌بندی‌شده ====================
async def monitor_job(context: ContextTypes.DEFAULT_TYPE):
    monitors = get_all_monitors()
    if not monitors:
        return

    for user_id, chat_id, selected_dates_str, consecutive_errors, first_error_time in monitors:
        success, current_dates, error_msg = await scrape_naati_dates()
        
        if success:
            update_error_status(user_id, has_error=False)
            monitored_list = selected_dates_str.split(",") if selected_dates_str else []
            
            new_found = [d for d in current_dates if d not in monitored_list]
            if new_found:
                msg = "🔔 **هشدار! تاریخ‌های جدید در آزمون NAATI یافت شد:**\n\n"
                for d in new_found:
                    msg += f"{parse_and_format_date(d)}\n"
                
                try:
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to send alert to {chat_id}: {e}")
        else:
            update_error_status(user_id, has_error=True)
            logger.warning(f"Error checking NAATI for user {user_id}: {error_msg}")
            
            if first_error_time:
                first_err_dt = datetime.fromisoformat(first_error_time)
                if datetime.now() - first_err_dt >= timedelta(hours=1):
                    remove_monitor(user_id)
                    cancel_msg = (
                        f"⚠️ **توقف اتوماتیک پایش!**\n\n"
                        f"به دلیل بروز خطاهای مداوم در اتصال به سرور طی ۱ ساعت گذشته، پایش شما متوقف گردید.\n"
                        f"❌ `کد خطا: {error_msg}`\n\n"
                        f"لطفاً مجدداً از طریق دستور /start پایش را فعال کنید."
                    )
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=cancel_msg, parse_mode="Markdown")
                    except Exception as e:
                        logger.error(f"Failed to send cancellation notice to {chat_id}: {e}")

# ==================== شروع اجرای ربات ====================
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin_cancel_monitors", admin_cancel_monitors))
    application.add_handler(CallbackQueryHandler(button_handler))

    if application.job_queue:
        application.job_queue.run_repeating(monitor_job, interval=300, first=10)

    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
