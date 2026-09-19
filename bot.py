import html
from datetime import datetime
import pytz
import jdatetime

def convert_sydney_to_tehran_shamsi(raw_date_str: str) -> tuple[str, str]:
    """
    دریافت تاریخ میلادی به وقت سیدنی و تبدیل آن به:
    ۱. خط اول: تاریخ میلادی + (Sydney)
    ۲. خط دوم: روز هفته + تاریخ شمسی + ساعت به وقت تهران
    """
    clean_date_str = raw_date_str.strip()
    sydney_line = f"{clean_date_str} (Sydney)"
    
    try:
        # پارس کردن رشته تاریخ میلادی (مانند: '01-10-2026 10:45 AM')
        dt_naive = datetime.strptime(clean_date_str, "%d-%m-%Y %I:%M %p")
        
        # ۱. مشخص کردن منطقه زمانی سیدنی (با احتساب ساعت تابستانی DST)
        sydney_tz = pytz.timezone("Australia/Sydney")
        dt_sydney = sydney_tz.localize(dt_naive)
        
        # ۲. تبدیل به منطقه زمانی تهران
        tehran_tz = pytz.timezone("Asia/Tehran")
        dt_tehran = dt_sydney.astimezone(tehran_tz)
        
        # ۳. تبدیل به تاریخ هجری شمسی
        shamsi_date = jdatetime.datetime.fromgregorian(datetime=dt_tehran)
        
        # ۴. اسامی روزهای هفته
        weekdays_fa = [
            "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"
        ]
        day_name = weekdays_fa[dt_tehran.weekday()]
        
        # ۵. اسامی ماه‌های شمسی
        months_fa = [
            "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
            "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
        ]
        month_name = months_fa[shamsi_date.month - 1]
        
        # ۶. ساخت خط دوم
        tehran_line = (
            f"└ 🗓 {day_name} {shamsi_date.day} {month_name} {shamsi_date.year} "
            f"| ⏰ {dt_tehran.strftime('%H:%M')} (تهران)"
        )
        return sydney_line, tehran_line

    except Exception:
        # در صورت بروز خطای غیرمنتظره جهت جلوگیری از کرش ربات
        return sydney_line, "└ 🗓 خطا در محاسبه تاریخ شمسی"


def build_ccl_message(exam_slots: list[dict]) -> str:
    """
    تابع اصلی برای دریافت لیست آزمون‌ها و ساخت پیام نهایی تلگرام.
    
    ورودی نمونه:
    [
        {"location": "ONLINE - Online", "date": "01-10-2026 10:45 AM", "seats": 34},
        ...
    ]
    """
    lines = ["📋 <b>تاریخ‌های فعال آزمون CCL فارسی در سایت:</b>\n"]
    
    for idx, slot in enumerate(exam_slots, start=1):
        location = html.escape(str(slot.get("location", "ONLINE - Online")))
        raw_date = str(slot.get("date", "") or slot.get("date_str", ""))
        seats = html.escape(str(slot.get("seats", "0")))
        
        # دریافت دو خط تاریخ
        sydney_date, tehran_date = convert_sydney_to_tehran_shamsi(raw_date)
        
        # ساخت هر ردیف
        item_text = (
            f"{idx}. 📍 {location} | 📅 {html.escape(sydney_date)} | 💺 {seats}\n"
            f"   {tehran_date}\n"
        )
        lines.append(item_text)
        
    lines.append("👇 <b>لطفاً نحوه پایش را مشخص کنید:</b>")
    
    return "\n".join(lines)


# =============================================================
# نمونه اجرا و تست مستقیم (Mock Data مطابق اسکرین‌شات شما)
# =============================================================
if __name__ == "__main__":
    # داده‌های واقعی شما از روی عکس:
    raw_slots = [
        {"location": "ONLINE - Online", "date": "01-10-2026 10:45 AM", "seats": 34},
        {"location": "ONLINE - Online", "date": "20-10-2026 12:00 PM", "seats": 36},
        {"location": "ONLINE - Online", "date": "05-11-2026 12:00 PM", "seats": 49},
        {"location": "ONLINE - Online", "date": "02-12-2026 12:00 PM", "seats": 52},
        {"location": "ONLINE - Online", "date": "10-12-2026 10:45 AM", "seats": 60},
        {"location": "ONLINE - Online", "date": "19-01-2027 12:00 PM", "seats": 57},
        {"location": "ONLINE - Online", "date": "16-02-2027 12:00 PM", "seats": 56},
        {"location": "ONLINE - Online", "date": "04-03-2027 10:45 AM", "seats": 40},
        {"location": "ONLINE - Online", "date": "16-03-2027 12:00 PM", "seats": 59},
        {"location": "ONLINE - Online", "date": "20-04-2027 12:00 PM", "seats": 60},
        {"location": "ONLINE - Online", "date": "12-05-2027 12:00 PM", "seats": 60},
        {"location": "ONLINE - Online", "date": "09-06-2027 12:00 PM", "seats": 59},
        {"location": "ONLINE - Online", "date": "23-06-2027 12:00 PM", "seats": 54},
    ]

    # ساخت پیام final
    telegram_message = build_ccl_message(raw_slots)
    
    # خروجی نهایی متنی
    print(telegram_message)
