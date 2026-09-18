import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from playwright.async_api import async_playwright

# تنظیمات لاگینگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")

class NAATITracker:
    def __init__(self):
        self.url = "https://cclpanel.com/"

    async def fetch_dates(self, status_callback=None):
        async with async_playwright() as p:
            if status_callback:
                await status_callback("🌐 در حال راه اندازی مرورگر اختصاصی...")
            
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            page = await context.new_page()

            try:
                if status_callback:
                    await status_callback("🔄 در حال دریافت اطلاعات از سایت NAATI...")
                
                await page.goto(self.url, wait_until="networkidle", timeout=60000)
                await asyncio.sleep(3)

                # استخراج اطلاعات جدول
                rows = await page.query_selector_all("table tbody tr")
                dates_info = []

                for row in rows:
                    text = await row.inner_text()
                    if text and ("Persian" in text or "فارسی" in text):
                        dates_info.append(text.strip())

                await browser.close()
                return dates_info, None

            except Exception as e:
                await browser.close()
                logger.error(f"Error fetching data: {e}")
                return None, str(e)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 بررسی ظرفیت‌های آنلاین CCL", callback_data="check_dates")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! به ربات استعلام خودکار تاریخ‌های آزمون NAATI خوش آمدید.\n"
        "برای مشاهده جدیدترین ظرفیت‌های فعال زبان فارسی، روی دکمه زیر کلیک کنید:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_dates":
        status_msg = await query.message.reply_text("⏳ در حال شروع پردازش...")
        
        async def edit_status(text):
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass

        tracker = NAATITracker()
        dates, error = await tracker.fetch_dates(status_callback=edit_status)

        if error:
            await status_msg.edit_text(f"❌ خطایی در استخراج اطلاعات رخ داد:\n`{error}`", parse_mode="Markdown")
        elif dates:
            formatted_dates = "\n\n".join([f"🔹 {d}" for d in dates])
            await status_msg.edit_text(f"✅ **جدیدترین ظرفیت‌های موجود:**\n\n{formatted_dates}", parse_mode="Markdown")
        else:
            await status_msg.edit_text("ℹ️ در حال حاضر هیچ ظرفیت جدیدی برای زبان فارسی یافت نشد یا سایت تغییر کرده است.")

def main():
    if not TOKEN:
        logger.error("BOT_TOKEN is not set!")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is starting polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
