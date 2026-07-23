import asyncio
import re
import os
import sys
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# ==================== خودکارسازی نصب مرورگر ====================
def ensure_playwright_browsers():
    """اطمینان از دانلود و وجود کرومیوم در مسیر Render"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
    
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        print(f"Playwright install log: {e}")

ensure_playwright_browsers()

from playwright.async_api import async_playwright
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler, ContextTypes
)

# سرور ساختگی برای زنده نگه داشتن پورت Render
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        return

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    server.serve_forever()

# ==================== تنظیمات ====================
TELEGRAM_TOKEN = "8708901411:AAGerrcWjeVS2CvQ3dHI4NLs6uO8RgE3uDU"
DEFAULT_LOCATION = "ONLINE"

WAITING_FOR_DATE = 1

def get_main_inline_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 انتخاب از تاریخ‌های موجود سایت", callback_data="btn_list")],
        [InlineKeyboardButton("✏️ وارد کردن تاریخ به صورت دستی", callback_data="btn_manual")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_single_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

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
                self.steps.append(f"\n⚠️ **علت خطا:**\n`{error_msg[:200]}`")

        full_text = "⚙️ **وضعیت پردازش:**\n\n" + "\n".join(self.steps)
        try:
            await self.message.edit_text(full_text, parse_mode="Markdown")
        except Exception:
            pass

    async def delete_status_message(self):
        """حذف پیام وضعیت پردازش پس از اتمام کار"""
        try:
            await self.message.delete()
        except Exception:
            pass

async def fetch_filtered_naati_dates(tracker: StatusTracker = None):
    async with async_playwright() as p:
        if tracker:
            await tracker.update("راه‌اندازی مرورگر اختصاصی", "in_progress")
        
        browser = None
        try:
            browser = await p.chromium.launch(
                headless=True, 
                args=[
                    "--no-sandbox", 
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu"
                ]
            )
            page = await browser.new_page()
            if tracker:
                await tracker.update("راه‌اندازی مرورگر اختصاصی", "success")
        except Exception as e:
            if tracker:
                await tracker.update("راه‌اندازی مرورگر اختصاصی", "failed", str(e))
            if browser:
                await browser.close()
            return None

        all_dates = []
        try:
            # گام ۱: باز کردن سایت
            if tracker:
                await tracker.update("باز کردن سایت NAATI", "in_progress")
            await page.goto("https://www.naati.com.au/test-date/", wait_until="networkidle", timeout=45000)
            if tracker:
                await tracker.update("باز کردن سایت NAATI", "success")

            # گام ۲: انتخاب نوع آزمون
            if tracker:
                await tracker.update("انتخاب نوع آزمون (CCL Test)", "in_progress")
            selects = page.locator("select")
            await selects.nth(0).wait_for(timeout=10000)
            await selects.nth(0).select_option(label="Credentialed Community Language Test")
            await page.wait_for_timeout(1000)
            if tracker:
                await tracker.update("انتخاب نوع آزمون (CCL Test)", "success")

            # گام ۳: انتخاب زبان
            if tracker:
                await tracker.update("اعمال فیلتر زبان (Persian)", "in_progress")
            await selects.nth(1).select_option(label="Persian")
            await page.wait_for_timeout(1500)
            if tracker:
                await tracker.update("اعمال فیلتر زبان (Persian)", "success")

            # گام ۴: استخراج جدول
            if tracker:
                await tracker.update("استخراج و تحلیل جدول ظرفیت‌ها", "in_progress")
            await page.wait_for_selector("table tbody tr", timeout=10000)
            rows = await page.query_selector_all("table tbody tr")
            
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 5:
                    test_type = (await cells[0].inner_text()).strip()
                    lang = (await cells[1].inner_text()).strip()
                    loc = (await cells[2].inner_text()).strip()
                    raw_date = (await cells[3].inner_text()).strip().split('\n')[0]
                    seats = (await cells[4].inner_text()).strip()
                    
                    all_dates.append({
                        "test_type": test_type,
                        "language": lang,
                        "location": loc,
                        "date": raw_date,
                        "seats": seats
                    })
            
            if tracker:
                await tracker.update("استخراج و تحلیل جدول ظرفیت‌ها", "success")
            
            await browser.close()
            return all_dates

        except Exception as e:
            error_details = str(e)
            print(f"Error fetching data: {error_details}")
            if tracker:
                last_step_text = tracker.steps[-1].replace("⏳ ", "").replace("...", "") if tracker.steps else "پردازش"
                await tracker.update(last_step_text, "failed", error_details)
            if browser:
                await browser.close()
            return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! به ربات پایش ظرفیت NAATI (ویژه CCL زبان فارسی) خوش آمدید.\n\nلطفاً یک گزینه را انتخاب کنید:",
        reply_markup=get_main_inline_keyboard()
    )
    return ConversationHandler.END

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "btn_main":
        await query.message.reply_text("منوی اصلی:", reply_markup=get_main_inline_keyboard())
        return ConversationHandler.END

    if query.data == "btn_list":
        status_msg = await query.message.reply_text("⚙️ **در حال شروع...**", parse_mode="Markdown")
        tracker = StatusTracker(status_msg)
        
        data = await fetch_filtered_naati_dates(tracker)

        # حذف پیام وضعیت پردازش پس از اتمام عملیات
        await tracker.delete_status_message()

        if data is None:
            await query.message.reply_text(
                "❌ عملیات ناموفق بود. می‌توانید دوباره امتحان کنید.",
                reply_markup=get_single_main_menu_keyboard()
            )
            return ConversationHandler.END

        if len(data) == 0:
            await query.message.reply_text(
                "ℹ️ هیچ تاریخ جدیدی در سایت یافت نشد.",
                reply_markup=get_single_main_menu_keyboard()
            )
            return ConversationHandler.END

        msg = "🗓 **تاریخ‌های فعال آزمون CCL فارسی در سایت:**\n\n"
        for item in data:
            msg += f"📍 مکان: `{item['location']}` | 📅 تاریخ: `{item['date']}` | 💺 ظرفیت: **{item['seats']}**\n"

        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_single_main_menu_keyboard())
        return ConversationHandler.END

    elif query.data == "btn_manual":
        await query.message.reply_text(
            f"📍 مکان آزمون به صورت پیش‌فرض **{DEFAULT_LOCATION}** در نظر گرفته شد.\n\nلطفاً **تاریخ مدنظر** را وارد کنید:\n(مثال: `03-09-2026` یا بخشی از تاریخ مثل `September` یا `03`)",
            reply_markup=get_single_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return WAITING_FOR_DATE

async def get_date_and_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_date = update.message.text
    target_location = DEFAULT_LOCATION
    chat_id = update.effective_chat.id

    status_msg = await update.message.reply_text("⚙️ **در حال شروع...**", parse_mode="Markdown")
    tracker = StatusTracker(status_msg)

    data = await fetch_filtered_naati_dates(tracker)

    # حذف پیام وضعیت پردازش پس از اتمام عملیات
    await tracker.delete_status_message()

    if data is None:
        await update.message.reply_text(
            "❌ عملیات پایش متوقف شد.",
            reply_markup=get_single_main_menu_keyboard()
        )
        return ConversationHandler.END

    found_item = None
    for item in data:
        if is_match(target_location, item['location']) and (target_date in item['date'] or is_match(target_date, item['date'])):
            found_item = item
            break

    if found_item:
        await update.message.reply_text(
            f"✅ **تاریخ پیدا شد و پایش فعال گردید!**\n\n📍 مکان: `{found_item['location']}`\n📅 تاریخ: `{found_item['date']}`\n💺 ظرفیت فعلی: **{found_item['seats']}**\n\nربات هر ۵ دقیقه سایت را پایش می‌کند و در صورت تغییر ظرفیت پیام می‌دهد.",
            parse_mode="Markdown",
            reply_markup=get_single_main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"⚠️ **تاریخ `{target_date}` در حال حاضر در سایت موجود نیست.**\n\nاما پایش خودکار فعال شد! به محض اینکه این تاریخ در سایت باز شود، ربات به شما خبر می‌دهد.",
            parse_mode="Markdown",
            reply_markup=get_single_main_menu_keyboard()
        )

    asyncio.create_task(start_monitoring(chat_id, target_location, target_date, context))
    return ConversationHandler.END

def is_match(user_input, site_text):
    clean_user = re.sub(r'[^a-zA-Z0-9]', '', user_input.lower())
    clean_site = re.sub(r'[^a-zA-Z0-9]', '', site_text.lower())
    return clean_user in clean_site or clean_site in clean_user

async def start_monitoring(chat_id, location, date_str, context):
    while True:
        await asyncio.sleep(300)
        data = await fetch_filtered_naati_dates()
        if data:
            for item in data:
                if is_match(location, item['location']) and (date_str in item['date'] or is_match(date_str, item['date'])):
                    seats_str = item['seats']
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🔔 **گزارش پایش ظرفیت:**\n\n📍 مکان: {item['location']}\n📅 تاریخ: {item['date']}\n💺 وضعیت ظرفیت: **{seats_str}**\n\n🔗 [ثبت نام در سایت NAATI](https://www.naati.com.au/test-date/)",
                        parse_mode="Markdown",
                        reply_markup=get_single_main_menu_keyboard()
                    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=get_main_inline_keyboard())
    return ConversationHandler.END

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_click, pattern="^btn_manual$")
        ],
        states={
            WAITING_FOR_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date_and_start)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(button_click, pattern="^btn_main$")
        ],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_click))

    print("ربات با موفقیت روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
