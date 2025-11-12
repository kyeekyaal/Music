import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import threading
import os

# ============================
# 🔹 Telegram Bot Token
# ============================
BOT_TOKEN = "8571888982:AAFRoMCdc-djPvXctFl5fxRchX-0cEfPXgM"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ============================
# 🔹 Flask App for Railway
# ============================
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Telegram Bot is Running on Railway!"

# ============================
# 🔹 Function to send second message
# ============================
def send_second_message(chat_id):
    text2 = "📢 ကြေငြာကိစ္စများအတွက်ဆက်သွယ်ရန်"
    markup2 = InlineKeyboardMarkup()
    markup2.add(
        InlineKeyboardButton("Admin Account", url="https://t.me/Jordan_9_9")
    )
    bot.send_message(chat_id, text2, reply_markup=markup2)

# ============================
# 🔹 Handle /start Command
# ============================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id

    # 🔹 ပထမ Message
    text1 = (
        "🌞 သာယာသောနေ့လေးဖြစ်ပါစေညီကိုတို့ရေ 🥰\n"
        "💖 ချန်နယ်ဝင်ပေးတဲ့တစ်ယောက်ချင်းစီတိုင်းကိုလည်း ကျေးဇူးအထူးတင်ပါတယ်"
    )
    markup1 = InlineKeyboardMarkup(row_width=2)
    markup1.add(
        InlineKeyboardButton("🎬 Main Channel", url="https://t.me/Max_area")
    )
    markup1.add(
        InlineKeyboardButton("💬 Chat Group 1", url="https://t.me/DarkWorldArea_1"),
        InlineKeyboardButton("💬 Chat Group 2", url="https://t.me/DarkWorldArea2")
    )

    bot.send_message(chat_id, text1, reply_markup=markup1)

    # 🔹 Thread နဲ့ ဒုတိယ message ပို့ခြင်း
    threading.Thread(target=send_second_message, args=(chat_id,)).start()

# ============================
# 🔹 Background Bot Polling
# ============================
threading.Thread(target=lambda: bot.polling(non_stop=True, skip_pending=True)).start()

# ============================
# 🔹 Flask App Run (for Railway)
# ============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
