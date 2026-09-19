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
# 1. تابع اختصاصی تبدیل تاریخ سیدنی به تهران
# ==========================================


def convert_sydney_to_tehran(date_str: str) -> str:
    """تبدیل رشته تاریخ سیدنی به فرمت دو خطی شامل زمان سیدنی و زمان تهران (شمسی)"""
    try:
        # 1. Parse کردن تاریخ ورودی میلادی (فرمت: DD-MM-YYYY HH:MM AM/PM)
        dt_naive = datetime.strptime(date_str.strip(), "%d-%m-%Y %I:%M %p")

        # 2. تنظیم منطقه زمانی سیدنی (با احتساب DST اتوماتیک)
        sydney_tz = pytz.timezone("Australia/Sydney")
        sydney_dt = sydney_tz.localize(dt_naive)

        # 3. تبدیل به منطقه زمانی تهران
        tehran_tz = pytz.timezone("Asia/Tehran")
        tehran_dt = sydney_dt.astimezone(tehran_tz)

        # 4. تبدیل به هجری شمسی
        j_date = jdatetime.datetime.fromgregorian(datetime=tehran_dt)

        # 5. فرمت‌دهی خروجی برای تلگرام
        sydney_formatted = f"🇦🇺 {date_str} (سیدنی)"
        tehran_formatted = (
            f"🇮🇷 {j_date.strftime('%Y/%m/%d - %H:%M')} (تهران)"
        )

        return f"{sydney_formatted}\n   └ {tehran_formatted}"
    except Exception:
        return date_str


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
# 3. تابع اصلی ارسال پیام
# ==========================================


async def show_ccl_dates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_lines = ["🗓 **تاریخ‌های فعال آزمون CCL فارسی در سایت:**\n"]

    for idx, item in enumerate(EXAMS_DATA, start=1):
        formatted_date = convert_sydney_to_tehran(item["date"])
        line = (
            f"{idx}. 📍 **{item['status']}** | 📅 {formatted_date} | 💺 **{item['seats']}**\n"
        )
        message_lines.append(line)

    message_lines.append("\n👇 **لطفاً نحوه پایش را مشخص کنید:**")

    full_message_text = "\n".join(message_lines)

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

    if update.message:
        await update.message.reply_text(
            full_message_text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            full_message_text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )


# ==========================================
# 4. اجرای ربات
# ==========================================


def main():
    # توکن اختصاصی شما
    BOT_TOKEN = "8708901411:AAHq60CbzFXNhIfhNlP7R0mH4rQ1a2LVS_4"

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", show_ccl_dates))
    app.add_handler(CommandHandler("dates", show_ccl_dates))

    print("ربات با موفقیت روشن شد...")
    app.run_polling()


if __name__ == "__main__":
    main()
