import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from playwright.async_api import async_playwright

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")

class NAATITracker:
    def __init__(self):
        self.url = "https://cclpanel.com/"

    async def fetch_dates(self, status_callback=None):
        async with async_playwright() as p:
            if status_callback:
                await status_callback("🌐 در حال راه‌اندازی مرورگر اختصاصی...")
            
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
            )
            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            page = await context.new_page()

            try:
                if status_callback:
                    await status_callback("🔄 در حال اتصال و دریافت اطلاعات ظرفیت‌ها...")
                
                await page.goto(self.url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(2)

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

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 بررسی ظرفیت‌های آنلاین CCL", callback_data="check_dates")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! به ربات استعلام خودکار تاریخ‌های آزمون NAATI خوش آمدید.\n"
        "برای مشاهده جدیدترین ظرفیت‌های فعال، روی دکمه زیر کلیک کنید:",
        reply_markup=reply_markup
    )

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_dates":
        status_msg = await query.message.reply_text("⏳ در حال پردازش و استخراج...")
        
        async def update_status_text(text):
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass

        tracker = NAATITracker()
        dates, error = await tracker.fetch_dates(status_callback=update_status_text)

        if error:
            await status_msg.edit_text(f"❌ خطایی در استخراج اطلاعات رخ داد:\n`{error}`", parse_mode="Markdown")
        elif dates:
            formatted_dates = "\n\n".join([f"🔹 {d}" for d in dates])
            await status_msg.edit_text(f"✅ **جدیدترین ظرفیت‌های موجود:**\n\n{formatted_dates}", parse_mode="Markdown")
        else:
            await status_msg.edit_text("ℹ️ در حال حاضر هیچ ظرفیت جدیدی یافت نشد.")

def main():
    if not TOKEN:
        logger.error("BOT_TOKEN یافت نشد!")
        return

    # استفاده از drop_pending_updates برای پاکسازی اتصالات معلق قبلی
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_button_click))

    logger.info("Bot starting with drop_pending_updates...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
