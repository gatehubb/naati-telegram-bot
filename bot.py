import os
import asyncio
import logging
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from playwright.async_api import async_playwright

# ==============================================================================
# 1. ماژول استارتر (Starter Module)
# مسئول: دریافت دستورات اولیه، احراز هویت و شروع برنامه
# ==============================================================================
class StarterModule:
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "2377451")

    @staticmethod
    async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👋 به ربات پایش آزمون NAATI خوش آمدید.\n\n"
            "برای شروع دسترسی مدیریتی، دستور /admin را وارد کنید."
        )

    @staticmethod
    async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("🔑 لطفا رمز عبور را وارد کنید:\n`/admin PASSWORD`", parse_mode="Markdown")
            return
        
        entered_password = context.args[0]
        if entered_password == StarterModule.ADMIN_PASSWORD:
            context.user_data['is_admin'] = True
            await update.message.reply_text("✅ دسترسی مدیریت تایید شد.")
        else:
            await update.message.reply_text("❌ رمز عبور اشتباه است.")


# ==============================================================================
# 2. ماژول استخراج‌کننده (Extractor Module)
# مسئول: اتصال به سایت NAATI، ورود به حساب و استخراج اطلاعات آزمون‌ها
# ==============================================================================
class ExtractorModule:
    @staticmethod
    async def extract_naati_data(username, password):
        extracted_dates = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            page = await browser.new_page()
            try:
                logging.info("در حال اتصال به پنل NAATI...")
                # منطق ورود به سایت و کراول کردن تاریخ‌ها در این قسمت قرار می‌گیرد
            except Exception as e:
                logging.error(f"خطا در استخراج اطلاعات: {e}")
            finally:
                await browser.close()
                
        return extracted_dates


# ==============================================================================
# 3. ماژول نمایش‌دهنده (Display Module)
# مسئول: قالب‌بندی و نمایش اطلاعات استخراج‌شده به کاربر
# ==============================================================================
class DisplayModule:
    @staticmethod
    async def display_extracted_data(update: Update, context: ContextTypes.DEFAULT_TYPE, dates_list):
        if not dates_list:
            await update.message.reply_text("❌ هیچ تاریخ یا آزمون باز پیدا نشد.")
            return

        keyboard = []
        text = "📅 **تاریخ‌های یافت شده:**\n\n"
        
        for idx, item in enumerate(dates_list):
            text += f"{idx + 1}. {item['date']} - {item['location']}\n"
            keyboard.append([
                InlineKeyboardButton(f"پایش {item['date']}", callback_data=f"remind_{idx}")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


# ==============================================================================
# 4. ماژول ریمایندر (Reminder Module)
# مسئول: ثبت تاریخ انتخابی کاربر، بررسی دوره‌ای و ارسال نوتیفیکیشن
# ==============================================================================
class ReminderModule:
    @staticmethod
    async def handle_reminder_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        selected_data = query.data
        await query.edit_message_text("🔔 تاریخ مورد نظر برای پایش ذخیره شد.")

    @staticmethod
    async def start_reminder_loop(bot, interval=300):
        while True:
            try:
                # منطق بررسی دوره‌ای و ارسال نوتیفیکیشن در صورت باز شدن ظرفیت
                pass
            except Exception as e:
                logging.error(f"خطا در ماژول ریمایندر: {e}")
                
            await asyncio.sleep(interval)


# ==============================================================================
# تنظیمات وب‌سرور Flask (برای زنده نگه‌داشتن ربات در Render)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "NAATI Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)


# ==============================================================================
# نقطه شروع و اجرای اصلی برنامه
# ==============================================================================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN یافت نشد!")

    application = ApplicationBuilder().token(token).build()

    # اتصال فاز ۱: استارتر
    application.add_handler(CommandHandler("start", StarterModule.start_command))
    application.add_handler(CommandHandler("admin", StarterModule.admin_command))

    # اتصال فاز ۴: ریمایندر
    application.add_handler(CallbackQueryHandler(ReminderModule.handle_reminder_selection))

    # اجرای Flask در Thread جداگانه
    Thread(target=run_flask, daemon=True).start()

    # اجرای ربات
    application.run_polling()

if __name__ == "__main__":
    main()
