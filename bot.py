import os
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# تنظیمات سیستم ثبت لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")

def fetch_ccl_dates():
    """دریافت مستقیم و سریع اطلاعات از سایت cclpanel"""
    url = "https://cclpanel.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, f"خطا در برقراری ارتباط با سایت (کد وضعیت: {response.status_code})"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        dates_info = []

        for row in rows:
            text = row.get_text(separator=' ', strip=True)
            if "Persian" in text or "فارسی" in text:
                dates_info.append(text)

        return dates_info, None
    except requests.exceptions.Timeout:
        return None, "زمان پاسخ‌دهی سایت به پایان رسید (Timeout)."
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return None, "خطایی در استخراج اطلاعات رخ داد."

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ارسال پیام خوش‌آمدگویی همراه با دکمه شیشه‌ای"""
    keyboard = [
        [InlineKeyboardButton("📅 بررسی ظرفیت‌های آنلاین CCL", callback_data="check_dates")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! به ربات استعلام خودکار تاریخ‌های آزمون NAATI خوش آمدید.\n\n"
        "برای مشاهده جدیدترین ظرفیت‌های فعال زبان فارسی، روی دکمه زیر کلیک کنید:",
        reply_markup=reply_markup
    )

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت کلیک دکمه و به‌روزرسانی وضعیت"""
    query = update.callback_query
    await query.answer()

    if query.data == "check_dates":
        # ارسال پیام اولیه و ذخیره آن برای ویرایش بعدی
        status_msg = await query.message.reply_text("🔄 در حال اتصال و استخراج اطلاعات ظرفیت‌ها...")
        
        dates, error = fetch_ccl_dates()

        if error:
            await status_msg.edit_text(f"❌ {error}")
        elif dates:
            formatted_dates = "\n\n".join([f"🔹 {d}" for d in dates])
            await status_msg.edit_text(f"✅ **جدیدترین ظرفیت‌های موجود:**\n\n{formatted_dates}", parse_mode="Markdown")
        else:
            await status_msg.edit_text("ℹ️ در حال حاضر هیچ ظرفیت جدیدی برای زبان فارسی یافت نشد.")

def main():
    """اجرای اصلی ربات"""
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
