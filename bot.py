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
# خاموش کردن لاگ‌های اضافه Flask/Werkzeug
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ==================== تنظیمات متغیرهای محیطی و امنیت ====================
TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "2377451").strip()

if not TELEGRAM_TOKEN:
  logging.warning(
      "⚠️ متغیر BOT_TOKEN یافت نشد! لطفاً آن را در تنظیمات سیستم/Render ست"
      " کنید."
  )

DB_PATH = "monitors.db"
USER_TEMP_SELECTIONS = {}


# ==================== خودکارسازی نصب مرورگر ====================
def ensure_playwright_browsers():
  try:
    from playwright.async_api import async_playwright
  except ImportError:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "playwright"], check=True
    )

  try:
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"], check=True
    )
  except Exception as e:
    logging.error(f"Playwright install log: {e}")


ensure_playwright_browsers()


# ==================== مدیریت دیتابیس SQLite (Thread-Safe & Async) ====================
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
                error_notified INTEGER DEFAULT 0
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
            INSERT OR REPLACE INTO monitors (chat_id, username, mode, target_date, selected_dates, last_seats, cached_snapshot, error_notified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
        "SELECT mode, target_date, selected_dates, last_seats,"
        " cached_snapshot, username, error_notified FROM monitors WHERE chat_id"
        " = ?",
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
      }
  return None


async def get_monitor(chat_id):
  return await asyncio.to_thread(_get_monitor_sync, chat_id)


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


def _get_all_monitors_sync():
  with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT chat_id, username, mode, target_date, selected_dates,"
        " last_seats, cached_snapshot, error_notified FROM monitors"
    )
    rows = cursor.fetchall()
    result = {}
    for row in rows:
      result[row[0]] = {
          "username": row[1],
          "mode": row[2],
          "target_date": row[3],
          "selected_dates": row[4].split(",") if row[4] else [],
          "last_seats": row[5],
          "cached_snapshot": row[6].split(",") if row[6] else [],
          "error_notified": row[7],
      }
    return result


async def get_all_monitors():
  return await asyncio.to_thread(_get_all_monitors_sync)


# ==================== امنیت ادمین ====================
ADMIN_LOGIN_STATE = 100


def _get_admin_status_sync(chat_id):
  with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT attempts, lockout_until FROM admin_attempts WHERE chat_id = ?",
        (chat_id,),
    )
    row = cursor.fetchone()
    if row:
      return {"attempts": row[0], "lockout_until": row[1]}
  return {"attempts": 0, "lockout_until": 0}


async def get_admin_status(chat_id):
  return await asyncio.to_thread(_get_admin_status_sync, chat_id)


def _record_failed_attempt_sync(chat_id):
  status = _get_admin_status_sync(chat_id)
  attempts = status["attempts"] + 1
  lockout_until = status["lockout_until"]

  if attempts >= 3:
    lockout_until = time.time() + 1800  # ۳۰ دقیقه قفل

  with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO admin_attempts (chat_id, attempts,"
        " lockout_until) VALUES (?, ?, ?)",
        (chat_id, attempts, lockout_until),
    )
    conn.commit()


async def record_failed_attempt(chat_id):
  await asyncio.to_thread(_record_failed_attempt_sync, chat_id)


def _reset_admin_attempts_sync(chat_id):
  with get_db_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM admin_attempts WHERE chat_id = ?", (chat_id,))
    conn.commit()


async def reset_admin_attempts(chat_id):
  await asyncio.to_thread(_reset_admin_attempts_sync, chat_id)


# ==================== وب‌سرور FLASK ====================
flask_app = Flask(__name__)


@flask_app.route("/")
def keep_alive():
  return "NAATI Monitor Bot is Active and Running!"


def run_flask_server():
  port = int(os.environ.get("PORT", 8080))
  flask_app.run(host="0.0.0.0", port=port, use_reloader=False)


threading.Thread(target=run_flask_server, daemon=True).start()


