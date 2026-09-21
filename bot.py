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
from zoneinfo import ZoneInfo

from flask import Flask
from playwright.async_api import async_playwright
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ==================== تنظیمات لاگینگ ====================
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ==================== تنظیمات متغیرهای محیطی ====================
TELEGRAM_TOKEN = os.environ.get(
    "BOT_TOKEN", "8708901411:AAFMxrPf-imYHkuHhKA4Mg5ss-WrTQ78f_I"
).strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "2377451").strip()

DB_PATH = "monitors.db"
USER_TEMP_SELECTIONS = {}

# متن استاندارد منوی اصلی
MAIN_MENU_TEXT = (
    "🤖 <b>دستیار هوشمند پایش آزمون NAATI CCL</b>\n\n"
    "<b>امکانات ربات:</b>\n"
    "• دریافت زنده تاریخ‌های فعال آزمون فارسی\n"
    "• پایش یک تاریخ خاص همراه با اعلام تاریخ‌های جدید\n"
    "• پایش همزمان چندین تاریخ (تا ۴ تاریخ)\n"
    "• پایش اتوماتیک و ارسال آنی هشدار تغییر ظرفیت\n\n"
    "جهت شروع، روی دکمه استخراج و انتخاب تاریخ کلیک کنید:"
)


# ==================== توابع تبدیل زمان و تاریخ شمسی ====================
def gregorian_to_jalali(gy, gm, gd):
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]

    gy2 = gy - 1600 if gy > 1600 else gy - 621
    gm2 = gm - 1
    gd2 = gd - 1

    g_day_no = (
        365 * gy2
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
    )
    for i in range(gm2):
        g_day_no += g_days_in_month[i]
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        g_day_no += 1
    g_day_no += gd2

    j_day_no = g_day_no - 79

    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    for i in range(12):
        if j_day_no < j_days_in_month[i]:
            jm = i + 1
            jd = j_day_no + 1
            break
        j_day_no -= j_days_in_month[i]

    return jy, jm, jd


PERSIAN_WEEKDAYS = [
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنج‌شنبه",
    "جمعه",
    "شنبه",
    "یکشنبه",
]
PERSIAN_MONTHS = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


def convert_sydney_str_to_tehran_info(sydney_date_str):
    try:
        clean_str = re.sub(r"\s+", " ", sydney_date_str.strip())
        dt_sydney = datetime.strptime(clean_str, "%d-%m-%Y %I:%M %p")
        dt_sydney = dt_sydney.replace(tzinfo=ZoneInfo("Australia/Sydney"))

        dt_tehran = dt_sydney.astimezone(ZoneInfo("Asia/Tehran"))

        jy, jm, jd = gregorian_to_jalali(
            dt_tehran.year, dt_tehran.month, dt_tehran.day
        )
        weekday_name = PERSIAN_WEEKDAYS[dt_tehran.weekday()]
        month_name = PERSIAN_MONTHS[jm - 1]

        time_str = dt_tehran.strftime("%H:%M")
        return f"{weekday_name} {jd} {month_name} {jy} - ساعت {time_str} (تهران)"
    except Exception as e:
        logging.error(f"Error converting date timezone: {e}")
        return "ساعت تهران نامشخص"


# ==================== نصب اتوماتیک مرورگر ====================
def ensure_playwright_browsers():
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
    except Exception as e:
        logging.warning(f"Playwright browser auto-install notice: {e}")


ensure_playwright_browsers()


# ==================== مدیریت دیتابیس (Async & WAL) ====================
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _init_db_sync():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitors (
                chat_id INTEGER PRIMARY KEY,
                username TEXT,
                mode TEXT,
                target_date TEXT,
                selected_dates TEXT,
                last_seats TEXT,
                cached_snapshot TEXT,
                error_notified INTEGER DEFAULT 0,
                consecutive_errors INTEGER DEFAULT 0,
                first_error_time REAL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_attempts (
                chat_id INTEGER PRIMARY KEY,
                attempts INTEGER,
                lockout_until REAL
            )
        """)
        conn.commit()


async def init_db():
    await asyncio.to_thread(_init_db_sync)


def _save_monitor_sync(
    chat_id,
    username,
    mode,
    target_date,
    selected_dates,
    last_seats,
    cached_snapshot,
    error_notified,
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO monitors (chat_id, username, mode, target_date, selected_dates, last_seats, cached_snapshot, error_notified, consecutive_errors, first_error_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
        """,
            (
                chat_id,
                username,
                mode,
                target_date,
                selected_dates,
                last_seats,
                cached_snapshot,
                error_notified,
            ),
        )
        conn.commit()


