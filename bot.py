import logging
import asyncio
import os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from playwright.async_api import async_playwright

# تنظیمات Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ---------------------------------------------------------
# کلاس مدیریت و ارسال وضعیت به کاربر (Status Tracker)
# ---------------------------------------------------------
class StatusTracker:
    def __init__(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.update = update
        self.context = context
        self.message = None
        self.steps = []

    async def start(self, initial_text: str):
        if self.update.callback_query:
            self.message = await self.update.callback_query.message.reply_text(initial_text)
        else:
            self.message = await self.update.message.reply_text(initial_text)

    async def update(self, step_name: str, status: str, detail: str = None):
        icon = "⏳" if status == "in_progress" else "✅" if status == "success" else "❌"
        text_line = f"{icon} {step_name}"
        if detail:
            text_line += f" ({detail})"

        found = False
        for i, s in enumerate(self.steps):
            if step_name in s:
                self.steps[i] = text_line
                found = True
                break
        if not found:
            self.steps.append(text_line)

        full_text = "🔍 **در حال بررسی ظرفیت‌های آزمون NAATI...**\n\n" + "\n".join(self.steps)
        if self.message:
            try:
                await self.message.edit_text(full_text, parse_mode="Markdown")
            except Exception:
                pass

def simplify_error_message(raw_err: str) -> str:
    if "Timeout" in raw_err:
        return "تایم‌آوت در پاسخگویی منوهای سایت NAATI"
    return "خطا در ارتباط با سرور NAATI"

# ---------------------------------------------------------
# تابع اسکرپ و استخراج تاریخ‌های NAATI با Playwright
# ---------------------------------------------------------
async def fetch_filtered_naati_dates(tracker: StatusTracker = None):
    async with async_playwright() as p:
        if tracker:
            await tracker.update("راه‌اندازی مرورگر اختصاصی", "in_progress")

        browser = None
        context = None
        try:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context()
            page = await context.new_page()

            if tracker:
                await tracker.update("راه‌اندازی مرورگر اختصاصی", "success")
                await tracker.update("باز کردن سایت NAATI", "in_progress")

            # ۱. بارگذاری سریع صفحه
            await page.goto(
                "https://www.naati.com.au/test-date/",
                wait_until="domcontentloaded",
                timeout=45000,
            )

            # ۲. بستن بنر کوکی در صورت وجود
            try:
                cookie_btn = page.locator("button:has-text('I Agree'), #onetrust-accept-btn-handler")
                if await cookie_btn.count() > 0:
                    await cookie_btn.first.click(timeout=3000)
            except Exception:
                pass

            if tracker:
                await tracker.update("باز کردن سایت NAATI", "success")
                await tracker.update("انتخاب نوع آزمون (CCL Test)", "in_progress")

            # ۳. انتخاب نوع آزمون
            select_ccl = page.locator("select").nth(0)
            await select_ccl.wait_for(state="attached", timeout=15000)
            await select_ccl.select_option(label="Credentialed Community Language Test")

            if tracker:
                await tracker.update("انتخاب نوع آزمون (CCL Test)", "success")
                await tracker.update("اعمال فیلتر زبان (Persian)", "in_progress")

            # ۴. انتظار برای فعال شدن منوی زبان (حل تایم‌آوت)
            select_lang = page.locator("select").nth(1)
            await page.wait_for_function(
                '() => !document.querySelectorAll("select")[1].disabled', 
                timeout=25000
            )
            await select_lang.select_option(label="Persian")

            if tracker:
                await tracker.update("اعمال فیلتر زبان (Persian)", "success")
                await tracker.update("استخراج و تحلیل جدول ظرفیت‌ها", "in_progress")

            # ۵. استخراج داده‌ها از جدول
            await page.wait_for_selector("table tbody tr", timeout=20000)
            rows = await page.query_selector_all("table tbody tr")

            all_dates = []
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 5:
                    test_type = (await cells[0].inner_text()).strip()
                    lang = (await cells[1].inner_text()).strip()
                    loc = (await cells[2].inner_text()).strip()
                    raw_date = (await cells[3].inner_text()).strip().split("\n")[0]
                    seats = (await cells[4].inner_text()).strip()

                    all_dates.append({
                        "test_type": test_type,
                        "language": lang,
                        "location": loc,
                        "date": raw_date,
                        "seats": seats,
                    })

            if tracker:
                await tracker.update("استخراج و تحلیل جدول ظرفیت‌ها", "success")

            return all_dates, None

        except Exception as e:
            raw_err = str(e)
            logging.error(f"Error fetching data: {raw_err}")
            simple_err = simplify_error_message(raw_err)
            if tracker and tracker.steps:
                last_step = tracker.steps[-1].replace("⏳ ", "").replace("...", "")
                await tracker.update(last_step, "failed", simple_err)
            return None, simple_err
        finally:
            if context:
                await context.close()
            if browser:
                await browser.close()

# ---------------------------------------------------------
# دستورات و هندلرهای ربات تلگرام
# ---------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📅 بررسی تاریخ‌های آزمون CCL", callback_data="check_dates")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سلام! به ربات استعلام تاریخ‌های آزمون NAATI خوش آمدید.\n"
        "برای مشاهده آخرین ظرفیت‌های موجود روی دکمه زیر کلیک کنید:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "check_dates":
        tracker = StatusTracker(update, context)
        await tracker.start("🔄 در حال شروع پردازش...")

        dates, error = await fetch_filtered_naati_dates(tracker)

        if error:
            await query.message.reply_text(f"❌ **بررسی با خطا مواجه شد:**\n{error}", parse_mode="Markdown")
            return

        if not dates:
            await query.message.reply_text("ℹ️ در حال حاضر هیچ تاریخی برای زبان فارسی یافت نشد.")
            return

        result_text = "📅 **تاریخ‌های فعال آزمون NAATI (زبان فارسی):**\n\n"
        for item in dates:
            result_text += (
                f"🔹 **تاریخ:** `{item['date']}`\n"
                f"📍 **نوع/مکان:** {item['location']}\n"
                f"🪑 **صندلی خالی:** {item['seats']}\n"
                f"───────────────\n"
            )

        keyboard = [[InlineKeyboardButton("🔄 بروزرسانی مجدد", callback_data="check_dates")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(result_text, parse_mode="Markdown", reply_markup=reply_markup)

# ---------------------------------------------------------
# اجرای اصلی ربات (جلوگیری از Conflict)
# ---------------------------------------------------------
if __name__ == "__main__":
    BOT_TOKEN = os.getenv("BOT_TOKEN")

    if not BOT_TOKEN:
        print("خطا: مقدار BOT_TOKEN در متغیرهای محیطی تعریف نشده است!")
    else:
        app = ApplicationBuilder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CallbackQueryHandler(button_handler))

        print("ربات با موفقیت روشن شد...")
        
        # drop_pending_updates=True باعث می‌شود اتصالات قبلی فوراً باطل شوند و Conflict رخ ندهد
        app.run_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