# ==================== کیبوردهای ساختاریافته ====================
def get_persistent_reply_keyboard():
  keyboard = [[
      KeyboardButton("🔙 برگشت به منوی اصلی"),
      KeyboardButton("⬅️ برگشت به صفحه قبل"),
  ]]
  return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def get_main_inline_keyboard(chat_id=None):
  keyboard = []
  if chat_id and await get_monitor(chat_id):
    keyboard.append([
        InlineKeyboardButton(
            "📊 مشاهده وضعیت پایش فعال", callback_data="btn_status"
        )
    ])
    keyboard.append(
        [InlineKeyboardButton("🛑 لغو پایش فعلی", callback_data="btn_stop_monitor")]
    )

  keyboard.append([
      InlineKeyboardButton(
          "📋 انتخاب تاریخ از سایت NAATI", callback_data="btn_list"
      )
  ])
  return InlineKeyboardMarkup(keyboard)


def get_single_main_menu_keyboard():
  keyboard = [
      [InlineKeyboardButton("📊 وضعیت پایش من", callback_data="btn_status")],
      [InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")],
  ]
  return InlineKeyboardMarkup(keyboard)


def get_mode_selection_keyboard():
  keyboard = [
      [
          InlineKeyboardButton("🎯 انتخاب تکی", callback_data="mode_single"),
          InlineKeyboardButton(
              "☑️ انتخاب چندتایی (حداکثر ۴)", callback_data="mode_multi"
          ),
      ],
      [InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")],
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
      [InlineKeyboardButton("📋 انتخاب تاریخ جدید", callback_data="btn_list")],
      [InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")],
  ]
  return InlineKeyboardMarkup(keyboard)


async def safe_delete_message(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int
):
  try:
    await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
  except Exception:
    pass


class StatusTracker:

  def __init__(self, message):
    self.message = message
    self.steps = []

  async def update(self, step_text, status="in_progress", error_msg=None):
    if status == "in_progress":
      self.steps.append(f"⏳ {step_text}...")
    elif status == "success":
      if self.steps:
        self.steps[-1] = f"✅ {step_text}"
    elif status == "failed":
      if self.steps:
        self.steps[-1] = f"❌ {step_text}"
      if error_msg:
        safe_err = html.escape(str(error_msg)[:200])
        self.steps.append(f"\n⚠️ <b>علت خطا:</b>\n<code>{safe_err}</code>")

    full_text = "⚙️ <b>وضعیت پردازش:</b>\n\n" + "\n".join(self.steps)
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
      await tracker.update("راه‌اندازی مرورگر اختصاصی", "in_progress")

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
        await tracker.update("راه‌اندازی مرورگر اختصاصی", "success")
        await tracker.update("باز کردن سایت NAATI", "in_progress")

      await page.goto(
          "https://www.naati.com.au/test-date/",
          wait_until="networkidle",
          timeout=45000,
      )
      if tracker:
        await tracker.update("باز کردن سایت NAATI", "success")
        await tracker.update("انتخاب نوع آزمون (CCL Test)", "in_progress")

      selects = page.locator("select")
      await selects.nth(0).wait_for(timeout=10000)
      await selects.nth(0).select_option(
          label="Credentialed Community Language Test"
      )
      await page.wait_for_timeout(1000)
      if tracker:
        await tracker.update("انتخاب نوع آزمون (CCL Test)", "success")
        await tracker.update("اعمال فیلتر زبان (Persian)", "in_progress")

      await selects.nth(1).select_option(label="Persian")
      await page.wait_for_timeout(1500)
      if tracker:
        await tracker.update("اعمال فیلتر زبان (Persian)", "success")
        await tracker.update("استخراج و تحلیل جدول ظرفیت‌ها", "in_progress")

      await page.wait_for_selector("table tbody tr", timeout=10000)
      rows = await page.query_selector_all("table tbody tr")

      all_dates = []
      for row in rows:
        cells = await row.query_selector_all("td")
        if len(cells) >= 5:
          test_type = (await cells[0].inner_text()).strip()
          lang = (await cells[1].inner_text()).strip()
          loc = (await cells[2].inner_text()).strip()
          raw_date = (await cells[3].inner_text()).strip().split("\n")[0]
          seats = (await cells[4].inner_text()).strip()

          all_dates.append({
              "test_type": test_type,
              "language": lang,
              "location": loc,
              "date": raw_date,
              "seats": seats,
          })

      if tracker:
        await tracker.update("استخراج و تحلیل جدول ظرفیت‌ها", "success")

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


def is_match(user_input, site_text):
  if not user_input or not site_text:
    return False
  clean_user = re.sub(r"[^a-zA-Z0-9]", "", str(user_input).lower())
  clean_site = re.sub(r"[^a-zA-Z0-9]", "", str(site_text).lower())
  return clean_user in clean_site or clean_site in clean_user


# ==================== هاندلرهای اصلی ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  USER_TEMP_SELECTIONS.pop(chat_id, None)

  await update.message.reply_text(
      "سلام! به ربات پایش ظرفیت NAATI خوش آمدید.\n\nلطفاً یک گزینه را انتخاب"
      " کنید:",
      reply_markup=get_persistent_reply_keyboard(),
  )
  main_kb = await get_main_inline_keyboard(chat_id)
  await update.message.reply_text("منوی کاربری:", reply_markup=main_kb)


async def handle_text_buttons(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  text = update.message.text
  chat_id = update.effective_chat.id
  USER_TEMP_SELECTIONS.pop(chat_id, None)

  if text in ["🔙 برگشت به منوی اصلی", "⬅️ برگشت به صفحه قبل"]:
    await update.message.reply_text(
        "منوی اصلی:", reply_markup=get_persistent_reply_keyboard()
    )
    main_kb = await get_main_inline_keyboard(chat_id)
    await update.message.reply_text("انتخاب کنید:", reply_markup=main_kb)


async def show_status(chat_id):
  monitor_info = await get_monitor(chat_id)
  if not monitor_info:
    return "❌ شما در حال حاضر <b>هیچ پایش فعالی ندارید.</b>"

  mode = monitor_info.get("mode")
  if mode == "single":
    d = html.escape(str(monitor_info["target_date"]))
    s = html.escape(str(monitor_info["last_seats"]))
    return (
        f"🟢 <b>پایش تکی فعال است:</b>\n\n📅 تاریخ: <code>{d}</code>\n💺 آخرین"
        f" ظرفیت ثبت‌شده: <b>{s}</b>\nℹ️ <i>شرط:</i> اعلام تغییر ظرفیت + باز شدن"
        " تاریخ جدید در محدوده ±4 سطر"
    )
  elif mode == "multi":
    dates_list = [
        html.escape(d) for d in monitor_info.get("selected_dates", [])
    ]
    seats_info = html.escape(str(monitor_info["last_seats"]))
    return (
        "🟢 <b>پایش چندتایی فعال است:</b>\n\n📅 تاریخ‌های تحت"
        f" پایش:\n<code>{', '.join(dates_list)}</code>\n💺 آخرین وضعیت"
        f" ظرفیت‌ها:\n<b>{seats_info}</b>"
    )


async def send_alert(app, chat_id, message_text):
  try:
    await app.bot.send_message(
        chat_id=chat_id,
        text=message_text,
        parse_mode="HTML",
        reply_markup=get_single_main_menu_keyboard(),
    )
  except Exception as e:
    logging.error(f"Failed to send alert to {chat_id}: {e}")


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
    await safe_delete_message(context, chat_id, query.message.message_id)
    main_kb = await get_main_inline_keyboard(chat_id)
    await context.bot.send_message(
        chat_id, "منوی اصلی:", reply_markup=main_kb
    )
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
        "🔴 <b>پایش شما با موفقیت متوقف شد.</b>",
        parse_mode="HTML",
        reply_markup=main_kb,
    )
    return

  if query.data == "btn_retry_monitor":
    await safe_delete_message(context, chat_id, query.message.message_id)
    monitor_info = await get_monitor(chat_id)
    if not monitor_info:
      main_kb = await get_main_inline_keyboard(chat_id)
      await context.bot.send_message(
          chat_id,
          "⚠️ هیچ درخواست پایش قبلی یافت نشد. لطفاً تاریخ جدید انتخاب کنید.",
          reply_markup=main_kb,
      )
      return

    status_msg = await context.bot.send_message(
        chat_id,
        "🔄 <b>در حال تلاش مجدد برای بارگذاری درخواست پایش شما...</b>",
        parse_mode="HTML",
    )
    tracker = StatusTracker(status_msg)
    data, error_err = await fetch_filtered_naati_dates(tracker)
    await tracker.delete_status_message()

    if not data:
      safe_err = (
          html.escape(str(error_err)[:250])
          if error_err
          else "عدم پاسخگویی سرور NAATI"
      )
      await context.bot.send_message(
          chat_id,
          "❌ <b>تلاش مجدد ناموفق بود!</b>\n\n⚠️ <b>علت"
          f" خطا:</b>\n<code>{safe_err}</code>",
          parse_mode="HTML",
          reply_markup=get_error_retry_keyboard(),
      )
    else:
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
        "⚙️ <b>در حال دریافت اطلاعات از سایت NAATI...</b>",
        parse_mode="HTML",
    )
    tracker = StatusTracker(status_msg)

    data, error_err = await fetch_filtered_naati_dates(tracker)
    await tracker.delete_status_message()
    await safe_delete_message(context, chat_id, current_msg_id)

    if not data:
      safe_err = (
          html.escape(str(error_err)[:250])
          if error_err
          else "عدم پاسخگویی سرور NAATI"
      )
      await context.bot.send_message(
          chat_id,
          "❌ <b>خطا در برقراری ارتباط با سایت NAATI!</b>\n\n⚠️ <b>علت"
          f" خطا:</b>\n<code>{safe_err}</code>",
          parse_mode="HTML",
          reply_markup=get_error_retry_keyboard(),
      )
      return

    context.user_data["cached_dates"] = data

    msg = "🗓 <b>تاریخ‌های فعال آزمون CCL فارسی در سایت:</b>\n\n"
    for idx, item in enumerate(data, 1):
      msg += (
          f"{idx}. 📍 <code>{html.escape(item['location'])}</code> | 📅"
          f" <code>{html.escape(item['date'])}</code> | 💺"
          f" <b>{html.escape(item['seats'])}</b>\n"
      )

    msg += "\n👇 <b>لطفاً نحوه پایش را مشخص کنید:</b>"
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
          "اطلاعات منقضی شده، لطفاً دوباره دریافت لیست را بزنید.",
          reply_markup=get_single_main_menu_keyboard(),
      )
      return

    keyboard = []
    for idx, item in enumerate(data[:10]):
      keyboard.append([
          InlineKeyboardButton(
              f"📅 {item['date']} ({item['seats']})",
              callback_data=f"select_single_{idx}",
          )
      ])
    keyboard.append(
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")]
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
    s_safe = html.escape(selected_item["seats"])

    await context.bot.send_message(
        chat_id,
        "✅ <b>پایش تکی فعال شد!</b>\n\n📅 تاریخ انتخابی:"
        f" <code>{d_safe}</code>\n💺 ظرفیت فعلی: <b>{s_safe}</b>\n\nℹ️ <i>در"
        " صورت تغییر ظرفیت یا اضافه شدن تاریخ جدید اطلاع داده می‌شود.</i>",
        parse_mode="HTML",
        reply_markup=get_single_main_menu_keyboard(),
    )
    return

  elif query.data == "mode_multi":
    await safe_delete_message(context, chat_id, query.message.message_id)
    USER_TEMP_SELECTIONS[chat_id] = set()
    await render_multi_select_menu(query, context, chat_id, edit=False)
    return

  elif query.data.startswith("toggle_multi_"):
    idx = int(query.data.split("_")[-1])
    selections = USER_TEMP_SELECTIONS.get(chat_id, set())

    if idx in selections:
      selections.remove(idx)
    else:
      if len(selections) >= 4:
        await query.answer(
            "⚠️ حداکثر می‌توانید ۴ تاریخ را انتخاب کنید!", show_alert=True
        )
        return
      selections.add(idx)

    USER_TEMP_SELECTIONS[chat_id] = selections
    await render_multi_select_menu(query, context, chat_id, edit=True)
    return

  elif query.data == "submit_multi":
    selections = USER_TEMP_SELECTIONS.get(chat_id, set())
    data = context.user_data.get("cached_dates", [])

    if not selections:
      await query.answer(
          "⚠️ لطفاً حداقل یک تاریخ را انتخاب کنید!", show_alert=True
      )
      return

    await safe_delete_message(context, chat_id, query.message.message_id)
    selected_items = [data[i] for i in selections if i < len(data)]
    selected_dates = [item["date"] for item in selected_items]
    last_seats = " | ".join(
        [f"{item['date']}:{item['seats']}" for item in selected_items]
    )

    await save_monitor(
        chat_id=chat_id,
        username=username,
        mode="multi",
        selected_dates=",".join(selected_dates),
        last_seats=last_seats,
        error_notified=0,
    )

    dates_str = "\n".join(
        [f"• <code>{html.escape(d)}</code>" for d in selected_dates]
    )

    await context.bot.send_message(
        chat_id,
        f"✅ <b>پایش چندتایی فعال شد!</b>\n\n{dates_str}",
        parse_mode="HTML",
        reply_markup=get_single_main_menu_keyboard(),
    )
    USER_TEMP_SELECTIONS.pop(chat_id, None)
    return

  elif query.data == "admin_refresh":
    await send_admin_panel_details(context, chat_id, query.message)
    return


async def render_multi_select_menu(query, context, chat_id, edit=False):
  data = context.user_data.get("cached_dates", [])
  selections = USER_TEMP_SELECTIONS.get(chat_id, set())

  keyboard = []
  for idx, item in enumerate(data[:10]):
    check = "✅ " if idx in selections else "[ ] "
    keyboard.append([
        InlineKeyboardButton(
            f"{check}{item['date']} ({item['seats']})",
            callback_data=f"toggle_multi_{idx}",
        )
    ])

  keyboard.append([
      InlineKeyboardButton(
          f"📥 ثبت نهایی ({len(selections)}/4)", callback_data="submit_multi"
      )
  ])
  keyboard.append(
      [InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")]
  )

  text = "☑️ <b>تاریخ‌های مدنظر را انتخاب کنید (حداکثر ۴ مورد):</b>"
  if edit:
    try:
      await query.message.edit_text(
          text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
      )
    except Exception:
      pass
  else:
    await context.bot.send_message(
        chat_id,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


# ==================== پنل مدیریت (ADMIN PANEL) ====================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
  chat_id = update.effective_chat.id
  status = await get_admin_status(chat_id)

  if status["lockout_until"] > time.time():
    remaining_minutes = int((status["lockout_until"] - time.time()) / 60) + 1
    await update.message.reply_text(
        "⛔️ <b>دسترسی مسدود است!</b>\nبه دلیل ۳ بار ورود اشتباه، تا"
        f" <code>{remaining_minutes}</code> دقیقه دیگر امکان ورود ندارید.",
        parse_mode="HTML",
    )
    return ConversationHandler.END

  await update.message.reply_text(
      "🔑 <b>لطفاً رمز عبور مدیریت را وارد کنید:</b>", parse_mode="HTML"
  )
  return ADMIN_LOGIN_STATE


async def handle_admin_password(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
  chat_id = update.effective_chat.id
  entered_pass = update.message.text.strip()

  status = await get_admin_status(chat_id)
  if status["lockout_until"] > time.time():
    remaining_minutes = int((status["lockout_until"] - time.time()) / 60) + 1
    await update.message.reply_text(
        "⛔️ <b>دسترسی مسدود است!</b>\nتا"
        f" <code>{remaining_minutes}</code> دقیقه دیگر منتظر بمانید.",
        parse_mode="HTML",
    )
    return ConversationHandler.END

  if entered_pass == ADMIN_PASSWORD:
    await reset_admin_attempts(chat_id)
    await update.message.reply_text(
        "✅ <b>ورود موفقیت‌آمیز بود.</b>", parse_mode="HTML"
    )
    await send_admin_panel_details(context, chat_id)
    return ConversationHandler.END
  else:
    await record_failed_attempt(chat_id)
    new_status = await get_admin_status(chat_id)
    attempts_left = 3 - new_status["attempts"]

    if new_status["attempts"] >= 3:
      await update.message.reply_text(
          "❌ <b>رمز اشتباه است!</b>\n⛔️ ۳ بار اشتباه وارد کردید. به مدت <b>۳۰"
          " دقیقه</b> مسدود شدید.",
          parse_mode="HTML",
      )
    else:
      await update.message.reply_text(
          f"❌ <b>رمز اشتباه است!</b>\nفرصت‌های باقی‌مانده: {attempts_left}",
          parse_mode="HTML",
      )

    return ConversationHandler.END


async def send_admin_panel_details(
    context: ContextTypes.DEFAULT_TYPE, chat_id, message_to_edit=None
):
  try:
    monitors = await get_all_monitors()
    total_users = len(monitors)

    msg = "👨‍💻 <b>پنل مدیریت ربات پایش NAATI</b>\n\n"
    msg += f"📊 تعداد کل پایش‌های فعال: <b>{total_users}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━\n\n"

    if not monitors:
      msg += "📭 هیچ پایش فعالی وجود ندارد."
    else:
      for cid, info in monitors.items():
        raw_uname = info.get("username") or "Unknown"
        user_str = (
            f"@{html.escape(raw_uname)}"
            if info.get("username")
            else f"ID: <code>{cid}</code>"
        )
        mode_str = "🎯 تکی" if info["mode"] == "single" else "☑️ چندتایی"

        if info["mode"] == "single":
          t_date = html.escape(str(info["target_date"]))
          l_seats = html.escape(str(info["last_seats"]))
          details = (
              f"تاریخ: <code>{t_date}</code> | آخرین ظرفیت: <b>{l_seats}</b>"
          )
        else:
          sel_dates = [html.escape(d) for d in info["selected_dates"]]
          details = f"تاریخ‌ها: <code>{', '.join(sel_dates)}</code>"

        msg += (
            f"👤 کاربر: {user_str}\nنوع: {mode_str}\nجزئیات:"
            f" {details}\n\n"
        )

    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 بروزرسانی پنل", callback_data="admin_refresh"
            )
        ],
        [InlineKeyboardButton("🔙 خروج", callback_data="btn_main")],
    ]

    if message_to_edit:
      await message_to_edit.edit_text(
          msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard)
      )
    else:
      await context.bot.send_message(
          chat_id=chat_id,
          text=msg,
          parse_mode="HTML",
          reply_markup=InlineKeyboardMarkup(keyboard),
      )

  except Exception as e:
    logging.error(f"Error in send_admin_panel_details: {e}")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⚠️ خطا در نمایش پنل ادمین:\n<code>{html.escape(str(e))}</code>",
        parse_mode="HTML",
    )