async def save_monitor(
    chat_id,
    username,
    mode,
    target_date="",
    selected_dates="",
    last_seats="",
    cached_snapshot="",
    error_notified=0,
):
    await asyncio.to_thread(
        _save_monitor_sync,
        chat_id,
        username,
        mode,
        target_date,
        selected_dates,
        last_seats,
        cached_snapshot,
        error_notified,
    )


def _get_monitor_sync(chat_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT mode, target_date, selected_dates, last_seats, cached_snapshot, username, error_notified, consecutive_errors, first_error_time FROM monitors WHERE chat_id = ?",
            (chat_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "mode": row[0],
                "target_date": row[1],
                "selected_dates": row[2].split(",") if row[2] else [],
                "last_seats": row[3],
                "cached_snapshot": row[4].split(",") if row[4] else [],
                "username": row[5],
                "error_notified": row[6],
                "consecutive_errors": row[7] if len(row) > 7 and row[7] is not None else 0,
                "first_error_time": row[8] if len(row) > 8 and row[8] is not None else 0,
            }
    return None


async def get_monitor(chat_id):
    return await asyncio.to_thread(_get_monitor_sync, chat_id)


def _record_error_and_check_cancel_sync(chat_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT consecutive_errors, first_error_time FROM monitors WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        if not row:
            return False
        
        curr_errors = row[0] if row[0] else 0
        first_time = row[1] if row[1] else 0
        now = time.time()
        
        if first_time == 0 or (now - first_time > 3600):
            new_errors = 1
            new_first_time = now
        else:
            new_errors = curr_errors + 1
            new_first_time = first_time
            
        if new_errors >= 7:
            cursor.execute("DELETE FROM monitors WHERE chat_id = ?", (chat_id,))
            conn.commit()
            return True
        else:
            cursor.execute("UPDATE monitors SET consecutive_errors = ?, first_error_time = ? WHERE chat_id = ?", 
                           (new_errors, new_first_time, chat_id))
            conn.commit()
            return False


async def record_error_and_check_cancel(chat_id):
    return await asyncio.to_thread(_record_error_and_check_cancel_sync, chat_id)


def _reset_error_counter_sync(chat_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE monitors SET consecutive_errors = 0, first_error_time = 0 WHERE chat_id = ?", (chat_id,))
        conn.commit()


async def reset_error_counter(chat_id):
    await asyncio.to_thread(_reset_error_counter_sync, chat_id)


def _update_error_status_sync(chat_id, status_value):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE monitors SET error_notified = ? WHERE chat_id = ?",
            (status_value, chat_id),
        )
        conn.commit()


async def update_error_status(chat_id, status_value):
    await asyncio.to_thread(_update_error_status_sync, chat_id, status_value)


def _remove_monitor_sync(chat_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM monitors WHERE chat_id = ?", (chat_id,))
        conn.commit()


async def remove_monitor(chat_id):
    await asyncio.to_thread(_remove_monitor_sync, chat_id)


# ==================== وب‌سرور زنده نگه داشتن RENDER ====================
flask_app = Flask(__name__)


@flask_app.route("/")
def keep_alive():
    return "NAATI Monitor Bot is Active and Running!", 200


def run_flask_server():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)


threading.Thread(target=run_flask_server, daemon=True).start()


# ==================== کیبوردهای ربات ====================
async def get_main_inline_keyboard(chat_id=None):
    keyboard = []
    if chat_id and await get_monitor(chat_id):
        keyboard.append([
            InlineKeyboardButton(
                "📊 مشاهده وضعیت پایش فعال", callback_data="btn_status"
            )
        ])
        keyboard.append([
            InlineKeyboardButton(
                "⛔ لغو پایش فعلی", callback_data="btn_stop_monitor"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔍 استخراج و انتخاب تاریخ از NAATI", callback_data="btn_list"
        )
    ])
    return InlineKeyboardMarkup(keyboard)


def get_single_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 وضعیت پایش من", callback_data="btn_status")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="btn_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_mode_selection_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🎯 انتخاب تکی", callback_data="mode_single"),
            InlineKeyboardButton(
                "📌 انتخاب چندتایی (حداکثر ۴)", callback_data="mode_multi"
            ),
        ],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="btn_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_error_retry_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 تلاش مجدد بارگذاری درخواست",
                callback_data="btn_retry_monitor",
            )
        ],
        [InlineKeyboardButton("🔍 انتخاب تاریخ جدید", callback_data="btn_list")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="btn_main")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def safe_delete_message(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int
):
    try:
        await context.bot.delete_message(
            chat_id=chat_id, message_id=message_id
        )
    except Exception:
        pass


