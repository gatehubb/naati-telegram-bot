import asyncio
import re
from playwright.async_api import async_playwright
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    filters, ConversationHandler, ContextTypes
)

TELEGRAM_TOKEN = "8708901411:AAEWDd3HcW-oAqyrAhfp4h6fhmLlO88eS-k"
LOCATION, MANUAL_DATE = range(2)

async def fetch_filtered_naati_dates():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_dates = []
        try:
            await page.goto("https://www.naati.com.au/test-date/", timeout=60000)
            await page.wait_for_selector("table", timeout=20000)

            test_type_select = page.locator("select").nth(0)
            if await test_type_select.is_visible():
                await test_type_select.select_option(label="Credentialed Community Language Test")
                await page.wait_for_timeout(1000)

            lang_select = page.locator("select").nth(1)
            if await lang_select.is_visible():
                await lang_select.select_option(label="Persian")
                await page.wait_for_timeout(1500)

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📋 انتخاب از تاریخ‌های موجود سایت"],
        ["✏️ وارد کردن تاریخ به صورت دستی"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "سلام! به ربات پایش ظرفیت NAATI (ویژه CCL زبان فارسی) خوش آمدید.\n\nلطفاً یک گزینه را انتخاب کنید:",
        reply_markup=reply_markup
    )

async def handle_option(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "📋 انتخاب از تاریخ‌های موجود سایت":
        await update.message.reply_text("در حال استخراج اطلاعات... ⏳")
        data = await fetch_filtered_naati_dates()
        
        if not data:
            await update.message.reply_text("متأسفانه دریافت اطلاعات ناموفق بود. مجدداً تلاش کنید.")
            return

        msg = "🗓 **تاریخ‌های فعال آزمون CCL فارسی:**\n\n"
        for item in data:
            msg += f"📍 مکان: `{item['location']}` | 📅 تاریخ: `{item['date']}` | 💺 ظرفیت: **{item['seats']}**\n"

        await update.message.reply_text(msg, parse_mode="Markdown")

    elif text == "✏️ وارد کردن تاریخ به صورت دستی":
        await update.message.reply_text(
            "مرحله ۱ از ۲:\nلطفاً **مکان آزمون** را وارد کنید.\n(مثال: `ONLINE` یا `Sydney`)",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown"
        )
        return LOCATION

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['location'] = update.message.text
    await update.message.reply_text(
        "مرحله ۲ از ۲:\nلطفاً **تاریخ مدنظر** را وارد کنید:\n(می‌توانید به صورت `03-09-2026` یا بخشی از تاریخ مثل `03` یا `September` وارد کنید)",
        parse_mode="Markdown"
    )
    return MANUAL_DATE

async def get_date_and_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_date = update.message.text
    target_location = context.user_data.get('location')
    chat_id = update.effective_chat.id

    await update.message.reply_text(
        f"✅ **پایش فعال شد!**\n\n📍 مکان: `{target_location}`\n📅 تاریخ: `{target_date}`\n\nربات هر ۵ دقیقه وضعیت را بررسی می‌کند و در صورت وجود ظرفیت هشدار می‌دهد.",
        parse_mode="Markdown"
    )

    asyncio.create_task(start_monitoring(chat_id, target_location, target_date, context))
    return ConversationHandler.END

# تابع نرمال‌سازی برای مقایسه هوشمند تاریخ و مکان
def is_match(user_input, site_text):
    clean_user = re.sub(r'[^a-zA-Z0-9]', '', user_input.lower())
    clean_site = re.sub(r'[^a-zA-Z0-9]', '', site_text.lower())
    return clean_user in clean_site or clean_site in clean_user

async def start_monitoring(chat_id, location, date_str, context):
    while True:
        data = await fetch_filtered_naati_dates()
        found = False
        for item in data:
            # بررسی تطابق مکان و تاریخ با قابلیت انعطاف‌پذیری
            if is_match(location, item['location']) and (date_str in item['date'] or is_match(date_str, item['date'])):
                found = True
                seats_str = item['seats']
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🔔 **گزارش پایش ظرفیت:**\n\n📍 مکان: {item['location']}\n📅 تاریخ: {item['date']}\n💺 وضعیت ظرفیت: **{seats_str}**\n\n🔗 [ثبت نام در سایت NAATI](https://www.naati.com.au/test-date/)",
                    parse_mode="Markdown"
                )
        if not found:
            print(f"تاریخ {date_str} یا مکان {location} در جدول یافت نشد.")

        await asyncio.sleep(300) # هر ۵ دقیقه

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

    print("ربات روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
