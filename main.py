import asyncio
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

# ------------------------------------------------------------------------------
# ۱. ساخت سرور سلامت‌سنج (Health Check Server) برای نگه داشتن سرویس در Render
# ------------------------------------------------------------------------------
web_app = Flask(__name__)


@web_app.route('/')
def health_check():
  return 'OK', 200


def start_health_server():
  """اجرای وب سرور در یک Thread مجزا جهت پاسخ به Pingهای Render"""
  port = int(os.environ.get('PORT', 10000))
  try:
    web_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
  except Exception as e:
    logging.error(f'Failed to start health check server: {e}')


# ------------------------------------------------------------------------------
# ۲. پیکربندی سیستم Log
# ------------------------------------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get(
    'BOT_TOKEN', '8708901411:AAHq60CbzFXNhIfhNlP7R0mH4rQ1a2LVS_4'
)


# ------------------------------------------------------------------------------
# ۳. توابع ربات تلگرام (Telegram Handlers)
# ------------------------------------------------------------------------------
async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
  """مدیریت دستور /start"""
  try:
    keyboard = [[
        InlineKeyboardButton(
            '🌐 استخراج و انتخاب تاریخ از NAATI', callback_data='extract_dates'
        )
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        '👋 **به ربات پایش هوشمند آزمون NAATI CCL خوش آمدید!**\n\n'
        'امکانات ربات:\n'
        '• دریافت زنده تاریخ‌های فعال آزمون فارسی\n'
        '• نمایش خودکار تاریخ شمسی و ساعت به وقت ایران\n'
        '• پایش اتوماتیک و ارسال هشدار آنی\n\n'
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
  """مدیریت ایمن کلیک روی دکمه‌های شیشه‌ای (Callback Queries)"""
  query = update.callback_query
  if not query:
    return

  try:
    # پاسخ سریع به تلگرام برای حذف حالت در حال بارگذاری روی دکمه
    await query.answer()

    if query.data == 'extract_dates':
      await query.edit_message_text(
          text='⏳ **در حال استخراج و دریافت اطلاعات از سامانه NAATI... لطفاً چند لحظه شکیبا باشید.**',
          parse_mode='Markdown',
      )

      # شبیه‌سازی دریافت داده‌ها یا منوی جدید
      keyboard = [
          [
              InlineKeyboardButton(
                  'چهارشنبه ۱۹ خرداد ۱۴۰۶ - ساعت ۰۵:۳۰',
                  callback_data='date_1',
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
          text='👇 لطفاً تاریخ مورد نظر جهت پایش را انتخاب کنید:',
          reply_markup=reply_markup,
      )

    elif query.data == 'main_menu':
      keyboard = [[
          InlineKeyboardButton(
              '🌐 استخراج و انتخاب تاریخ از NAATI',
              callback_data='extract_dates',
          )
      ]]
      reply_markup = InlineKeyboardMarkup(keyboard)
      await query.edit_message_text(
          text='جهت شروع، روی دکمه زیر کلیک کنید:', reply_markup=reply_markup
      )

  except Exception as e:
    logger.error(f'Error handling button click ({query.data}): {e}')


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
  """مدیریت خطاهای غیرمنتظره ربات"""
  logger.error(msg='Exception while handling an update:', exc_info=context.error)


# ------------------------------------------------------------------------------
# ۴. نقطه ورود و اجرای برنامه (Main Function)
# ------------------------------------------------------------------------------
def main():
  # الف) اجرای وب سرور در Thread مجزا
  health_thread = threading.Thread(target=start_health_server, daemon=True)
  health_thread.start()
  logger.info('Health check HTTP server initialized.')

  # ب) راه‌اندازی ربات تلگرام
  application = Application.builder().token(BOT_TOKEN).build()

  # افزودن ثبت‌کننده‌های رویداد (Handlers)
  application.add_handler(CommandHandler('start', start_command))
  application.add_handler(CallbackQueryHandler(button_click_handler))
  application.add_error_handler(error_handler)

  # ج) شروع Polling
  logger.info('Bot polling starting...')
  application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
  main()
