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
# ۱. راه‌اندازی Web Server ساده برای خنثی کردن Timeout در Render
# ----------------------------------------------------
web_app = Flask(__name__)


@web_app.route('/')
def health_check():
  return 'Bot is running live!', 200


def run_flask():
  # Render پورت را به صورت خودکار در متغیر PORT قرار می‌دهد
  port = int(os.environ.get('PORT', 8080))
  web_app.run(host='0.0.0.0', port=port)


# ----------------------------------------------------
# ۲. تنظیمات تنظیمات لوگ و توکن ربات
# ----------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)

# توکن مستقیم یا دریافت از Environment Variable
BOT_TOKEN = os.environ.get(
    'BOT_TOKEN', '8708901411:AAHq60CbzFXNhIfhNlP7R0mH4rQ1a2LVS_4'
)


# ----------------------------------------------------
# ۳. توابع اصلی ربات (Handlers)
# ----------------------------------------------------
async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
  """پاسخ به دستور /start"""
  keyboard = [[
      InlineKeyboardButton(
          '🌐 NAATI استخراج و انتخاب تاریخ از', callback_data='extract_dates'
      )
  ]]
  reply_markup = InlineKeyboardMarkup(keyboard)

  welcome_text = (
      '👋 **به ربات پایش هوشمند آزمون NAATI CCL خوش آمدید!**\n\n'
      'امکانات ربات:\n'
      '• دریافت زنده تاریخ‌های فعال آزمون فارسی\n'
      '• نمایش خودکار تاریخ شمسی و ساعت به وقت ایران (تهران)\n'
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
  """مدیریت کلیک روی دکمه‌های شیشه‌ای (Inline Buttons)"""
  query = update.callback_query

  # پاسخ فوری به تلگرام برای برداشتن حالت Loading روی دکمه
  await query.answer()

  if query.data == 'extract_dates':
    # ارسال پیام وضعیت در حال پردازش
    await query.edit_message_text(
        text='⏳ **در حال استخراج و دریافت اطلاعات از سامانه NAATI... لطفاً چند لحظه شکیبا باشید.**',
        parse_mode='Markdown',
    )

    # TODO: منطق اصلی دریافت تاریخ‌ها را در این قسمت جای‌گذاری کنید.
    # به عنوان نمونه یک منوی نمونه نمایش داده می‌شود:
    keyboard = [
        [
            InlineKeyboardButton(
                'چهارشنبه ۱۹ خرداد ۱۴۰۶ - ساعت ۰۵:۳۰',
                callback_data='date_1',
            )
        ],
        [
            InlineKeyboardButton(
                'چهارشنبه ۲ تیر ۱۴۰۶ - ساعت ۰۵:۳۰', callback_data='date_2'
            )
        ],
        [InlineKeyboardButton('🔙 بازگشت به منوی اصلی', callback_data='main_menu')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text='👇 لطفاً نحوه پایش را مشخص کنید:', reply_markup=reply_markup
    )

  elif query.data == 'main_menu':
    # بازگشت به منوی اصلی
    keyboard = [[
        InlineKeyboardButton(
            '🌐 NAATI استخراج و انتخاب تاریخ از', callback_data='extract_dates'
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        text='جهت شروع، روی دکمه زیر کلیک کنید:', reply_markup=reply_markup
    )


# ----------------------------------------------------
# ۴. نقطه اجرای اصلی (Main Execution)
# ----------------------------------------------------
def main():
  # ۱. اجرای Web Server در یک Thread جداگانه
  threading.Thread(target=run_flask, daemon=True).start()
  logging.info('Flask HTTP server started.')

  # ۲. ساخت و پیکربندی Application ربات
  app = Application.builder().token(BOT_TOKEN).build()

  # افزودن Handlerها
  app.add_handler(CommandHandler('start', start_command))
  app.add_handler(CallbackQueryHandler(button_click_handler))

  # ۳. شروع دریافت پیام‌ها (Polling)
  logging.info('Bot Polling started...')
  app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
  main()
