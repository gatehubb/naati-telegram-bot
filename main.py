import logging
import os
import threading
from flask import Flask
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ----------------------------------------------------
# ۱. سرور Flask جهت روشن نگه داشتن سرویس در Render
# ----------------------------------------------------
web_app = Flask(__name__)


@web_app.route('/')
def health_check():
  return 'Bot is running live!', 200


def run_flask():
  port = int(os.environ.get('PORT', 10000))
  web_app.run(host='0.0.0.0', port=port)


# ----------------------------------------------------
# ۲. تنظیمات لوگ و توکن
# ----------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

BOT_TOKEN = os.environ.get(
    'BOT_TOKEN', '8708901411:AAHq60CbzFXNhIfhNlP7R0mH4rQ1a2LVS_4'
)


# ----------------------------------------------------
# ۳. توابع ربات تلگرام (با Callback Dataهای دقیق قبلی)
# ----------------------------------------------------
async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
  """نمایش منوی اصلی دقیقا مشابه تصویر شما"""
  keyboard = [[
      InlineKeyboardButton(
          '🟣 NAATI استخراج و انتخاب تاریخ از', callback_data='extract_dates'
      )
  ]]
  reply_markup = InlineKeyboardMarkup(keyboard)

  welcome_text = (
      '🤖 **دستیار هوشمند پایش آزمون NAATI CCL**\n\n'
      'به ربات پایش لحظه‌ای ظرفیت آزمون‌های NAATI خوش آمدید.\n\n'
      'امکانات ربات:\n'
      '• دریافت زنده تاریخ‌های فعال آزمون فارسی\n'
      '• نمایش خودکار تاریخ شمسی و ساعت به وقت ایران (تهران) روی دکمه‌ها و پیام‌ها\n'
      '• پایش یک تاریخ خاص همراه با اعلام ظرفیت‌های جدید\n'
      '• پایش همزمان چندین تاریخ (تا ۴ تاریخ)\n'
      '• پایش اتوماتیک هر ۵ دقیقه یک‌بار و ارسال هشدار آنی تغییر ظرفیت\n\n'
      'جهت شروع، روی دکمه زیر کلیک کنید:'
  )

  if update.message:
    await update.message.reply_text(
        welcome_text, parse_mode='Markdown', reply_markup=reply_markup
    )


async def button_click_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
  """مدیریت دکمه‌های شیشه‌ای"""
  query = update.callback_query
  if not query:
    return

  # پاسخ آنی به تلگرام برای برداشتن لودینگ دکمه
  await query.answer()

  # بررسی دقیق Callback Data
  if query.data == 'extract_dates':
    await query.edit_message_text(
        text='⏳ **در حال استخراج و دریافت اطلاعات از سامانه NAATI... لطفاً چند لحظه شکیبا باشید.**',
        parse_mode='Markdown',
    )

    # TODO: منطق اصلی اتصال به اسکریپت استخراج تاریخ‌ها
    # نمونه منوی بعد از استخراج:
    keyboard = [
        [
            InlineKeyboardButton(
                '📅 چهارشنبه ۱۹ خرداد ۱۴۰۶ - ساعت ۰۵:۳۰', callback_data='date_1'
            )
        ],
        [InlineKeyboardButton('🔙 بازگشت به منوی اصلی', callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text='👇 لطفاً جهت پایش، تاریخ مورد نظر را انتخاب کنید:',
        reply_markup=reply_markup,
    )

  elif query.data == 'main_menu':
    keyboard = [[
        InlineKeyboardButton(
            '🟣 NAATI استخراج و انتخاب تاریخ از', callback_data='extract_dates'
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text='جهت شروع، روی دکمه زیر کلیک کنید:', reply_markup=reply_markup
    )


# ----------------------------------------------------
# ۴. اجرای برنامه
# ----------------------------------------------------
def main():
  # ۱. اجرای وب سرور پس‌زمینه
  threading.Thread(target=run_flask, daemon=True).start()

  # ۲. ساخت برنامه تلگرام
  app = Application.builder().token(BOT_TOKEN).build()

  # ثبت هندلرها
  app.add_handler(CommandHandler('start', start_command))
  app.add_handler(CallbackQueryHandler(button_click_handler))

  # ۳. شروع Polling با پاک‌سازی آپدیت‌های معلق
  app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
  main()
