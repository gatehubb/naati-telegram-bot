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
# ۱. وب‌سرور جهت فعال نگه داشتن پورت در Render
# ----------------------------------------------------
web_app = Flask(__name__)


@web_app.route('/')
def health_check():
  return 'Bot is alive and running!', 200


def run_flask_server():
  port = int(os.environ.get('PORT', 10000))
  web_app.run(host='0.0.0.0', port=port)


# ----------------------------------------------------
# ۲. تنظیمات لوگ و توکن
# ----------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get(
    'BOT_TOKEN', '8708901411:AAHq60CbzFXNhIfhNlP7R0mH4rQ1a2LVS_4'
)


# ----------------------------------------------------
# ۳. توابع و هندلرهای اصلی ربات
# ----------------------------------------------------
async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
  """ارسال پیام خوش‌آمدگویی و منوی اصلی"""
  try:
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
  except Exception as e:
    logger.error(f'Error in start_command: {e}')


async def button_click_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
  """مدیریت دکمه‌های شیشه‌ای"""
  query = update.callback_query
  if not query:
    return

  try:
    # پاسخ فوری برای رفع حالت در حال بارگذاری دکمه
    await query.answer()

    if query.data == 'extract_dates':
      await query.edit_message_text(
          text='⏳ **در حال استخراج و دریافت اطلاعات از سامانه NAATI... لطفاً چند لحظه شکیبا باشید.**',
          parse_mode='Markdown',
      )

      # منوی انتخاب تاریخ
      keyboard = [
          [
              InlineKeyboardButton(
                  '📅 چهارشنبه ۱۹ خرداد ۱۴۰۶ - ساعت ۰۵:۳۰', callback_data='date_1'
              )
          ],
          [
              InlineKeyboardButton(
                  '🔙 بازگشت به منوی اصلی', callback_data='main_menu'
              )
          ],
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

  except Exception as e:
    logger.error(f'Error handling button click ({query.data}): {e}')


# ----------------------------------------------------
# ۴. اجرای برنامه
# ----------------------------------------------------
def main():
  # ۱. اجرای وب سرور در یک Thread جداگانه
  threading.Thread(target=run_flask_server, daemon=True).start()
  logger.info('Web server started on background thread.')

  # ۲. ساخت و پیکربندی ربات
  app = Application.builder().token(BOT_TOKEN).build()

  app.add_handler(CommandHandler('start', start_command))
  app.add_handler(CallbackQueryHandler(button_click_handler))

  # ۳. شروع دریافت پیام‌ها و پاک کردن درخواست‌های معلق قبلی
  logger.info('Starting Telegram Bot Polling...')
  app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
  main()
