from datetime import datetime
import jdatetime
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ==========================================
# 1. تابع اختصاصی تبدیل تاریخ (سیدنی به تهران)
# ==========================================


def convert_sydney_to_tehran(date_str: str) -> tuple[str, str]:
    """تبدیل تاریخ سیدنی به فرمت دو خطی بدون تداخل فونت و چیدمان"""
    try:
        dt_naive = datetime.strptime(date_str.strip(), "%d-%m-%Y %I:%M %p")

        sydney_tz = pytz.timezone("Australia/Sydney")
        sydney_dt = sydney_tz.localize(dt_naive)

        tehran_tz = pytz.timezone("Asia/Tehran")
        tehran_dt = sydney_dt.astimezone(tehran_tz)

        j_date = jdatetime.datetime.fromgregorian(datetime=tehran_dt)

        sydney_line = f"{date_str} (Sydney)"
        tehran_line = f"تهران: {j_date.strftime('%Y/%m/%d - %H:%M')}"

        return sydney_line, tehran_line
    except Exception:
        return date_str, ""


# ==========================================
# 2. داده‌های آزمون‌ها
# ==========================================

EXAMS_DATA = [
    {"status": "ONLINE - Online", "date": "01-10-2026 10:45 AM", "seats": 34},
    {"status": "ONLINE - Online", "date": "20-10-2026 12:00 PM", "seats": 36},
    {"status": "ONLINE - Online", "date": "05-11-2026 12:00 PM", "seats": 49},
    {"status": "ONLINE - Online", "date": "02-12-2026 12:00 PM", "seats": 52},
    {"status": "ONLINE - Online", "date": "10-12-2026 10:45 AM", "seats": 60},
    {"status": "ONLINE - Online", "date": "19-01-2027 12:00 PM", "seats": 57},
    {"status": "ONLINE - Online", "date": "16-02-2027 12:00 PM", "seats": 56},
    {"status": "ONLINE - Online", "date": "04-03-2027 10:45 AM", "seats": 40},
    {"status": "ONLINE - Online", "date": "16-03-2027 12:00 PM", "seats": 59},
    {"status": "ONLINE - Online", "date": "20-04-2027 12:00 PM", "seats": 60},
    {"status": "ONLINE - Online", "date": "12-05-2027 12:00 PM", "seats": 60},
    {"status": "ONLINE - Online", "date": "09-06-2027 12:00 PM", "seats": 59},
    {"status": "ONLINE - Online", "date": "23-06-2027 12:00 PM", "seats": 54},
]


# ==========================================
# 3. منوی اولیه ربات (با دستور /start)
# ==========================================


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش منوی اصلی اولیه هنگام زدن /start"""
    welcome_text = "سلام! به ربات بررسی آزمون‌های NAATI CCL خوش آمدید.\n\nلطفاً گزینه مورد نظر خود را انتخاب کنید:"

    keyboard = [
        [
            InlineKeyboardButton(
                "📅 مشاهده تاریخ‌های فعال آزمون",
                callback_data="show_ccl_dates",
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            welcome_text, reply_markup=reply_markup
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            welcome_text, reply_markup=reply_markup
        )


# ==========================================
# 4. نمایش جدول تاریخ‌ها (پس از انتخاب کاربر)
# ==========================================


async def show_ccl_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()

    message_text = "🗓 **تاریخ‌های فعال آزمون CCL فارسی در سایت:**\n\n"

    for idx, item in enumerate(EXAMS_DATA, start=1):
        sydney_str, tehran_str = convert_sydney_to_tehran(item["date"])

        message_text += f"{idx}. 📍 {item['status']} | 💺 {item['seats']}\n"
        message_text += f"   📅 🇦🇺 {sydney_str}\n"
        if tehran_str:
            message_text += f"   🇮🇷 {tehran_str}\n"
        message_text += "\n"

    message_text += "👇 **لطفاً نحوه پایش را مشخص کنید:**"

    keyboard = [
        [
            InlineKeyboardButton(
                "🎯 انتخاب تکی", callback_data="select_single"
            ),
            InlineKeyboardButton(
                "📌 انتخاب چندتایی (حداکثر ۴)", callback_data="select_multi"
            ),
        ],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.edit_message_text(
            message_text, reply_markup=reply_markup, parse_mode="Markdown"
        )
    elif update.message:
        await update.message.reply_text(
            message_text, reply_markup=reply_markup, parse_mode="Markdown"
        )


# ==========================================
# 5. مدیریت Callbackها و اجرای ربات
# ==========================================


async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "show_ccl_dates":
        await show_ccl_dates(update, context)
    elif data == "main_menu":
        await start_command(update, context)


def main():
    BOT_TOKEN = "8708901411:AAHq60CbzFXNhIfhNlP7R0mH4rQ1a2LVS_4"

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # ۱. دستور استارت فقط منوی اصلی را باز می‌کند
    app.add_handler(CommandHandler("start", start_command))

    # ۲. مدیریت کلیک روی دکمه‌ها
    app.add_handler(CallbackQueryHandler(handle_callbacks))

    print("ربات فعال شد...")
    app.run_polling()


if __name__ == "__main__":
    main()
