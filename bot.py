import asyncio
import re
from playwright.async_api import async_playwright
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler, ContextTypes
)

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

# تابع سریع و بهینه‌شده برای فیلتر کردن سایت NAATI
async def fetch_filtered_naati_dates(status_msg=None):
    async with async_playwright() as p:
        # متصل شدن با حالت بی‌سر و سریع
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        page = await context.new_page()

        # مسدود کردن بارگیری تصاویر و فونت‌ها برای افزایش سرعت ۵ برابری
        await page.route("**/*.{png,jpg,jpeg,svg,woff,woff2,css}", lambda route: route.abort())

        all_dates = []
        try:
            if status_msg:
                await status_msg.edit_text("⏳ [۱/۳] در حال باز کردن سایت NAATI...")
            
            # لود سریع بدون منتظر ماندن برای فونت‌ها و فایل‌های سنگین
            await page.goto("https://www.naati.com.au/test-date/", wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_selector("select", timeout=15000)

            if status_msg:
                await status_msg.edit_text("🔍 [۲/۳] در حال اعمال فیلتر (CCL Test و زبان فارسی)...")
            
            # انتخاب آزمون CCL
            test_type_select = page.locator("select").nth(0)
            if await test_type_select.is_visible():
                await test_type_select.select_option(label="Credentialed Community Language Test")
                await page.wait_for_timeout(500)

            # انتخاب زبان فارسی
            lang_select = page.locator("select").nth(1)
            if await lang_select.is_visible():
                await lang_select.select_option(label="Persian")
                await page.wait_for_timeout(800)

            if status_msg:
                await status_msg.edit_text("📊 [۳/۳] در حال استخراج جدول تاریخ‌ها...")

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

# دستور /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! به ربات پایش ظرفیت NAATI (ویژه CCL زبان فارسی) خوش آمدید.\n\nلطفاً یک گزینه را انتخاب کنید:",
        reply_markup=get_main_inline_keyboard()
    )
    return ConversationHandler.END

# کلیک روی دکمه‌های شیشه‌ای
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data in ["btn_main", "btn_reset"]:
        await query.message.reply_text("منوی اصلی:", reply_markup=get_main_inline_keyboard())
        return ConversationHandler.END

    if query.data == "btn_list":
        status_msg = await query.message.reply_text("⏳ در حال شروع ارتباط با سرور NAATI...")
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

    await update.message.reply_text(
        f"✅ **پایش خودکار فعال شد!**\n\n📍 مکان: `{target_location}`\n📅 تاریخ: `{target_date}`\n\nربات هر ۵ دقیقه سایت را چک کرده و در صورت وجود ظرفیت اطلاع می‌دهد.",
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
        status_msg = await context.bot.send_message(
            chat_id=chat_id, 
            text="🔄 در حال بررسی وضعیت ظرفیت NAATI..."
        )
        
        data = await fetch_filtered_naati_dates(status_msg)
        
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
                    reply_markup=get_reset_inline_keyboard()
                )

        if not found:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"ℹ️ تاریخ `{date_str}` در لیست حال حاضر سایت پیدا نشد.",
                parse_mode="Markdown",
                reply_markup=get_reset_inline_keyboard()
            )

        await asyncio.sleep(300)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=get_main_inline_keyboard())
    return ConversationHandler.END

def main():
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
