import os
import threading
import subprocess
import tempfile
import shutil
import time
import json
from pathlib import Path
from datetime import datetime
from queue import Queue
from io import BytesIO

import telebot
from PIL import Image
import requests
from flask import Flask
from dotenv import load_dotenv

# ===== LOAD CONFIG =====
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DOWNLOAD_DIR = Path("downloads_music4u")
MAX_FILESIZE = 30 * 1024 * 1024
START_TIME = datetime.utcnow()

bot = telebot.TeleBot(TOKEN)
DOWNLOAD_DIR.mkdir(exist_ok=True)
subscribers = set()
active_downloads = {}
DATA_FILE = Path("music4u_subscribers.json")
lock = threading.Lock()

# ===== FLASK KEEP ALIVE =====
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ Music 4U Bot is Alive!"

def run_server():
    app.run(host="0.0.0.0", port=8080, debug=False)

def keep_alive():
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

# ===== SUBSCRIBERS =====
def load_subscribers():
    global subscribers
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                subscribers = set(json.load(f))
        except:
            subscribers = set()

def save_subs():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(list(subscribers), f)

# ===== ADMIN CHECK =====
def is_admin(uid):
    return uid == ADMIN_ID

# ===== COMMANDS =====
@bot.message_handler(commands=["start", "help"])
def start(msg):
    bot.reply_to(msg, (
        "🎶 *Welcome to Music 4U*\n\n"
        "သီချင်းရှာရန်: `/play <နာမည်>` သို့မဟုတ် YouTube link\n"
        "/stop - ဒေါင်းလုပ်ရပ်ရန်\n"
        "/subscribe - Broadcast join\n"
        "/unsubscribe - Broadcast cancel\n"
        "/status - Server uptime\n"
        "/about - Bot info\n"
        "\n⚡ Fast • Reliable • 24/7 Online"
    ), parse_mode="Markdown")

@bot.message_handler(commands=["play"])
def play(msg):
    chat_id = msg.chat.id
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(msg, "အသုံးပြုနည်း: `/play <နာမည်>`", parse_mode="Markdown")
        return
    query = parts[1].strip()

    with lock:
        if chat_id not in active_downloads:
            stop_event = threading.Event()
            q = Queue()
            q.put(query)
            active_downloads[chat_id] = {"stop": stop_event, "queue": q}
            threading.Thread(target=process_queue, args=(chat_id,), daemon=True).start()
        else:
            active_downloads[chat_id]["queue"].put(query)
            bot.reply_to(msg, "⏳ Download queue ထဲသို့ထည့်လိုက်ပါသည်။")

@bot.message_handler(commands=["stop"])
def stop(msg):
    chat_id = msg.chat.id
    with lock:
        if chat_id in active_downloads:
            active_downloads[chat_id]["stop"].set()
            bot.reply_to(msg, "🛑 Download ရပ်လိုက်ပါသည်။")
        else:
            bot.reply_to(msg, "ရပ်ရန် download မရှိပါ။")

# ===== QUEUE PROCESSING =====
def process_queue(chat_id):
    stop_event = active_downloads[chat_id]["stop"]
    q = active_downloads[chat_id]["queue"]
    while not q.empty() and not stop_event.is_set():
        query = q.get()
        download_and_send(chat_id, query, stop_event)
        q.task_done()
    with lock:
        if chat_id in active_downloads and q.empty():
            active_downloads.pop(chat_id, None)

# ===== CORE DOWNLOAD LOGIC =====
def download_and_send(chat_id, query, stop_event):
    tmpdir = tempfile.mkdtemp(prefix="music4u_")
    progress_msg_id = None
    last_update_time = 0
    UPDATE_INTERVAL = 0.5
    TIMEOUT = 60

    try:
        # Fetch metadata
        info_json = subprocess.check_output(
            ["yt-dlp", "--no-playlist", "--ignore-errors", "--no-warnings",
             "--print-json", "--skip-download", f"ytsearch5:{query}"],
            text=True
        )

        data_list = [json.loads(line) for line in info_json.strip().split("\n") if line.strip()]
        video_found = False

        for data in data_list:
            title = data.get("title", "Unknown")
            url = data.get("webpage_url")
            if not url:
                continue

            bot.send_message(chat_id, f"🔎 `{title}` ကိုရှာနေပါသည်…", parse_mode="Markdown")
            out = os.path.join(tmpdir, "%(title)s.%(ext)s")
            cmd = [
                "yt-dlp", "--no-playlist", "--ignore-errors", "--no-warnings",
                "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
                "--quiet", "--output", out, url
            ]

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            start_time = time.time()

            while proc.poll() is None:
                if stop_event.is_set():
                    proc.terminate()
                    bot.send_message(chat_id, "❌ Download stopped")
                    return
                if time.time() - start_time > TIMEOUT:
                    proc.terminate()
                    break
                now = time.time()
                if now - last_update_time > UPDATE_INTERVAL:
                    dots = "." * int(((now * 2) % 4) + 1)
                    msg_text = f"📥 Downloading{dots}"
                    if not progress_msg_id:
                        m = bot.send_message(chat_id, msg_text)
                        progress_msg_id = m.message_id
                    else:
                        try:
                            bot.edit_message_text(msg_text, chat_id, progress_msg_id)
                        except:
                            pass
                    last_update_time = now
                time.sleep(0.3)

            files = [f for f in os.listdir(tmpdir) if f.endswith(".mp3")]
            if files:
                fpath = os.path.join(tmpdir, files[0])
                if os.path.getsize(fpath) > MAX_FILESIZE:
                    bot.send_message(chat_id, "⚠️ ဖိုင်အရွယ်အစားကြီးနေသည်။ Telegram မှ ပို့လို့မရပါ။")
                    return
                caption = f"🎶 {title}\n\n_Music 4U မှ ပေးပို့နေပါသည်_ 🎧"
                thumb_url = data.get("thumbnail")
                try:
                    if thumb_url:
                        img = Image.open(BytesIO(requests.get(thumb_url, timeout=5).content))
                        thumb_path = os.path.join(tmpdir, "thumb.jpg")
                        img.save(thumb_path)
                        with open(fpath, "rb") as aud, open(thumb_path, "rb") as th:
                            bot.send_audio(chat_id, aud, caption=caption, thumb=th, parse_mode="Markdown")
                    else:
                        with open(fpath, "rb") as aud:
                            bot.send_audio(chat_id, aud, caption=caption, parse_mode="Markdown")
                except:
                    with open(fpath, "rb") as aud:
                        bot.send_audio(chat_id, aud, caption=caption, parse_mode="Markdown")

                bot.send_message(chat_id, "✅ သီချင်း ပေးပို့ပြီးပါပြီ 🎧")
                video_found = True
                break

        if not video_found:
            bot.send_message(chat_id, "🚫 ဖိုင်မတွေ့ပါ၊ အခြား keyword ဖြင့်စမ်းကြည့်ပါ။")

    except Exception as e:
        bot.send_message(chat_id, f"❌ အမှားတစ်ခုဖြစ်ပါသည်: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ===== RUN BOT =====
def start_bot():
    print("✅ Bot is starting...")
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=30)

# ===== MAIN =====
if __name__ == "__main__":
    keep_alive()  # Flask server thread
    load_subscribers()
    start_bot()   # Run bot in main thread
