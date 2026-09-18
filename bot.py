import os
import logging
from playwright.async_api import async_playwright
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")

async def fetch_naati_dates():
    """مراجعه به NAATI، انتخاب فیلترها و استخراج جدول ظرفیت‌ها"""
    url = "https://www.naati.com.au/test-date/"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            # ۱. باز کردن صفحه
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            
            # ۲. انتخاب Test Type -> Credentialed Community Language Test
            test_type_select = page.locator("select").nth(0)
            await test_type_select.wait_for(state="visible", timeout=15000)
            await test_type_select.select_option(label="Credentialed Community Language Test")
            await page.wait_for_timeout(1000)

            # ۳. انتخاب Language -> Persian
            lang_select = page.locator("select").nth(1)
            await lang_select.select_option(label="Persian")
            await page.wait_for_timeout(1000)

            # ۴. انتخاب Location -> ONLINE - Online
            loc_select = page.locator("select").nth(2)
            await loc_select.select_option(label="ONLINE - Online")
            
            # ۵. مکث کوتاه جهت به‌روزرسانی جدول
            await page.wait_for_timeout(2500)

            # ۶. استخراج سطر‌های جدول
            rows = await page.locator("tbody tr").all()
            results = []

            for row in rows:
                cells = await row.locator("td").all_text_contents()
                if len(cells) >= 5:
                    test_type = cells[0].strip()
                    language = cells[1].strip()
                    location = cells[2].strip()
                    date_time = cells[3].strip()
                    seats = cells[4].strip()

                    results.append(
                        f"📅 **تاریخ و زمان:** `{date_time}`\n"
                        f"🪑 **ظرفیت باقی‌مانده:** `{seats}`\n"
                        f"📍 **مکان:** {location}"
                    )

            await browser.close()
            return results, None

        except Exception as e:
            logger.error(f"Playwright automation error: {e}")
            await browser.close()
            return None, f"خطا در دریافت اطلاعات از سایت NAATI: {str(e)}"

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 بررسی ظرفیت‌های آنلاین CCL", callback_data="check_dates")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! به ربات استعلام خودکار تاریخ‌های آزمون NAATI خوش آمدید.\n\n"
        "برای مشاهده جدیدترین ظرفیت‌های فعال، روی دکمه زیر کلیک کنید:",
        reply_markup=reply_markup
    )

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_dates":
        status_msg = await query.message.reply_text("🔄 در حال ورود به سایت NAATI و فیلتر کردن ظرفیت‌های فارسی...")
        
        dates, error = await fetch_naati_dates()

        if error:
            await status_msg.edit_text(f"❌ {error}")
        elif dates:
            output_text = "✅ **جدیدترین ظرفیت‌های یافت‌شده (CCL - Persian - Online):**\n\n" + "\n\n-------------------\n\n".join(dates)
            await status_msg.edit_text(output_text, parse_mode="Markdown")
        else:
            await status_msg.edit_text("ℹ️ در حال حاضر هیچ تاریخ آزمونی برای این فیلترها یافت نشد.")

def main():
    if not TOKEN:
        logger.error("خطا: متغیر BOT_TOKEN یافت نشد!")
        return

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(handle_button_click))

    logger.info("Bot started successfully...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
