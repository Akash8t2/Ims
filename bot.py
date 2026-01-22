#!/usr/bin/env python3
import os
import time
import re
import json
import html
import threading
import logging
import requests
from datetime import datetime
from telebot import TeleBot, types
from pymongo import MongoClient

# ================= CONFIG =================

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))

MONGO_DB_URI = os.getenv("MONGO_DB_URI")
DB_NAME = "otp_bot"

AJAX_URL = "http://144.217.66.209/ints/agent/res/data_smscdr.php"
CHECK_INTERVAL = 10

COOKIES = {
    "PHPSESSID": os.getenv("PHPSESSID", "")
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01"
}

GROUP_LINK = "https://t.me/OtpRush"

# ================= INIT =================

bot = TeleBot(BOT_TOKEN)
session = requests.Session()
session.headers.update(HEADERS)
session.cookies.update(COOKIES)

mongo = MongoClient(MONGO_DB_URI, serverSelectionTimeoutMS=5000)
db = mongo[DB_NAME]

admins = db.admins
chats = db.chats
numbers = db.numbers
owners = db.number_owner
state = db.state

logging.basicConfig(level=logging.INFO)

# ================= HELPERS =================

def is_owner(uid):
    return uid == OWNER_ID

def is_admin(uid):
    return is_owner(uid) or admins.find_one({"user_id": uid})

def extract_otp(text):
    m = re.search(r"\b(\d{4,8})\b", text or "")
    return m.group(1) if m else "N/A"

def mask_number(num):
    return num[:3] + "******" + num[-2:] if len(num) > 6 else num

def build_payload():
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "fdate1": f"{today} 00:00:00",
        "fdate2": f"{today} 23:59:59",
        "iDisplayStart": 0,
        "iDisplayLength": 25
    }

# ================= BOT COMMANDS =================

@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(
        m.chat.id,
        "🔥 *OTP BOT READY*\n\nUse buttons below",
        parse_mode="Markdown",
        reply_markup=main_keyboard(m.from_user.id)
    )

def main_keyboard(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📞 Get Number")
    if is_admin(uid):
        kb.add("📤 Upload Numbers")
    return kb

# ---------- OWNER ONLY ----------

@bot.message_handler(commands=["addadmin"])
def add_admin(m):
    if not is_owner(m.from_user.id):
        return
    try:
        uid = int(m.text.split()[1])
        admins.update_one({"user_id": uid}, {"$set": {"user_id": uid}}, upsert=True)
        bot.reply_to(m, "✅ Admin added")
    except:
        bot.reply_to(m, "Usage: /addadmin user_id")

# ---------- ADMIN ----------

@bot.message_handler(commands=["addchat"])
def add_chat(m):
    if not is_admin(m.from_user.id):
        return
    try:
        cid = int(m.text.split()[1])
        chats.update_one({"chat_id": cid}, {"$set": {"chat_id": cid}}, upsert=True)
        bot.reply_to(m, "✅ Chat added")
    except:
        bot.reply_to(m, "Usage: /addchat chat_id")

# ================= NUMBER SYSTEM =================

@bot.message_handler(func=lambda m: m.text == "📞 Get Number")
def get_number(m):
    countries = numbers.distinct("country")
    kb = types.InlineKeyboardMarkup()
    for c in countries:
        kb.add(types.InlineKeyboardButton(c, callback_data=f"country|{c}"))
    bot.send_message(m.chat.id, "Select country:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("country|"))
def give_number(c):
    country = c.data.split("|", 1)[1]
    doc = numbers.find_one_and_delete({"country": country})
    if not doc:
        bot.answer_callback_query(c.id, "No numbers left")
        return

    num = doc["number"]
    owners.update_one(
        {"number": num},
        {"$set": {"number": num, "user_id": c.from_user.id}},
        upsert=True
    )

    bot.edit_message_text(
        f"<b>{country}</b>\n\n<code>{html.escape(num)}</code>\n\n⌛ Waiting for OTP…",
        c.message.chat.id,
        c.message.message_id,
        parse_mode="HTML"
    )

# ---------- UPLOAD TXT ----------

@bot.message_handler(content_types=["document"])
def upload_txt(m):
    if not is_admin(m.from_user.id):
        return
    file = bot.download_file(bot.get_file(m.document.file_id).file_path)
    lines = file.decode(errors="ignore").splitlines()
    count = 0
    for line in lines:
        if line.strip():
            numbers.insert_one({"country": "AUTO", "number": line.strip()})
            count += 1
    bot.reply_to(m, f"✅ {count} numbers added")

# ================= OTP WORKER =================

def otp_worker():
    while True:
        try:
            r = session.get(AJAX_URL, params=build_payload(), timeout=20)
            rows = r.json().get("aaData", [])
            rows = [r for r in rows if r and isinstance(r[0], str)]
            if not rows:
                time.sleep(CHECK_INTERVAL)
                continue

            rows.sort(key=lambda x: datetime.strptime(x[0], "%Y-%m-%d %H:%M:%S"), reverse=True)
            row = rows[0]
            uid = row[0] + row[2] + (row[5] or "")

            last = state.find_one({"_id": "state"})
            if last and last.get("last_uid") == uid:
                time.sleep(CHECK_INTERVAL)
                continue

            state.update_one({"_id": "state"}, {"$set": {"last_uid": uid}}, upsert=True)

            number = row[2]
            if not number.startswith("+"):
                number = "+" + number

            otp = extract_otp(row[5])

            msg_user = f"📩 OTP\n\n📞 `{number}`\n🔢 `{otp}`"
            msg_group = f"📩 OTP\n\n📞 `{mask_number(number)}`\n🔢 `{otp}`"

            for c in chats.find():
                bot.send_message(c["chat_id"], msg_group, parse_mode="Markdown")

            owner = owners.find_one({"number": number})
            if owner:
                bot.send_message(owner["user_id"], msg_user, parse_mode="Markdown")

        except Exception as e:
            logging.error(e)

        time.sleep(CHECK_INTERVAL)

# ================= MAIN =================

threading.Thread(target=otp_worker, daemon=True).start()
bot.remove_webhook()
time.sleep(1)
bot.infinity_polling()
