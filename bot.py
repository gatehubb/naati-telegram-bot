import html
from datetime import datetime
import pytz
import jdatetime


def convert_sydney_to_tehran_shamsi(raw_date_str: str) -> tuple[str, str]:
    """
    دریافت تاریخ میلادی بر اساس منطقه زمانی سیدنی 
    و تبدیل آن به تاریخ شمسی و ساعت تهران.
    
    ورودی نمونه: '01-10-2026 10:45 AM'
    خروجی:
        خط ۱: '01-10-2026 10:45 AM (Sydney)'
        خط ۲: '└ 🗓 پنج‌شنبه ۹ مهر ۱۴۰۵ | ⏰ ۱۴:۱۵ (تهران)'
    """
    sydney_line = f"{raw_date_str} (Sydney)"
    
    try:
        # ۱. پارس کردن رشته تاریخ میلادی
        dt_naive = datetime.strptime(raw_date_str.strip(), "%d-%m-%Y %I:%M %p")
        
        # ۲. اعمال منطقه زمانی سیدنی (با احتساب ساعت تابستانی DST)
        sydney_tz = pytz.timezone("Australia/Sydney")
        dt_sydney = sydney_tz.localize(dt_naive)
        
        # ۳. تبدیل به منطقه زمانی تهران
        tehran_tz = pytz.timezone("Asia/Tehran")
        dt_tehran = dt_sydney.astimezone(tehran_tz)
        
        # ۴. تبدیل به تاریخ هجری شمسی
        shamsi_date = jdatetime.datetime.fromgregorian(datetime=dt_tehran)
        
        # ۵. اسامی روزهای هفته به فارسی
        weekdays_fa = [
            "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"
        ]
        day_name = weekdays_fa[dt_tehran.weekday()]
        
        # ۶. اسامی ماه‌های شمسی
        months_fa = [
            "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
        ]
        month_name = months_fa[shamsi_date.month - 1]
        
        # ۷. ساخت خط دوم (تهران و شمسی)
        tehran_line = (
            f"└ 🗓 {day_name} {shamsi_date.day} {month_name} {shamsi_date.year} "
            f"| ⏰ {dt_tehran.strftime('%H:%M')} (تهران)"
        )
        return sydney_line, tehran_line

    except Exception:
        # در صورت بروز خطا در پارس یا فرمت ناهمخوان، از کرش برنامه جلوگیری می‌شود
        return sydney_line, "└ 🗓 خطا در محاسبه تاریخ شمسی"


def generate_ccl_telegram_message(exam_slots: list[dict]) -> str:
    """
    تولید پیام نهایی و شکیل برای تلگرام
    """
    message_lines = ["📅 <b>تاریخ‌های فعال آزمون CCL فارسی در سایت:</b>\n"]
    
    for idx, slot in enumerate(exam_slots, start=1):
        location = html.escape(str(slot.get("location", "ONLINE - Online")))
        raw_date = str(slot.get("date", ""))
        seats = html.escape(str(slot.get("seats", "0")))
        
        # تبدیل تاریخ‌ها
        sydney_date, tehran_date = convert_sydney_to_tehran_shamsi(raw_date)
        
        # ساخت بخش مربوط به هر آزمون
        line_item = (
            f"{idx}. 📍 {location} | 📅 {html.escape(sydney_date)} | 💺 {seats}\n"
            f"   {tehran_date}\n"
        )
        message_lines.append(line_item)
        
    message_lines.append("👇 <b>لطفاً نحوه پایش را مشخص کنید:</b>")
    
    return "\n".join(message_lines)


# =============================================================
# نمونه اجرا و تست متد (امتحان مستقیم کد)
# =============================================================
if __name__ == "__main__":
    # داده‌های نمونه مطابق تصویر شما
    sample_slots = [
        {"location": "ONLINE - Online", "date": "01-10-2026 10:45 AM", "seats": 34},
        {"location": "ONLINE - Online", "date": "20-10-2026 12:00 PM", "seats": 36},
        {"location": "ONLINE - Online", "date": "05-11-2026 12:00 PM", "seats": 49},
        {"location": "ONLINE - Online", "date": "02-12-2026 12:00 PM", "seats": 52},
    ]

    # تولید پیام تلگرام
    final_message = generate_ccl_telegram_message(sample_slots)
    
    # چاپ خروجی جهت بررسی
    print(final_message)
