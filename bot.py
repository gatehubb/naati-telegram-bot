import os
import logging
import asyncio
from typing import Optional, List, Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

# تنظیمات Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# کلاس مدیریت وضعیت لحظه‌ای به کاربر (Status Tracker)
# ---------------------------------------------------------
class StatusTracker:
    def __init__(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.update = update
        self.context = context
        self.message = None
        self.steps: List[str] = []

    async def start(self, initial_text: str):
        if self.update.callback_query:
            self.message = await self.update.callback_query.message.reply_text(initial_text)
        elif self.update.message:
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

        full_text = "🔍 **در حال استعلام آنلاین ظرفیت‌های NAATI...**\n\n" + "\n".join(self.steps)
        if self.message:
            try:
                await self.message.edit_text(full_text, parse_mode="Markdown")
            except Exception:
                pass

def simplify_error_message(raw_err: str) -> str:
    if "Timeout" in raw_err:
        return "تایم‌آوت در پاسخگویی منوهای سایت NAATI"
    elif "net::ERR_" in raw_err:
        return "خطای شبکه در برقراری ارتباط با سرور NAATI"
    return "خطای غیرمنتظره در پردازش اطلاعات"

# ---------------------------------------------------------
# اسکرپر Playwright برای NAATI
# ---------------------------------------------------------
async def fetch_filtered_naati_dates(tracker: Optional[StatusTracker] = None):
    async with async_playwright() as p:
        if tracker:
            await tracker.update("راه‌اندازی موتور مرورگر اختصاصی", "in_progress")

        browser: Optional[Browser] = None
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None

        try:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-zygote",
                    "--single-process",
                ],
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()

            if tracker:
                await tracker.update("راه‌اندازی موتور مرورگر اختصاصی", "success")
                await tracker.update("بارگذاری صفحه استعلام NAATI", "in_progress")

            # ۱. باز کردن صفحه با wait_until سریع
            await page.goto(
                "https://www.naati.com.au/test-date/",
                wait_until="domcontentloaded",
                timeout=45000,
            )

            # ۲. مدیریت بنر کوکی
            try:
                cookie_btn = page.locator("button:has-text('I Agree'), #onetrust-accept-btn-handler")
                if await cookie_btn.count() > 0:
                    await cookie_btn.first.click(timeout=3000)
            except Exception:
                pass

            if tracker:
                await tracker.update("بارگذاری صفحه استعلام NAATI", "success")
                await tracker.update("تنظیم فیلتر نوع آزمون (CCL)", "in_progress")

            # ۳. انتخاب نوع آزمون (CCL Test)
            select_ccl = page.locator("select").nth(0)
            await select_ccl.wait_for(state="attached", timeout=15000)
            await select_ccl.select_option(label="Credentialed Community Language Test")

            if tracker:
                await tracker.update("تنظیم فیلتر نوع آزمون (CCL)", "success")
                await tracker.update("اعمال فیلتر زبان (Persian)", "in_progress")

            # ۴. انتظار برای فعال شدن منوی دوم و انتخاب زبان
            await page.wait_for_function(
                '() => { const s = document.querySelectorAll("select"); return s.length > 1 && !s[1].disabled; }',
                timeout=25000
            )
            select_lang = page.locator("select").nth(1)
            await select_lang.select_option(label="Persian")

            if tracker:
                await tracker.update("اعمال فیلتر زبان (Persian)", "success")
                await tracker.update("استخراج و تحلیل جدول داده‌ها", "in_progress")

            # ۵. استخراج جدول داده‌ها
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
                await tracker.update("استخراج و تحلیل جدول داده‌ها", "success")

            return all_dates, None

        except Exception as e:
            raw_err = str(e)
            logger.error(f"Error in NAATI Scraper: {raw_err}")
            simple_err = simplify_error_message(raw_err)
            if tracker and tracker.steps:
                last_step = tracker.steps[-1].replace("⏳ ", "").replace("...", "")
                await tracker.update(last_step, "failed", simple_err)
            return None, simple_err

        finally:
            if page:
                await page.close()
            if context:
                await context.close()
            if browser:
                await browser.close()

# ---------------------------------------------------------
# هندلرهای ربات تلگرام
# ---------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("📅 بررسی ظرفیت‌های آنلاین CCL", callback_data="check_dates")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(
            "سلام! به ربات استعلام خودکار تاریخ‌های آزمون NAATI خوش آمدید.\n"
            "برای مشاهده جدیدترین ظرفیت‌های فعال زبان فارسی، روی دکمه زیر کلیک کنید:",
            reply_markup=reply_markup
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()

    if query.data == "check_dates":
        tracker = StatusTracker(update, context)
        await tracker.start("🔄 در حال شروع پردازش...")

        dates, error = await fetch_filtered_naati_dates(tracker)

        if error:
            await query.message.reply_text(f"❌ **عملیات با خطا مواجه شد:**\n{error}", parse_mode="Markdown")
            return

        if not dates:
            await query.message.reply_text("ℹ️ در حال حاضر هیچ ظرفیت فعالی برای زبان فارسی ثبت نشده است.")
            return

        result_text = "📅 **جدول ظرفیت‌های آنلاین آزمون NAATI (Persian):**\n\n"
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
# سرور Dummy HTTP جهت پاس کردن Health Check در Render
# ---------------------------------------------------------
async def start_dummy_http_server():
    port = int(os.environ.get("PORT", 8080))
    async def handle_client(reader, writer):
        response = "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK"
        writer.write(response.encode('utf-8'))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "0.0.0.0", port)
    logger.info(f"Dummy HTTP Server running on port {port} for Render Health Check.")
    return server

# ---------------------------------------------------------
# نقطه ورود اصلی برنامه
# ---------------------------------------------------------
async def main():
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is missing!")
        return

    # اجرای سرور وب برای Health Check
    http_server = await start_dummy_http_server()

    # ساخت ربات تلگرام
    application = ApplicationBuilder().token(bot_token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CallbackQueryHandler(button_handler))

    await application.initialize()
    await application.start()
    
    # حذف آپدیت‌های آویزان جهت جلوگیری از Conflict
    await application.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    logger.info("Telegram Bot started successfully.")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Stopping bot and HTTP server...")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        http_server.close()
        await http_server.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
