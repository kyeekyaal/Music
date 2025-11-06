# Music 4U Telegram Bot
# This bot allows users to search and download audio from YouTube.

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
# Note: Using ADMIN_ID is a security feature, ensure it is set.
ADMIN_ID = int(os.getenv("ADMIN_ID", 0)) # Default to 0 if not set
DOWNLOAD_DIR = Path("downloads_music4u")
MAX_FILESIZE = 30 * 1024 * 1024 # 30MB Telegram Limit
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
    # Use 0.0.0.0 for deployment environments like Railway
    # Railway provides a PORT variable, use it if available, otherwise default to 8080
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)), debug=False)

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
                # Convert list of strings/ints back to set of ints
                subscribers = set(int(s) for s in json.load(f))
        except Exception as e:
            print(f"Error loading subscribers: {e}")
            subscribers = set()

def save_subs():
    # Convert set of ints to list of strings for JSON serialization
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(list(str(s) for s in subscribers), f)

# ===== ADMIN CHECK =====
def is_admin(uid):
    return uid == ADMIN_ID

# ===== COMMANDS =====
@bot.message_handler(commands=["start", "help"])
def start(msg):
    bot.reply_to(msg, (
        "🎶 *Music 4U မှ ကြိုဆိုပါသည်*\n\n"
        "သီချင်းရှာရန်: `/play <နာမည်>` သို့မဟုတ် YouTube link\n"
        "/stop - ဒေါင်းလုပ်ရပ်ရန်\n"
        "/subscribe - Broadcast join\n"
        "/unsubscribe - Broadcast cancel\n"
        "/status - Server uptime\n"
        "/about - Bot info\n"
        "\n⚡ မြန်ဆန် • ယုံကြည်စိတ်ချရ • ၂၄/၇ လိုင်းပေါ်ရှိ"
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
            # If a new download starts, initialize queue and thread
            stop_event = threading.Event()
            q = Queue()
            q.put(query)
            active_downloads[chat_id] = {"stop": stop_event, "queue": q}
            threading.Thread(target=process_queue, args=(chat_id,), daemon=True).start()
            bot.send_message(chat_id, f"📥 `{query}` ကိုစတင်ရှာဖွေ ဒေါင်းလုပ်လုပ်နေပါသည်။")
        else:
            # If user is already downloading, add to queue
            active_downloads[chat_id]["queue"].put(query)
            bot.reply_to(msg, "⏳ Download queue ထဲသို့ထည့်လိုက်ပါသည်။")

@bot.message_handler(commands=["stop"])
def stop(msg):
    chat_id = msg.chat.id
    with lock:
        if chat_id in active_downloads:
            active_downloads[chat_id]["stop"].set()
            # It will be popped from active_downloads inside process_queue
            bot.reply_to(msg, "🛑 Download ရပ်လိုက်ပါသည်။")
        else:
            bot.reply_to(msg, "ရပ်ရန် download မရှိပါ။")

@bot.message_handler(commands=["status"])
def status(msg):
    uptime = datetime.utcnow() - START_TIME
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    status_message = (
        f"⚙️ *Bot Status*\n"
        f"အသက်ရှင်ချိန်: {uptime.days}d, {hours:02}h:{minutes:02}m:{seconds:02}s\n"
        f"Active Downloads: {len(active_downloads)}\n"
        f"Subscribers: {len(subscribers)}"
    )
    bot.reply_to(msg, status_message, parse_mode="Markdown")

@bot.message_handler(commands=["subscribe"])
def subscribe(msg):
    chat_id = msg.chat.id
    with lock:
        if chat_id not in subscribers:
            subscribers.add(chat_id)
            save_subs()
            bot.reply_to(msg, "🔔 Broadcast သို့ အောင်မြင်စွာ ဝင်ရောက်လိုက်ပါပြီ။")
        else:
            bot.reply_to(msg, "သင်သည် Broadcast တွင် ရှိပြီးသားဖြစ်ပါသည်။")

@bot.message_handler(commands=["unsubscribe"])
def unsubscribe(msg):
    chat_id = msg.chat.id
    with lock:
        if chat_id in subscribers:
            subscribers.discard(chat_id)
            save_subs()
            bot.reply_to(msg, "🔕 Broadcast မှ အောင်မြင်စွာ ထွက်ခွာလိုက်ပါပြီ။")
        else:
            bot.reply_to(msg, "သင်သည် Broadcast တွင် မရှိသေးပါ။")

# ===== ADMIN BROADCAST COMMANDS (Example) =====
@bot.message_handler(commands=["broadcast"])
def broadcast_admin(msg):
    chat_id = msg.chat.id
    if not is_admin(chat_id):
        bot.reply_to(msg, "Access Denied.")
        return

    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(msg, "Usage: `/broadcast <message>`", parse_mode="Markdown")
        return

    message = parts[1].strip()
    sent_count = 0
    fail_count = 0

    bot.send_message(chat_id, f"Starting broadcast to {len(subscribers)} users...")
    
    for user_id in list(subscribers):
        try:
            # Use 'MarkdownV2' or similar if needed for complex formatting
            bot.send_message(user_id, message, parse_mode="Markdown") 
            sent_count += 1
            time.sleep(0.1) # small delay to avoid hitting rate limits
        except telebot.apihelper.ApiTelegramException as e:
            if e.result_json.get('error_code') == 403: # User blocked the bot
                print(f"User {user_id} blocked the bot. Removing.")
                with lock:
                    subscribers.discard(user_id)
                    save_subs()
            else:
                fail_count += 1
                print(f"Failed to send to {user_id}: {e}")
        except Exception as e:
            fail_count += 1
            print(f"Unknown error sending to {user_id}: {e}")

    bot.send_message(chat_id, f"✅ Broadcast finished. Sent: {sent_count}, Failed: {fail_count}")

# ===== QUEUE PROCESSING =====
def process_queue(chat_id):
    stop_event = active_downloads[chat_id]["stop"]
    q = active_downloads[chat_id]["queue"]
    
    while not q.empty() and not stop_event.is_set():
        query = q.get()
        print(f"Processing query for chat {chat_id}: {query}")
        download_and_send(chat_id, query, stop_event)
        q.task_done()

    # Clean up after queue is empty or stop is set
    with lock:
        if chat_id in active_downloads:
            print(f"Queue finished for chat {chat_id}. Cleaning up.")
            active_downloads.pop(chat_id, None)

# ===== CORE DOWNLOAD LOGIC (Improved Error Handling) =====
def download_and_send(chat_id, query, stop_event):
    tmpdir = tempfile.mkdtemp(prefix="music4u_")
    progress_msg_id = None
    last_update_time = 0
    UPDATE_INTERVAL = 0.5
    TIMEOUT = 90 # Increased timeout for slow downloads

    try:
        # 1. Fetch metadata (using a simple search query)
        bot.send_message(chat_id, f"🔎 `{query}` ကိုရှာနေပါသည်…", parse_mode="Markdown")

        try:
            # Use subprocess.run for better error handling and simplicity
            info_result = subprocess.run(
                ["yt-dlp", "--no-playlist", "--ignore-errors", "--no-warnings",
                 "--print-json", "--skip-download", f"ytsearch5:{query}"],
                capture_output=True,
                text=True,
                check=True, # Raise an error if return code is non-zero
                timeout=30 # Timeout for metadata fetch
            )
            
            info_json = info_result.stdout
            if not info_json.strip():
                 bot.send_message(chat_id, "🚫 ရှာဖွေမှုရလဒ်မတွေ့ပါ။")
                 return
                 
        except subprocess.CalledProcessError as e:
             error_message = f"yt-dlp metadata error (Code {e.returncode}): {e.stderr.strip()}"
             print(error_message)
             # Check if the error is related to missing binaries
             if "No such file or directory" in e.stderr or "command not found" in e.stderr:
                 bot.send_message(chat_id, "❌ Server တွင် လိုအပ်သော `yt-dlp` tool မရှိပါ။ (Admin ကို ဆက်သွယ်ပါ)")
             else:
                 bot.send_message(chat_id, f"❌ ရှာဖွေမှု အမှားတစ်ခုဖြစ်ပါသည်: {e.stderr.strip()[:100]}...")
             return
        except subprocess.TimeoutExpired:
            bot.send_message(chat_id, "❌ ရှာဖွေမှုအချိန်ကုန်ဆုံးသွားသည်။ (Timeout)")
            return
        except FileNotFoundError:
             bot.send_message(chat_id, "❌ Server တွင် လိုအပ်သော `yt-dlp` tool မရှိပါ။ (Admin ကို ဆက်သွယ်ပါ)")
             return
        except Exception as e:
            bot.send_message(chat_id, f"❌ metadata ရယူရာတွင် အမှားဖြစ်: {e}")
            return


        data_list = [json.loads(line) for line in info_json.strip().split("\n") if line.strip()]
        video_found = False

        # 2. Iterate through results and try to download
        for data in data_list:
            title = data.get("title", "Unknown Title")
            url = data.get("webpage_url")
            
            if not url:
                continue

            # Update status message for the actual download
            bot.send_message(chat_id, f"📥 `{title}` ကို ဒေါင်းလုပ်စတင်ပါမည်…", parse_mode="Markdown")
            
            # The output template ensures the file is created in tmpdir
            out = os.path.join(tmpdir, "%(title)s.%(ext)s")
            cmd = [
                "yt-dlp", "--no-playlist", "--ignore-errors", "--no-warnings",
                "--extract-audio", "--audio-format", "mp3", "--audio-quality", "0",
                "--quiet", "--output", out, url
            ]

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            start_time = time.time()
            progress_msg_id = None # Reset progress message ID

            while proc.poll() is None:
                if stop_event.is_set():
                    proc.terminate()
                    # Wait a moment for the process to terminate
                    proc.wait(timeout=5) 
                    bot.send_message(chat_id, "❌ Download ရပ်တန့်လိုက်ပါသည်။")
                    return
                
                if time.time() - start_time > TIMEOUT:
                    proc.terminate()
                    proc.wait(timeout=5)
                    bot.send_message(chat_id, "❌ ဒေါင်းလုပ်ချိန်ကုန်ဆုံးသွားသည်။ (Timeout)")
                    return

                now = time.time()
                # Update progress message periodically
                if now - last_update_time > UPDATE_INTERVAL:
                    dots = "." * int(((now * 2) % 4) + 1)
                    msg_text = f"📥 ဒေါင်းလုပ်လုပ်နေပါသည်{dots}"
                    try:
                        if not progress_msg_id:
                            m = bot.send_message(chat_id, msg_text)
                            progress_msg_id = m.message_id
                        else:
                            bot.edit_message_text(msg_text, chat_id, progress_msg_id)
                    except:
                        # Ignore edit message errors (e.g., message unchanged, or network issues)
                        pass
                    last_update_time = now
                time.sleep(0.3)

            # Check for non-zero exit code if not stopped by user
            if proc.returncode != 0 and not stop_event.is_set():
                stderr_output = proc.stderr.read()
                print(f"yt-dlp download failed with return code {proc.returncode}: {stderr_output}")
                bot.send_message(chat_id, f"❌ ဒေါင်းလုပ်လုပ်ရာတွင် အမှားဖြစ်: {stderr_output.strip()[:100]}...")
                continue # Try next video in list if available

            # 3. Find the downloaded file
            files = [f for f in os.listdir(tmpdir) if f.endswith(".mp3")]
            if files:
                fpath = os.path.join(tmpdir, files[0])
                file_size = os.path.getsize(fpath)
                
                if file_size > MAX_FILESIZE:
                    bot.send_message(chat_id, f"⚠️ ဖိုင်အရွယ်အစားကြီးနေသည် ({round(file_size / (1024*1024), 2)}MB)။ Telegram မှ ပို့လို့မရပါ။")
                    # Break the loop, don't try next video
                    video_found = True
                    break

                caption = f"🎶 {title}\n\n_Music 4U မှ ပေးပို့နေပါသည်_ 🎧"
                thumb_url = data.get("thumbnail")
                
                # 4. Send the audio file to Telegram
                try:
                    bot.send_message(chat_id, "⬆️ Telegram သို့ ပို့နေပါသည်...")
                    thumb_file = None
                    
                    if thumb_url:
                        # Fetch thumbnail
                        img_response = requests.get(thumb_url, timeout=10)
                        img_response.raise_for_status() # Raise error for bad status codes
                        img = Image.open(BytesIO(img_response.content))
                        thumb_path = os.path.join(tmpdir, "thumb.jpg")
                        # Ensure thumbnail is small enough (max 320x320)
                        img.thumbnail((320, 320)) 
                        img.save(thumb_path)
                        thumb_file = open(thumb_path, "rb")

                    with open(fpath, "rb") as aud:
                        bot.send_audio(
                            chat_id, 
                            audio=aud, 
                            caption=caption, 
                            thumb=thumb_file, 
                            parse_mode="Markdown"
                        )
                    
                    if thumb_file:
                        thumb_file.close() # Close the file handle

                except Exception as send_e:
                    print(f"Error sending file to Telegram: {send_e}")
                    # Fallback: send without thumbnail
                    try:
                        bot.send_message(chat_id, "⚠️ Thumbnail ပို့ရာတွင် အမှားဖြစ်၍ သီချင်းသက်သက် ပို့ပါမည်။")
                        with open(fpath, "rb") as aud:
                            bot.send_audio(chat_id, audio=aud, caption=caption, parse_mode="Markdown")
                    except Exception as fallback_e:
                        bot.send_message(chat_id, f"❌ သီချင်းပို့ရာတွင် အမှားဖြစ်: {fallback_e}")
                        
                # 5. Success
                bot.send_message(chat_id, "✅ သီချင်း ပေးပို့ပြီးပါပြီ 🎧")
                video_found = True
                break # Exit the loop after successful download and send

        if not video_found and not stop_event.is_set():
            bot.send_message(chat_id, "🚫 ဖိုင်မတွေ့ပါ၊ အခြား keyword ဖြင့်စမ်းကြည့်ပါ။")

    except Exception as e:
        print(f"Main download error: {e}")
        bot.send_message(chat_id, f"❌ အမှားတစ်ခုဖြစ်ပါသည်: {e}")
    finally:
        # Crucial: always clean up the temporary directory
        shutil.rmtree(tmpdir, ignore_errors=True)
        print(f"Cleaned up temporary directory: {tmpdir}")

# ===== RUN BOT =====
def start_bot():
    print("✅ Bot is starting...")
    # Add a check for TOKEN
    if not TOKEN:
        print("FATAL ERROR: BOT_TOKEN is missing. Please check your .env file or Railway variables.")
        return
        
    # Load subs before starting polling
    load_subscribers()
    print(f"Loaded {len(subscribers)} subscribers.")

    # telebot.infinity_polling handles reconnection automatically
    bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=30)

# ===== MAIN =====
if __name__ == "__main__":
    keep_alive()  # Flask server thread
    start_bot()   # Run bot in main thread
