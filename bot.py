import asyncio
import re
import os
import sys
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# ==================== خودکارسازی نصب مرورگر ====================
def ensure_playwright_browsers():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
    
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    except Exception as e:
        print(f"Playwright install log: {e}")

ensure_playwright_browsers()

from playwright.async_api import async_playwright
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    MessageHandler, filters, ConversationHandler, ContextTypes
)

# سرور ساختگی برای زنده نگه داشتن پورت Render
class DummyServer(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        return

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DummyServer)
    server.serve_forever()

# ==================== تنظیمات و دیتابیس حافظه ====================
TELEGRAM_TOKEN = "8708901411:AAGerrcWjeVS2CvQ3dHI4NLs6uO8RgE3uDU"
DEFAULT_LOCATION = "ONLINE"
WAITING_FOR_DATE = 1

# ذخیره درخواست‌های کاربران
# { chat_id: {"mode": "single/multi/manual", "target_date": "...", "selected_dates": [...], "target_index": int, "last_seats": {}, "cached_snapshot": [...]} }
USER_MONITORS = {}
USER_TEMP_SELECTIONS = {}

def get_main_inline_keyboard():
    keyboard = [
        [InlineKeyboardButton("📋 انتخاب از تاریخ‌های موجود سایت", callback_data="btn_list")],
        [InlineKeyboardButton("✏️ وارد کردن تاریخ به صورت دستی", callback_data="btn_manual")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_single_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_mode_selection_keyboard():
    """دکمه‌های انتخاب حالت تکی و چندتایی کنار هم"""
    keyboard = [
        [
            InlineKeyboardButton("🎯 انتخاب تکی", callback_data="mode_single"),
            InlineKeyboardButton("☑️ انتخاب چندتایی", callback_data="mode_multi")
        ],
        [InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

class StatusTracker:
    def __init__(self, message):
        self.message = message
        self.steps = []

    async def update(self, step_text, status="in_progress", error_msg=None):
        if status == "in_progress":
            self.steps.append(f"⏳ {step_text}...")
        elif status == "success":
            if self.steps:
                self.steps[-1] = f"✅ {step_text}"
        elif status == "failed":
            if self.steps:
                self.steps[-1] = f"❌ {step_text}"
            if error_msg:
                self.steps.append(f"\n⚠️ **علت خطا:**\n`{error_msg[:200]}`")

        full_text = "⚙️ **وضعیت پردازش:**\n\n" + "\n".join(self.steps)
        try:
            await self.message.edit_text(full_text, parse_mode="Markdown")
        except Exception:
            pass

    async def delete_status_message(self):
        try:
            await self.message.delete()
        except Exception:
            pass

async def fetch_filtered_naati_dates(tracker: StatusTracker = None):
    async with async_playwright() as p:
        if tracker:
            await tracker.update("راه‌اندازی مرورگر اختصاصی", "in_progress")
        
        browser = None
        try:
            browser = await p.chromium.launch(
                headless=True, 
                args=[
                    "--no-sandbox", 
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu"
                ]
            )
            page = await browser.new_page()
            if tracker:
                await tracker.update("راه‌اندازی مرورگر اختصاصی", "success")
        except Exception as e:
            if tracker:
                await tracker.update("راه‌اندازی مرورگر اختصاصی", "failed", str(e))
            if browser:
                await browser.close()
            return None

        all_dates = []
        try:
            if tracker:
                await tracker.update("باز کردن سایت NAATI", "in_progress")
            await page.goto("https://www.naati.com.au/test-date/", wait_until="networkidle", timeout=45000)
            if tracker:
                await tracker.update("باز کردن سایت NAATI", "success")

            if tracker:
                await tracker.update("انتخاب نوع آزمون (CCL Test)", "in_progress")
            selects = page.locator("select")
            await selects.nth(0).wait_for(timeout=10000)
            await selects.nth(0).select_option(label="Credentialed Community Language Test")
            await page.wait_for_timeout(1000)
            if tracker:
                await tracker.update("انتخاب نوع آزمون (CCL Test)", "success")

            if tracker:
                await tracker.update("اعمال فیلتر زبان (Persian)", "in_progress")
            await selects.nth(1).select_option(label="Persian")
            await page.wait_for_timeout(1500)
            if tracker:
                await tracker.update("اعمال فیلتر زبان (Persian)", "success")

            if tracker:
                await tracker.update("استخراج و تحلیل جدول ظرفیت‌ها", "in_progress")
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
            
            if tracker:
                await tracker.update("استخراج و تحلیل جدول ظرفیت‌ها", "success")
            
            await browser.close()
            return all_dates

        except Exception as e:
            error_details = str(e)
            print(f"Error fetching data: {error_details}")
            if tracker:
                last_step_text = tracker.steps[-1].replace("⏳ ", "").replace("...", "") if tracker.steps else "پردازش"
                await tracker.update(last_step_text, "failed", error_details)
            if browser:
                await browser.close()
            return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! به ربات پایش ظرفیت NAATI (ویژه CCL زبان فارسی) خوش آمدید.\n\nلطفاً یک گزینه را انتخاب کنید:",
        reply_markup=get_main_inline_keyboard()
    )
    return ConversationHandler.END

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id

    if query.data == "btn_main":
        await query.message.reply_text("منوی اصلی:", reply_markup=get_main_inline_keyboard())
        return ConversationHandler.END

    if query.data == "btn_list":
        status_msg = await query.message.reply_text("⚙️ **در حال دریافت اطلاعات...**", parse_mode="Markdown")
        tracker = StatusTracker(status_msg)
        
        data = await fetch_filtered_naati_dates(tracker)
        await tracker.delete_status_message()

        if not data:
            await query.message.reply_text(
                "❌ دریافت اطلاعات ناموفق بود. مجدداً تلاش کنید.",
                reply_markup=get_single_main_menu_keyboard()
            )
            return ConversationHandler.END

        # ذخیره کش تاریخ‌ها برای کاربر
        context.user_data['cached_dates'] = data

        msg = "🗓 **تاریخ‌های فعال آزمون CCL فارسی در سایت:**\n\n"
        for idx, item in enumerate(data, 1):
            msg += f"{idx}. 📍 `{item['location']}` | 📅 `{item['date']}` | 💺 **{item['seats']}**\n"

        msg += "\n👇 **لطفاً نحوه انتخاب تاریخ برای پایش را مشخص کنید:**"
        await query.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_mode_selection_keyboard())
        return ConversationHandler.END

    # حالت انتخاب تکی
    elif query.data == "mode_single":
        data = context.user_data.get('cached_dates', [])
        if not data:
            await query.message.reply_text("اطلاعات منقضی شده، لطفاً دوباره لیست تاریخ‌ها را دریافت کنید.", reply_markup=get_single_main_menu_keyboard())
            return ConversationHandler.END

        keyboard = []
        for idx, item in enumerate(data[:6]):  # 6 تاریخ اول
            keyboard.append([InlineKeyboardButton(f"📅 {item['date']} ({item['seats']})", callback_data=f"select_single_{idx}")])
        keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")])

        await query.message.reply_text("🎯 **یک تاریخ را از ۶ مورد اول انتخاب کنید:**", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    # پردازش انتخاب تکی
    elif query.data.startswith("select_single_"):
        idx = int(query.data.split("_")[-1])
        data = context.user_data.get('cached_dates', [])
        if idx >= len(data):
            return ConversationHandler.END

        selected_item = data[idx]
        USER_MONITORS[chat_id] = {
            "mode": "single",
            "target_date": selected_item['date'],
            "target_index": idx,
            "location": selected_item['location'],
            "last_seats": {selected_item['date']: selected_item['seats']},
            "cached_snapshot": [d['date'] for d in data]  # برای تشخیص تاریخ‌های جدید
        }

        await query.message.reply_text(
            f"✅ **پایش تکی فعال شد!**\n\n📅 تاریخ انتخابی: `{selected_item['date']}`\n💺 ظرفیت فعلی: **{selected_item['seats']}**\n\nℹ️ *شرط پایش:* تغییر ظرفیت این تاریخ + باز شدن هرگونه تاریخ جدید در محدوده ۴ سطر بالاتر/پایین‌تر.",
            parse_mode="Markdown",
            reply_markup=get_single_main_menu_keyboard()
        )
        return ConversationHandler.END

    # حالت انتخاب چندتایی
    elif query.data == "mode_multi":
        USER_TEMP_SELECTIONS[chat_id] = set()
        await render_multi_select_menu(query, context, chat_id)
        return ConversationHandler.END

    # چگونگی تیک زدن/برداشتن چندتایی
    elif query.data.startswith("toggle_multi_"):
        idx = int(query.data.split("_")[-1])
        selections = USER_TEMP_SELECTIONS.get(chat_id, set())

        if idx in selections:
            selections.remove(idx)
        else:
            if len(selections) >= 4:
                await query.answer("⚠️ حداکثر می‌توانید ۴ تاریخ را انتخاب کنید!", show_alert=True)
                return ConversationHandler.END
            selections.add(idx)

        USER_TEMP_SELECTIONS[chat_id] = selections
        await render_multi_select_menu(query, context, chat_id, edit=True)
        return ConversationHandler.END

    # ثبت نهایی چندتایی
    elif query.data == "submit_multi":
        selections = USER_TEMP_SELECTIONS.get(chat_id, set())
        data = context.user_data.get('cached_dates', [])

        if not selections:
            await query.answer("⚠️ لطفاً حداقل یک تاریخ را انتخاب کنید!", show_alert=True)
            return ConversationHandler.END

        selected_items = [data[i] for i in selections if i < len(data)]
        selected_dates = [item['date'] for item in selected_items]
        last_seats = {item['date']: item['seats'] for item in selected_items}

        USER_MONITORS[chat_id] = {
            "mode": "multi",
            "selected_dates": selected_dates,
            "location": DEFAULT_LOCATION,
            "last_seats": last_seats
        }

        dates_str = "\n".join([f"• `{d}`" for d in selected_dates])
        await query.message.reply_text(
            f"✅ **پایش چندتایی برای {len(selected_dates)} تاریخ فعال شد:**\n\n{dates_str}\n\nℹ️ *شرط پایش:* اعلام هرگونه تغییر ظرفیت در این موارد.",
            parse_mode="Markdown",
            reply_markup=get_single_main_menu_keyboard()
        )
        USER_TEMP_SELECTIONS.pop(chat_id, None)
        return ConversationHandler.END

    elif query.data == "btn_manual":
        await query.message.reply_text(
            f"📍 مکان آزمون به صورت پیش‌فرض **{DEFAULT_LOCATION}** در نظر گرفته شد.\n\nلطفاً **تاریخ مدنظر** را وارد کنید:\n(مثال: `03-09-2026` یا بخشی از تاریخ مثل `September` یا `03`)",
            reply_markup=get_single_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        return WAITING_FOR_DATE

async def render_multi_select_menu(query, context, chat_id, edit=False):
    data = context.user_data.get('cached_dates', [])
    selections = USER_TEMP_SELECTIONS.get(chat_id, set())

    keyboard = []
    for idx, item in enumerate(data[:8]):  # 8 تاریخ اول
        check = "✅ " if idx in selections else "[ ] "
        keyboard.append([InlineKeyboardButton(f"{check}{item['date']} ({item['seats']})", callback_data=f"toggle_multi_{idx}")])

    keyboard.append([InlineKeyboardButton(f"📥 ثبت نهایی ({len(selections)}/4)", callback_data="submit_multi")])
    keyboard.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="btn_main")])

    text = "☑️ **تاریخ‌های مدنظر را انتخاب کنید (حداکثر ۴ مورد):**"
    if edit:
        try:
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        except Exception:
            pass
    else:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def get_date_and_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_date = update.message.text
    chat_id = update.effective_chat.id

    status_msg = await update.message.reply_text("⚙️ **در حال بررسی...**", parse_mode="Markdown")
    tracker = StatusTracker(status_msg)

    data = await fetch_filtered_naati_dates(tracker)
    await tracker.delete_status_message()

    if not data:
        await update.message.reply_text("❌ عملیات پایش متوقف شد.", reply_markup=get_single_main_menu_keyboard())
        return ConversationHandler.END

    found_item = next((item for item in data if is_match(target_date, item['date'])), None)
    initial_seats = found_item['seats'] if found_item else "یافت نشد"

    USER_MONITORS[chat_id] = {
        "mode": "manual",
        "target_date": target_date,
        "location": DEFAULT_LOCATION,
        "last_seats": {target_date: initial_seats}
    }

    await update.message.reply_text(
        f"✅ **پایش دستی برای تاریخ `{target_date}` فعال شد!**\n\n💺 وضعیت فعلی: **{initial_seats}**",
        parse_mode="Markdown",
        reply_markup=get_single_main_menu_keyboard()
    )
    return ConversationHandler.END

def is_match(user_input, site_text):
    clean_user = re.sub(r'[^a-zA-Z0-9]', '', user_input.lower())
    clean_site = re.sub(r'[^a-zA-Z0-9]', '', site_text.lower())
    return clean_user in clean_site or clean_site in clean_user

# ==================== حلقه عمومی پایش تمام کاربران ====================
async def global_monitoring_loop(app):
    while True:
        await asyncio.sleep(300)

        if not USER_MONITORS:
            continue

        data = await fetch_filtered_naati_dates()
        if not data:
            continue

        for chat_id, monitor_info in list(USER_MONITORS.items()):
            mode = monitor_info.get("mode")

            # --- ۱. پایش حالت دستی ---
            if mode == "manual":
                target_date = monitor_info["target_date"]
                last_seats = monitor_info["last_seats"].get(target_date, "")
                found_item = next((item for item in data if is_match(target_date, item['date'])), None)
                current_seats = found_item['seats'] if found_item else "یافت نشد/تمام شده"

                if current_seats != last_seats:
                    USER_MONITORS[chat_id]["last_seats"][target_date] = current_seats
                    await send_alert(app, chat_id, f"🔔 **تغییر ظرفیت (پایش دستی):**\n\n📅 تاریخ: `{target_date}`\n💺 ظرفیت جدید: **{current_seats}**")

            # --- ۲. پایش حالت چندتایی ---
            elif mode == "multi":
                selected_dates = monitor_info.get("selected_dates", [])
                last_seats_dict = monitor_info.get("last_seats", {})

                for s_date in selected_dates:
                    found_item = next((item for item in data if is_match(s_date, item['date'])), None)
                    current_seats = found_item['seats'] if found_item else "تمام شده/حذف شده"
                    old_seats = last_seats_dict.get(s_date, "")

                    if current_seats != old_seats:
                        USER_MONITORS[chat_id]["last_seats"][s_date] = current_seats
                        await send_alert(app, chat_id, f"🔔 **تغییر ظرفیت (پایش چندتایی):**\n\n📅 تاریخ: `{s_date}`\n💺 وضعیت جدید: **{current_seats}**")

            # --- ۳. پایش حالت تکی (+4 / -4 سطر) ---
            elif mode == "single":
                target_date = monitor_info["target_date"]
                last_seats = monitor_info["last_seats"].get(target_date, "")

                # پیدا کردن ایندکس فعلی تاریخ انتخابی در جدول جدید
                current_idx = next((i for i, item in enumerate(data) if is_match(target_date, item['date'])), None)

                # شرط ۱: تغییر ظرفیت خود تاریخ
                if current_idx is not None:
                    curr_seats = data[current_idx]['seats']
                    if curr_seats != last_seats:
                        USER_MONITORS[chat_id]["last_seats"][target_date] = curr_seats
                        await send_alert(app, chat_id, f"🔔 **تغییر ظرفیت تاریخ انتخابی:**\n\n📅 تاریخ: `{target_date}`\n💺 ظرفیت جدید: **{curr_seats}**")

                    # شرط ۲: بررسی باز شدن تاریخ‌های جدیدتر در محدوده -4 تا +4 سطر
                    start_idx = max(0, current_idx - 4)
                    end_idx = min(len(data), current_idx + 5)
                    nearby_items = data[start_idx:end_idx]

                    snapshot = monitor_info.get("cached_snapshot", [])
                    new_found = [item for item in nearby_items if item['date'] not in snapshot]

                    if new_found:
                        USER_MONITORS[chat_id]["cached_snapshot"].extend([item['date'] for item in new_found])
                        msg_new = "🔥 **تاریخ جدید در محدوده ±4 سطر یافت شد!**\n\n"
                        for item in new_found:
                            msg_new += f"📅 تاریخ: `{item['date']}` | 💺 ظرفیت: **{item['seats']}**\n"
                        await send_alert(app, chat_id, msg_new)

async def send_alert(app, chat_id, text):
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=f"{text}\n\n🔗 [ثبت نام در سایت NAATI](https://www.naati.com.au/test-date/)",
            parse_mode="Markdown",
            reply_markup=get_single_main_menu_keyboard()
        )
    except Exception as e:
        print(f"Alert error: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("عملیات لغو شد.", reply_markup=get_main_inline_keyboard())
    return ConversationHandler.END

def main():
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button_click, pattern="^btn_manual$")
        ],
        states={
            WAITING_FOR_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date_and_start)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(button_click, pattern="^btn_main$")
        ],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_click))

    # ==================== مدیریت ایونت‌لوپ برای جلوگیری از خطای Render ====================
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.create_task(global_monitoring_loop(app))

    print("ربات با موفقیت روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
