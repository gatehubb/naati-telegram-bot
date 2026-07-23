import asyncio
from playwright.async_api import async_playwright
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ConversationHandler, ContextTypes
)

# ==================== تنظیمات ====================
TELEGRAM_TOKEN = "8708901411:AAFrP287VRqln4V2dZZHYl1FUvZAWwzU97I"

LOCATION, MANUAL_DATE = range(2)
# =================================================

# تابع هوشمند برای فیلتر کردن سایت NAATI و خواندن جدول
async def fetch_filtered_naati_dates():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_dates = []
        try:
            print("در حال باز کردن سایت NAATI...")
            await page.goto("https://www.naati.com.au/test-date/", timeout=60000)
            await page.wait_for_selector("table", timeout=20000)

            # ۱. انتخاب Test Type (Credentialed Community Language Test)
            test_type_select = page.locator("select").nth(0)
            if await test_type_select.is_visible():
                await test_type_select.select_option(label="Credentialed Community Language Test")
                await page.wait_for_timeout(1000)

            # ۲. انتخاب Language (Persian)
            lang_select = page.locator("select").nth(1)
            if await lang_select.is_visible():
                await lang_select.select_option(label="Persian")
                await page.wait_for_timeout(1500)

            # ۳. استخراج داده‌های جدول اختصاصی فارسی
            await page.wait_for_selector("table tbody tr", timeout=15000)
            rows = await page.query_selector_all("table tbody tr")
            
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 5:
                    test_type = (await cells[0].inner_text()).strip()
                    lang = (await cells[1].inner_text()).strip()
                    loc = (await cells[2].inner_text()).strip()
                    date = (await cells[3].inner_text()).strip().split('\n')[0] # فقط تاریخ بدون ساعت
                    seats = (await cells[4].inner_text()).strip()
                    
                    all_dates.append({
                        "test_type": test_type,
                        "language": lang,
                        "location": loc,
                        "date": date,
                        "seats": seats
                    })
            
            await browser.close()
            return all_dates

        except Exception as e:
            print(f"خطا در دریافت اطلاعات از سایت: {e}")
            await browser.close()
            return []

# دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📋 انتخاب از تاریخ‌های موجود سایت"],
        ["✏️ وارد کردن تاریخ به صورت دستی"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "سلام! به ربات پایش ظرفیت NAATI (ویژه آزمون CCL زبان فارسی) خوش آمدید.\n\nلطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
        reply_markup=reply_markup
    )

# مدیریت منوی اصلی
async def handle_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📋 انتخاب از تاریخ‌های موجود سایت":
        await update.message.reply_text("در حال فیلتر کردن سایت روی (CCL + Persian) و دریافت تاریخ‌ها... لطفاً چند ثانیه صبر کنید ⏳")
        data = await fetch_filtered_naati_dates()
        
        if not data:
            await update.message.reply_text("متأسفانه نتوانستم اطلاعات را دریافت کنم. لطفاً مجدداً تلاش کنید.")
            return

        msg = "🗓 **تاریخ‌های فعال برای آزمون CCL فارسی در سایت:**\n\n"
        for item in data:
            msg += f"📍 مکان: `{item['location']}` | 📅 تاریخ: `{item['date']}` | 💺 ظرفیت: **{item['seats']}**\n"

        msg += "\nبرای شروع پایش خودکار یک تاریخ خاص، گزینه «وارد کردن تاریخ به صورت دستی» را انتخاب کنید."
        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "✏️ وارد کردن تاریخ به صورت دستی":
        await update.message.reply_text(
            "مرحله ۱ از ۲:\nلطفاً **مکان آزمون** را وارد کنید.\n(مثال: `ONLINE` یا `Sydney`)",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return LOCATION

# دریافت مکان در حالت دستی
async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    await update.message.reply_text(
        "مرحله ۲ از ۲:\nلطفاً **تاریخ مدنظر** را دقیقاً با فرمت زیر وارد کنید:\n\nفرمت صحیح: `DD-MM-YYYY`\nمثال: `13-08-2026`",
        parse_mode="Markdown"
    )
    return MANUAL_DATE

# دریافت تاریخ و شروع پایش
async def get_date_and_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_date = update.message.text
    target_location = context.user_data.get('location')
    chat_id = update.effective_chat.id

    await update.message.reply_text(
        f"✅ **تنظیمات پایش با موفقیت فعال شد!**\n\n"
        f"🎯 آزمون: `CCL Test (Persian)`\n"
        f"📍 مکان: `{target_location}`\n"
        f"📅 تاریخ: `{target_date}`\n\n"
        f"ربات هر ۵ دقیقه سایت را فیلتر کرده و بررسی می‌کند. به محض باز شدن ظرفیت به شما پیام خواهم داد.",
        parse_mode="Markdown"
    )

    asyncio.create_task(start_monitoring(chat_id, target_location, target_date, context))
    return ConversationHandler.END

# حلقه پایش خودکار در پس‌زمینه
async def start_monitoring(chat_id, location, date_str, context):
    while True:
        data = await fetch_filtered_naati_dates()
        for item in data:
            if date_str in item['date'] and location.lower() in item['location'].lower():
                try:
                    seats = int(item['seats'])
                    if seats > 0:
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"🚨 **ظرفیت باز شد!** 🚨\n\n"
                                 f"🎯 آزمون: CCL Persian\n"
                                 f"📍 مکان: {location}\n"
                                 f"📅 تاریخ: {date_str}\n"
                                 f"💺 ظرفیت خالی: **{seats}**\n\n"
                                 f"🔗 [ثبت نام فوری در سایت NAATI](https://www.naati.com.au/test-date/)",
                            parse_mode="Markdown"
                        )
                except ValueError:
                    pass
        await asyncio.sleep(300) # بررسی هر ۵ دقیقه یک بار

# لغو فرایند
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✏️ وارد کردن تاریخ به صورت دستی$"), handle_option)],
        states={
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)],
            MANUAL_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date_and_start)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("^📋 انتخاب از تاریخ‌های موجود سایت$"), handle_option))
    app.add_handler(conv_handler)

    print("ربات هوشمند NAATI بدون مشکل روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
