import asyncio
import re
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from playwright.async_api import async_playwright
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler, ContextTypes
)

# سرور ساختگی برای دادن پاسخ پورت به Render (پلن رایگان)
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        return  # خاموش کردن لاگ‌های اضافی سرور وب

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    server.serve_forever()

# ==================== تنظیمات ====================
TELEGRAM_TOKEN = "8708901411:AAEWDd3HcW-oAqyrAhfp4h6fhmLlO88eS-k"
DEFAULT_LOCATION = "ONLINE"

MANUAL_DATE = 0

def get_main_inline_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 انتخاب از تاریخ‌های موجود سایت", callback_data="btn_list")],
        [InlineKeyboardButton("✏️ وارد کردن تاریخ به صورت دستی", callback_data="btn_manual")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_reset_inline_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🔄 ریست / شروع مجدد", callback_data="btn_reset"),
            InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def fetch_filtered_naati_dates(status_msg=None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        page = await browser.new_page()

        all_dates = []
        try:
            if status_msg:
                await status_msg.edit_text("⏳ [۱/۴] در حال باز کردن سایت NAATI...")
            
            await page.goto("https://www.naati.com.au/test-date/", wait_until="networkidle", timeout=45000)

            if status_msg:
                await status_msg.edit_text("🔍 [۲/۴] انتخاب نوع آزمون (CCL Test)...")
            
            selects = page.locator("select")
            await selects.nth(0).wait_for(timeout=10000)
            await selects.nth(0).select_option(label="Credentialed Community Language Test")
            await page.wait_for_timeout(1000)

            if status_msg:
                await status_msg.edit_text("🇮🇷 [۳/۴] انتخاب زبان (Persian)...")
            
            await selects.nth(1).select_option(label="Persian")
            await page.wait_for_timeout(1500)

            if status_msg:
                await status_msg.edit_text("📊 [۴/۴] در حال استخراج و تحلیل جدول...")

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
            
            await browser.close()
            return all_dates
        except Exception as e:
            print(f"Error fetching data: {e}")
            await browser.close()
            return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! به ربات پایش ظرفیت NAATI (ویژه CCL زبان فارسی) خوش آمدید.\n\nلطفاً یک گزینه را انتخاب کنید:",
        reply_markup=get_main_inline_keyboard()
    )
    return ConversationHandler.END

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data in ["btn_main", "btn_reset"]:
        await query.message.reply_text("منوی اصلی:", reply_markup=get_main_inline_keyboard())
        return ConversationHandler.END

    if query.data == "btn_list":
        status_msg = await query.message.reply_text("⏳ شروع فرایند...")
        data = await fetch_filtered_naati_dates(status_msg)
        
        try:
            await status_msg.delete()
        except Exception:
            pass

        if not data:
            await query.message.reply_text(
                "❌ متأسفانه دریافت اطلاعات ناموفق بود یا ظرفیتی یافت نشد. لطفاً دوباره تلاش کنید.",
                reply_markup=get_reset_inline_keyboard()
            )
            return

        msg = "🗓 **تاریخ‌های فعال آزمون CCL فارسی در سایت:**\n\n"
        for item in data:
            msg += f"📍 مکان: `{item['location']}` | 📅 تاریخ: `{item['date']}` | 💺 ظرفیت: **{item['seats']}**\n"

        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_reset_inline_keyboard())

    elif query.data == "btn_manual":
        await query.message.reply_text(
            f"📍 مکان آزمون به صورت پیش‌فرض **{DEFAULT_LOCATION}** در نظر گرفته شد.\n\nلطفاً **تاریخ مدنظر** را وارد کنید:\n(مثال: `03-09-2026` یا بخشی از تاریخ مثل `September` یا `03`)",
            reply_markup=get_reset_inline_keyboard(),
            parse_mode="Markdown"
        )
        return MANUAL_DATE

async def get_date_and_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_date = update.message.text
    target_location = DEFAULT_LOCATION
    chat_id = update.effective_chat.id

    status_msg = await update.message.reply_text("🔎 در حال بررسی اولیه تاریخ وارد شده در سایت...")
    
    data = await fetch_filtered_naati_dates(status_msg)
    
    try:
        await status_msg.delete()
    except Exception:
        pass

    found_item = None
    for item in data:
        if is_match(target_location, item['location']) and (target_date in item['date'] or is_match(target_date, item['date'])):
            found_item = item
            break

    if found_item:
        await update.message.reply_text(
            f"✅ **تاریخ پیدا شد و پایش فعال گردید!**\n\n📍 مکان: `{found_item['location']}`\n📅 تاریخ: `{found_item['date']}`\n💺 ظرفیت فعلی: **{found_item['seats']}**\n\nربات هر ۵ دقیقه سایت را پایش می‌کند و در صورت تغییر ظرفیت پیام می‌دهد.",
            parse_mode="Markdown",
            reply_markup=get_reset_inline_keyboard()
        )
    else:
        await update.message.reply_text(
            f"⚠️ **تاریخ `{target_date}` در حال حاضر در سایت موجود نیست.**\n\nاما پایش خودکار فعال شد! به محض اینکه این تاریخ در سایت باز شود، ربات به شما خبر می‌دهد.",
            parse_mode="Markdown",
            reply_markup=get_reset_inline_keyboard()
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
        for item in data:
            if is_match(location, item['location']) and (date_str in item['date'] or is_match(date_str, item['date'])):
                seats_str = item['seats']
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔔 **گزارش پایش ظرفیت:**\n\n📍 مکان: {item['location']}\n📅 تاریخ: {item['date']}\n💺 وضعیت ظرفیت: **{seats_str}**\n\n🔗 [ثبت نام در سایت NAATI](https://www.naati.com.au/test-date/)",
                    parse_mode="Markdown",
                    reply_markup=get_reset_inline_keyboard()
                )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=get_main_inline_keyboard())
    return ConversationHandler.END

def main():
    # شروع سرور پورت رایگان
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_click, pattern="^btn_manual$")
        ],
        states={
            MANUAL_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date_and_start)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(button_click, pattern="^(btn_main|btn_reset)$")
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(conv_handler)

    print("ربات روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