# ==================== حلقه پایش عمومی و مدیریت خطاها ====================
async def global_monitoring_loop(app):
  while True:
    await asyncio.sleep(300)

    try:
      monitors = await get_all_monitors()
      if not monitors:
        continue

      logging.info(
          f"Checking NAATI site for {len(monitors)} database monitors..."
      )
      data, fetch_err = await fetch_filtered_naati_dates()

      if not data:
        logging.warning(f"Monitoring fetch failed: {fetch_err}")
        safe_err = (
            html.escape(str(fetch_err)[:250])
            if fetch_err
            else "عدم پاسخگویی یا قطع اتصال سرور NAATI"
        )

        for chat_id, monitor_info in monitors.items():
          if monitor_info.get("error_notified", 0) == 0:
            try:
              await app.bot.send_message(
                  chat_id=chat_id,
                  text=(
                      "❌ <b>خطا در پایش درخواست شما!</b>\n\nدر میانه زمان"
                      " پایش، ربات نتوانست وارد سایت شود یا داده‌ها را بررسی"
                      f" کند.\n\n⚠️ <b>علت خطا:</b>\n<code>{safe_err}</code>"
                  ),
                  parse_mode="HTML",
                  reply_markup=get_error_retry_keyboard(),
              )
              await update_error_status(chat_id, 1)
            except Exception as send_err:
              logging.error(
                  f"Failed to send error notification to {chat_id}: {send_err}"
              )
        continue

      for chat_id, monitor_info in monitors.items():
        if monitor_info.get("error_notified", 0) == 1:
          await update_error_status(chat_id, 0)

        mode = monitor_info.get("mode")

        if mode == "single":
          target_date = monitor_info["target_date"]
          last_seats = monitor_info["last_seats"]

          current_idx = next(
              (
                  i
                  for i, item in enumerate(data)
                  if is_match(target_date, item["date"])
              ),
              None,
          )

          if current_idx is not None:
            curr_seats = data[current_idx]["seats"]
            if curr_seats != last_seats:
              await save_monitor(
                  chat_id,
                  monitor_info["username"],
                  mode,
                  target_date=target_date,
                  last_seats=curr_seats,
                  cached_snapshot=",".join(monitor_info["cached_snapshot"]),
                  error_notified=0,
              )
              await send_alert(
                  app,
                  chat_id,
                  "🔔 <b>تغییر ظرفیت تاریخ انتخابی:</b>\n\n📅 تاریخ:"
                  f" <code>{html.escape(target_date)}</code>\n💺 ظرفیت جدید:"
                  f" <b>{html.escape(curr_seats)}</b>",
              )

            start_idx = max(0, current_idx - 4)
            end_idx = min(len(data), current_idx + 5)
            nearby_items = data[start_idx:end_idx]

            snapshot = monitor_info.get("cached_snapshot", [])
            new_found = [
                item for item in nearby_items if item["date"] not in snapshot
            ]

            if new_found:
              updated_snapshot = snapshot + [item["date"] for item in new_found]
              await save_monitor(
                  chat_id,
                  monitor_info["username"],
                  mode,
                  target_date=target_date,
                  last_seats=curr_seats,
                  cached_snapshot=",".join(updated_snapshot),
                  error_notified=0,
              )
              msg_new = "🔥 <b>تاریخ جدید در محدوده ±4 سطر یافت شد!</b>\n\n"
              for item in new_found:
                msg_new += (
                    f"📅 تاریخ: <code>{html.escape(item['date'])}</code> | 💺"
                    f" ظرفیت: <b>{html.escape(item['seats'])}</b>\n"
                )
              await send_alert(app, chat_id, msg_new)

        elif mode == "multi":
          selected_dates = monitor_info.get("selected_dates", [])
          last_seats_str = monitor_info.get("last_seats", "")

          last_seats_dict = {}
          if last_seats_str:
            for pair in last_seats_str.split(" | "):
              if ":" in pair:
                d, s = pair.split(":", 1)
                last_seats_dict[d] = s

          updated_seats_dict = last_seats_dict.copy()
          changes_detected = False
          msg_multi = "🔔 <b>تغییر ظرفیت در تاریخ‌های پایش چندتایی:</b>\n\n"

          for s_date in selected_dates:
            matched_item = next(
                (item for item in data if is_match(s_date, item["date"])), None
            )
            if matched_item:
              c_seats = matched_item["seats"]
              prev_s = last_seats_dict.get(s_date, "")
              if c_seats != prev_s:
                changes_detected = True
                updated_seats_dict[s_date] = c_seats
                msg_multi += (
                    f"📅 تاریخ: <code>{html.escape(s_date)}</code> | ظرفیت جدید:"
                    f" <b>{html.escape(c_seats)}</b>\n"
                )

          if changes_detected:
            new_seats_str = " | ".join(
                [f"{d}:{s}" for d, s in updated_seats_dict.items()]
            )
            await save_monitor(
                chat_id,
                monitor_info["username"],
                mode,
                selected_dates=",".join(selected_dates),
                last_seats=new_seats_str,
                error_notified=0,
            )
            await send_alert(app, chat_id, msg_multi)

    except Exception as e:
      logging.error(f"Error in global_monitoring_loop: {e}")


# ==================== نقطه شروع برنامه (MAIN) ====================
async def post_init(app):
  await init_db()
  asyncio.create_task(global_monitoring_loop(app))


def main():
  if not TELEGRAM_TOKEN:
    logging.critical("❌ توکن ربات تنظیم نشده است. برنامه متوقف می‌شود.")
    return

  application = (
      ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
  )

  admin_handler = ConversationHandler(
      entry_points=[CommandHandler("admin", admin_command)],
      states={
          ADMIN_LOGIN_STATE: [
              MessageHandler(
                  filters.TEXT & ~filters.COMMAND, handle_admin_password
              )
          ]
      },
      fallbacks=[],
  )

  application.add_handler(admin_handler)
  application.add_handler(CommandHandler("start", start))
  application.add_handler(
      MessageHandler(
          filters.Regex("^(🔙 برگشت به منوی اصلی|⬅️ برگشت به صفحه قبل)$"),
          handle_text_buttons,
      )
  )
  application.add_handler(CallbackQueryHandler(button_click))

  logging.info("ربات پایش NAATI با موفقیت راه‌اندازی شد...")
  application.run_polling()


if __name__ == "__main__":
  main()
