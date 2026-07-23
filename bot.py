import asyncio
import re
from playwright.async_api import async_playwright
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ConversationHandler, ContextTypes
)

# ==================== تنظیمات ====================
TELEGRAM_TOKEN = "8708901411:AAEWDd3HcW-oAqyrAhfp4h6fhmLlO88eS-k"

LOCATION, MANUAL_DATE = range(2)

def get_main_keyboard():
    keyboard = [
        ["📋 انتخاب از تاریخ‌های موجود سایت"],
        ["✏️ وارد کردن تاریخ به صورت دستی"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_reset_keyboard():
    keyboard = [
        ["🔄 ریست و تنظیم مجدد"],
        ["🔙 بازگشت به منوی اصلی"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# تابع هوشمند برای فیلتر کردن سایت NAATI و خواندن جدول به همراه پیام‌های Log
async def fetch_filtered_naati_dates(status_msg=None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_dates = []
        try:
            if status_msg:
                await status_msg.edit_text("⏳ [۱/۴] در حال باز کردن سایت NAATI...")
            await page.goto("https://www.naati.com.au/test-date/", timeout=60000)
            await page.wait_for_selector("table", timeout=20000)

            if status_msg:
                await status_msg.edit_text("🔍 [۲/۴] در حال اعمال فیلتر (CCL Test)...")
            test_type_select = page.locator("select").nth(0)
            if await test_type_select.is_visible():
                await test_type_select.select_option(label="Credentialed Community Language Test")
                await page.wait_for_timeout(1000)

            if status_msg:
                await status_msg.edit_text("🇮🇷 [۳/۴] در حال اعمال فیلتر زبان فارسی (Persian)...")
            lang_select = page.locator("select").nth(1)
            if await lang_select.is_visible():
                await lang_select.select_option(label="Persian")
                await page.wait_for_timeout(1500)

            if status_msg:
                await status_msg.edit_text("📊 [۴/۴] در حال استخراج و تحلیل جدول تاریخ‌ها...")

            await page.wait_for_selector("table tbody tr", timeout=15000)
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

# دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! به ربات پایش ظرفیت NAATI (ویژه CCL زبان فارسی) خوش آمدید.\n\nلطفاً یک گزینه را انتخاب کنید:",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

# مدیریت گزینه‌ها و منو
async def handle_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text in ["🔙 بازگشت به منوی اصلی", "🔄 ریست و تنظیم مجدد"]:
        await update.message.reply_text("منوی اصلی فراخوانی شد:", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    if text == "📋 انتخاب از تاریخ‌های موجود سایت":
        status_msg = await update.message.reply_text("⏳ در حال شروع ارتباط با سرور NAATI...")
        data = await fetch_filtered_naati_dates(status_msg)
        
        # پاک کردن پیام لاگ موقت
        try:
            await status_msg.delete()
        except Exception:
            pass

        if not data:
            await update.message.reply_text(
                "❌ متأسفانه دریافت اطلاعات ناموفق بود. لطفاً دوباره تلاش کنید.",
                reply_markup=get_reset_keyboard()
            )
            return

        msg = "🗓 **تاریخ‌های فعال آزمون CCL فارسی در سایت:**\n\n"
        for item in data:
            msg += f"📍 مکان: `{item['location']}` | 📅 تاریخ: `{item['date']}` | 💺 ظرفیت: **{item['seats']}**\n"

        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_reset_keyboard())

    elif text == "✏️ وارد کردن تاریخ به صورت دستی":
        await update.message.reply_text(
            "مرحله ۱ از ۲:\nلطفاً **مکان آزمون** را وارد کنید.\n(مثال: `ONLINE` یا `Sydney`)",
            reply_markup=get_reset_keyboard(),
            parse_mode="Markdown"
        )
        return LOCATION

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text in ["🔙 بازگشت به منوی اصلی", "🔄 ریست و تنظیم مجدد"]:
        await update.message.reply_text("عملیات لغو شد. منوی اصلی:", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    context.user_data['location'] = text
    await update.message.reply_text(
        "مرحله ۲ از ۲:\nلطفاً **تاریخ مدنظر** را وارد کنید:\n(مثال: `03-09-2026` یا بخشی از تاریخ مثل `September` یا `03`)",
        reply_markup=get_reset_keyboard(),
        parse_mode="Markdown"
    )
    return MANUAL_DATE

async def get_date_and_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_date = update.message.text
    if target_date in ["🔙 بازگشت به منوی اصلی", "🔄 ریست و تنظیم مجدد"]:
        await update.message.reply_text("عملیات لغو شد. منوی اصلی:", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    target_location = context.user_data.get('location')
    chat_id = update.effective_chat.id

    await update.message.reply_text(
        f"✅ **پایش خودکار فعال شد!**\n\n📍 مکان: `{target_location}`\n📅 تاریخ: `{target_date}`\n\nربات هر ۵ دقیقه سایت را چک کرده و تغییرات را اطلاع می‌دهد.",
        parse_mode="Markdown",
        reply_markup=get_reset_keyboard()
    )

    # اجرای پایش در پس‌زمینه
    asyncio.create_task(start_monitoring(chat_id, target_location, target_date, context))
    return ConversationHandler.END

# تابع مقایسه انعطاف‌پذیر
def is_match(user_input, site_text):
    clean_user = re.sub(r'[^a-zA-Z0-9]', '', user_input.lower())
    clean_site = re.sub(r'[^a-zA-Z0-9]', '', site_text.lower())
    return clean_user in clean_site or clean_site in clean_user

# حلقه پایش خودکار با لاگ موقت
async def start_monitoring(chat_id, location, date_str, context):
    while True:
        status_msg = await context.bot.send_message(
            chat_id=chat_id, 
            text="🔄 در حال بررسی وضعیت ظرفیت NAATI..."
        )
        
        data = await fetch_filtered_naati_dates(status_msg)
        
        # پاک کردن لاگ بررسی موقت پس از اتمام
        try:
            await status_msg.delete()
        except Exception:
            pass

        found = False
        for item in data:
            if is_match(location, item['location']) and (date_str in item['date'] or is_match(date_str, item['date'])):
                found = True
                seats_str = item['seats']
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔔 **گزارش پایش ظرفیت:**\n\n📍 مکان: {item['location']}\n📅 تاریخ: {item['date']}\n💺 وضعیت ظرفیت: **{seats_str}**\n\n🔗 [ثبت نام در سایت NAATI](https://www.naati.com.au/test-date/)",
                    parse_mode="Markdown",
                    reply_markup=get_reset_keyboard()
                )

        if not found:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"ℹ️ تاریخ `{date_str}` با مکان `{location}` در لیست حال حاضر سایت پیدا نشد.",
                parse_mode="Markdown",
                reply_markup=get_reset_keyboard()
            )

        await asyncio.sleep(300) # هر ۵ دقیقه

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=get_main_keyboard())
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^✏️ وارد کردن تاریخ به صورت دستی$"), handle_option)
        ],
        states={
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)],
            MANUAL_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date_and_start)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            MessageHandler(filters.Regex("^(🔙 بازگشت به منوی اصلی|🔄 ریست و تنظیم مجدد)$"), start)
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^📋 انتخاب از تاریخ‌های موجود سایت$"), handle_option))
    app.add_handler(MessageHandler(filters.Regex("^(🔙 بازگشت به منوی اصلی|🔄 ریست و تنظیم مجدد)$"), start))
    app.add_handler(conv_handler)

    print("ربات روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