class StatusTracker:
    def __init__(self, message):
        self.message = message
        self.steps = []

    async def update(self, step_text, status="in_progress", error_msg=None):
        if status == "in_progress":
            self.steps.append(f"⏳ {step_text}")
        elif status == "success":
            if self.steps:
                self.steps[-1] = f"✅ {step_text}"
        elif status == "failed":
            if self.steps:
                self.steps[-1] = f"❌ {step_text}"
            if error_msg:
                safe_err = html.escape(str(error_msg)[:200])
                self.steps.append(f"\n⚠️ علت خطا:\n{safe_err}")

        full_text = (
            "⚙️ <b>وضعیت پردازش:</b>\n"
            "<i>(این عملیات ممکن است حدود ۱ دقیقه زمان ببرد، لطفاً منتظر بمانید...)</i>\n\n"
            + "\n".join(self.steps)
        )
        try:
            await self.message.edit_text(full_text, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Error updating tracker message: {e}")

    async def delete_status_message(self):
        try:
            await self.message.delete()
        except Exception:
            pass


# ==================== دریافت داده‌ها از NAATI ====================
async def fetch_filtered_naati_dates(tracker: StatusTracker = None):
    async with async_playwright() as p:
        if tracker:
            await tracker.update("شروع پردازش", "in_progress")
        browser = None
        context = None
        try:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context()
            page = await context.new_page()
            if tracker:
                await tracker.update("شروع پردازش", "success")
                await tracker.update("بررسی سایت", "in_progress")
            await page.goto(
                "https://www.naati.com.au/test-date/",
                wait_until="networkidle",
                timeout=45000,
            )
            if tracker:
                await tracker.update("برقراری اتصال پایدار", "success")
                await tracker.update("تحلیل داده‌ها", "in_progress")
            selects = page.locator("select")
            await selects.nth(0).wait_for(timeout=10000)
            await selects.nth(0).select_option(
                label="Credentialed Community Language Test"
            )
            await page.wait_for_timeout(1000)
            if tracker:
                await tracker.update("برقراری اتصال پایدار", "success")
                await tracker.update("تحلیل داده‌های موجود", "in_progress")
            await selects.nth(1).select_option(label="Persian")
            await page.wait_for_timeout(1500)
            if tracker:
                await tracker.update("تحلیل داده‌های موجود", "success")
                await tracker.update("آماده سازی نتایج جهت نمایش", "in_progress")
            await page.wait_for_selector("table tbody tr", timeout=10000)
            rows = await page.query_selector_all("table tbody tr")
            all_dates = []
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 5:
                    test_type = (await cells[0].inner_text()).strip()
                    lang = (await cells[1].inner_text()).strip()
                    loc = (await cells[2].inner_text()).strip()
                    raw_date = (
                        (await cells[3].inner_text()).strip().replace("\n", " ")
                    )
                    seats = (await cells[4].inner_text()).strip()
                    all_dates.append({
                        "test_type": test_type,
                        "language": lang,
                        "location": loc,
                        "date": raw_date,
                        "seats": seats,
                    })
            if tracker:
                await tracker.update("آماده سازی نتایج جهت نمایش", "success")
            return all_dates, None
        except Exception as e:
            error_details = str(e)
            logging.error(f"Error fetching data: {error_details}")
            if tracker:
                last_step_text = (
                    tracker.steps[-1].replace("⏳ ", "").replace("...", "")
                    if tracker.steps
                    else "پردازش"
                )
                await tracker.update(last_step_text, "failed", error_details)
            return None, error_details
        finally:
            if context:
                await context.close()
            if browser:
                await browser.close()


# ==================== هاندلرهای اصلی ====================
async def send_main_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, message_id: int = None):
    """تابع مرکزی و هوشمند جهت ارسال یا ویرایش منوی اصلی"""
    main_kb = await get_main_inline_keyboard(chat_id)
    
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=MAIN_MENU_TEXT,
                parse_mode="HTML",
                reply_markup=main_kb
            )
            return
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=MAIN_MENU_TEXT,
        parse_mode="HTML",
        reply_markup=main_kb
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هندلر دستور /start"""
    chat_id = update.effective_chat.id
    USER_TEMP_SELECTIONS.pop(chat_id, None)
    await send_main_menu(chat_id, context)


async def handle_text_buttons(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    text = update.message.text
    chat_id = update.effective_chat.id
    USER_TEMP_SELECTIONS.pop(chat_id, None)
    if text in [
        "🔙 برگشت به منوی اصلی",
        "↩️ برگشت به صفحه قبل",
        "برگشت به منوی اصلی",
        "برگشت به صفحه قبل",
    ]:
        await send_main_menu(chat_id, context)


async def show_status(chat_id):
    monitor_info = await get_monitor(chat_id)
    if not monitor_info:
        return "ℹ️ شما در حال حاضر هیچ پایش فعالی ندارید."
    mode = monitor_info.get("mode")
    if mode == "single":
        d = html.escape(str(monitor_info["target_date"]))
        tehran_str = convert_sydney_str_to_tehran_info(monitor_info["target_date"])
        s = html.escape(str(monitor_info["last_seats"]))
        return (
            f"🎯 <b>پایش تکی فعال است:</b>\n\n"
            f"📅 <b>تاریخ (سیدنی):</b> {d}\n"
            f"⏰ <b>معادل تهران:</b> {html.escape(tehran_str)}\n"
            f"💺 <b>آخرین ظرفیت ثبت‌شده:</b> {s}\n\n"
            f"🔔 <b>شرط هشدار:</b> تغییر ظرفیت این تاریخ یا باز شدن تاریخ‌های جدید در سایت."
        )
    elif mode == "multi":
        dates_list = []
        for d in monitor_info.get("selected_dates", []):
            t_str = convert_sydney_str_to_tehran_info(d)
            dates_list.append(
                f"• {html.escape(d)}\n  ⏰ <i>{html.escape(t_str)}</i>"
            )

        seats_info = html.escape(str(monitor_info["last_seats"]))
        return (
            f"📌 <b>پایش چندتایی فعال است:</b>\n\n"
            f"📅 <b>تاریخ‌های تحت پایش:</b>\n" + "\n".join(dates_list) + "\n\n"
            f"💺 <b>آخرین وضعیت ظرفیت‌ها:</b>\n{seats_info}"
        )


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    username = (
        update.effective_user.username
        or update.effective_user.first_name
        or "Unknown"
    )

    if query.data == "btn_main":
        USER_TEMP_SELECTIONS.pop(chat_id, None)
        await send_main_menu(chat_id, context, query.message.message_id)
        return

    if query.data == "btn_status":
        await safe_delete_message(context, chat_id, query.message.message_id)
        status_text = await show_status(chat_id)
        await context.bot.send_message(
            chat_id,
            status_text,
            parse_mode="HTML",
            reply_markup=get_single_main_menu_keyboard(),
        )
        return

    if query.data == "btn_stop_monitor":
        USER_TEMP_SELECTIONS.pop(chat_id, None)
        await remove_monitor(chat_id)
        await safe_delete_message(context, chat_id, query.message.message_id)
        main_kb = await get_main_inline_keyboard(chat_id)
        await context.bot.send_message(
            chat_id,
            "✅ <b>پایش شما با موفقیت متوقف شد.</b>\n\n" + MAIN_MENU_TEXT,
            parse_mode="HTML",
            reply_markup=main_kb,
        )
        return

    if query.data == "btn_retry_monitor":
        await safe_delete_message(context, chat_id, query.message.message_id)
        monitor_info = await get_monitor(chat_id)
        if not monitor_info:
            await send_main_menu(chat_id, context)
            return
        status_msg = await context.bot.send_message(
            chat_id,
            "⚙️ <b>وضعیت پردازش:</b>\n<i>(این عملیات ممکن است حدود ۱ دقیقه زمان ببرد، لطفاً منتظر بمانید...)</i>\n\n⏳ شروع مرورگر",
            parse_mode="HTML",
        )
        tracker = StatusTracker(status_msg)
        data, error_err = await fetch_filtered_naati_dates(tracker)
        await tracker.delete_status_message()

        if not data:
            if error_err and ("select option action" in error_err or "Timeout" in error_err):
                is_cancelled = await record_error_and_check_cancel(chat_id)
                if is_cancelled:
                    cancel_keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 فعال‌سازی مجدد پایش", callback_data="btn_list")],
                        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="btn_main")]
                    ])
                    await context.bot.send_message(
                        chat_id,
                        "⚠️ <b>پایش شما کنسل شد!</b>\n\nبه علت بروز ۷ بار خطای متوالی در ارتباط با سایت NAATI در یک ساعت گذشته، پایش شما متوقف گردید.\nبا استفاده از دکمه زیر می‌توانید مجدداً فرآیند را اجرا و پایش را فعال کنید.",
                        parse_mode="HTML",
                        reply_markup=cancel_keyboard,
                    )
                    return

            safe_err = (
                html.escape(str(error_err)[:250])
                if error_err
                else "عدم پاسخگویی سرور NAATI"
            )
            await context.bot.send_message(
                chat_id,
                f"❌ <b>تلاش مجدد ناموفق بود!</b>\n\n⚠️ علت خطا:\n{safe_err}",
                parse_mode="HTML",
                reply_markup=get_error_retry_keyboard(),
            )
        else:
            await reset_error_counter(chat_id)
            await update_error_status(chat_id, 0)
            await context.bot.send_message(
                chat_id,
                "✅ <b>اتصال برقرار شد! پایش شما مجدداً بدون مشکل فعال گردید.</b>",
                parse_mode="HTML",
                reply_markup=get_single_main_menu_keyboard(),
            )
        return

    if query.data == "btn_list":
        current_msg_id = query.message.message_id
        status_msg = await context.bot.send_message(
            chat_id,
            "⚙️ <b>وضعیت پردازش:</b>\n<i>(این عملیات ممکن است حدود ۱ دقیقه زمان ببرد، لطفاً منتظر بمانید...)</i>\n\n⏳ شروع مرورگر",
            parse_mode="HTML",
        )
        tracker = StatusTracker(status_msg)
        data, error_err = await fetch_filtered_naati_dates(tracker)
        await tracker.delete_status_message()
        await safe_delete_message(context, chat_id, current_msg_id)

        if not data:
            if error_err and ("select option action" in error_err or "Timeout" in error_err):
                is_cancelled = await record_error_and_check_cancel(chat_id)
                if is_cancelled:
                    cancel_keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 فعال‌سازی مجدد پایش", callback_data="btn_list")],
                        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="btn_main")]
                    ])
                    await context.bot.send_message(
                        chat_id,
                        "⚠️ <b>پایش شما کنسل شد!</b>\n\nبه علت بروز ۷ بار خطای متوالی در ارتباط با سایت NAATI در یک ساعت گذشته، پایش شما متوقف گردید.\nبا استفاده از دکمه زیر می‌توانید مجدداً فرآیند را اجرا و پایش را فعال کنید.",
                        parse_mode="HTML",
                        reply_markup=cancel_keyboard,
                    )
                    return

            safe_err = (
                html.escape(str(error_err)[:250])
                if error_err
                else "عدم پاسخگویی سرور NAATI"
            )
            await context.bot.send_message(
                chat_id,
                f"❌ <b>خطا در برقرار ارتباط با سایت NAATI!</b>\n\n⚠️ علت خطا:\n{safe_err}",
                parse_mode="HTML",
                reply_markup=get_error_retry_keyboard(),
            )
            return

        context.user_data["cached_dates"] = data
        msg = "🗓️ <b>تاریخ‌های فعال آزمون CCL فارسی در سایت:</b>\n\n"
        for idx, item in enumerate(data, 1):
            tehran_time_info = convert_sydney_str_to_tehran_info(item["date"])
            msg += (
                f"{idx}. 📍 {html.escape(item['location'])} | "
                f"📅 {html.escape(item['date'])} | "
                f"💺 {html.escape(item['seats'])}\n"
                f"    ⏰ <i>{html.escape(tehran_time_info)}</i>\n\n"
            )
        msg += "👇 <b>لطفاً نحوه پایش را مشخص کنید:</b>"
        await context.bot.send_message(
            chat_id,
            msg,
            parse_mode="HTML",
            reply_markup=get_mode_selection_keyboard(),
        )
        return

    elif query.data == "mode_single":
        await safe_delete_message(context, chat_id, query.message.message_id)
        data = context.user_data.get("cached_dates", [])
        if not data:
            await context.bot.send_message(
                chat_id,
                "⚠️ اطلاعات منقضی شده، لطفاً دوباره دریافت لیست را بزنید.",
                reply_markup=get_single_main_menu_keyboard(),
            )
            return
        keyboard = []
        for idx, item in enumerate(data[:10]):
            keyboard.append([
                InlineKeyboardButton(
                    f"📅 {item['date']} (💺 {item['seats']})",
                    callback_data=f"select_single_{idx}",
                )
            ])
        keyboard.append(
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="btn_main")]
        )
        await context.bot.send_message(
            chat_id,
            "🎯 <b>یک تاریخ را جهت پایش تکی انتخاب کنید:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    elif query.data.startswith("select_single_"):
        await safe_delete_message(context, chat_id, query.message.message_id)
        idx = int(query.data.split("_")[-1])
        data = context.user_data.get("cached_dates", [])
        if idx >= len(data):
            return
        selected_item = data[idx]
        cached_snapshot = ",".join([d["date"] for d in data])
        await save_monitor(
            chat_id=chat_id,
            username=username,
            mode="single",
            target_date=selected_item["date"],
            last_seats=selected_item["seats"],
            cached_snapshot=cached_snapshot,
            error_notified=0,
        )
        d_safe = html.escape(selected_item["date"])
        t_tehran_safe = html.escape(
            convert_sydney_str_to_tehran_info(selected_item["date"])
        )
        await context.bot.send_message(
            chat_id,
            f"✅ <b>پایش تکی با موفقیت فعال شد!</b>\n\n📅 <b>تاریخ:</b> {d_safe}\n⏰ <b>ساعت تهران:</b> {t_tehran_safe}",
            parse_mode="HTML",
            reply_markup=get_single_main_menu_keyboard(),
        )
        return


# ==================== هاندر خطای عمومی ====================
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"Global Error Catch: {context.error}", exc_info=context.error)


# ==================== راه اندازی اصلی ====================
async def post_init(application):
    await init_db()


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()

    # ۱. ثبت CommandHandler دستور start
    app.add_handler(CommandHandler("start", start))

    # ۲. ثبت CallbackQueryHandler کلیک روی دکمه‌ها
    app.add_handler(CallbackQueryHandler(button_click))

    # ۳. ثبت MessageHandler پیام‌های متنی
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_buttons)
    )

    # ۴. ثبت سیستم ثبت خطا
    app.add_error_handler(global_error_handler)

    print("Bot starting polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
