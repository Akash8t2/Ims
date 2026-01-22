#!/usr/bin/env python3
import os
import time
import html
import threading
import re
import requests
from datetime import datetime
from telebot import TeleBot, types
from pymongo import MongoClient

# ================= CONFIG =================

BOT_TOKEN = "7448362382:AAGzYcF4XH5cAOIOsrvJ6E9MXqjnmOdKs2o"
OWNER_ID = 5397621246          # only owner can add admins
MONGO_DB_URI = "mongodb+srv://akkingisin2026_db_user:JGPAXJSayxR9yFen@cluster0.hrbb5tc.mongodb.net/?appName=Cluster0"
DB_NAME = "otp_bot"

AJAX_URL = "http://144.217.66.209/ints/agent/res/data_smscdr.php"
CHECK_INTERVAL = 10

COOKIES = {
    "PHPSESSID": "9e49b48530129a97ed51bacb04d4575f"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01"
}

GROUP_LINK = "https://t.me/OtpRush"
CHANNEL_LINK = "https://t.me/mailtwist"

# ================= INIT =================

bot = TeleBot(BOT_TOKEN)
session = requests.Session()
session.headers.update(HEADERS)
session.cookies.update(COOKIES)

mongo = MongoClient(MONGO_DB_URI)
db = mongo[DB_NAME]

admins_col = db.admins
chats_col = db.chats
numbers_col = db.numbers
owners_col = db.number_owner
state_col = db.state

# ================= HELPERS =================

def is_owner(uid):
    return uid == OWNER_ID

def is_admin(uid):
    return admins_col.find_one({"user_id": uid}) is not None or is_owner(uid)

def extract_otp(text):
    m = re.search(r"\b(\d{4,8})\b", text or "")
    return m.group(1) if m else "N/A"

def mask_number(num):
    if len(num) < 6:
        return num
    return num[:3] + "******" + num[-2:]

def build_payload():
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "fdate1": f"{today} 00:00:00",
        "fdate2": f"{today} 23:59:59",
        "iDisplayStart": 0,
        "iDisplayLength": 25
    }

# ================= KEYBOARDS =================

def main_keyboard(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if is_admin(uid):
        kb.add("📤 Upload Numbers", "📊 Panel Status")
    kb.add("📞 Get Number")
    return kb

def country_inline():
    kb = types.InlineKeyboardMarkup(row_width=2)
    for c in numbers_col.distinct("country"):
        kb.add(types.InlineKeyboardButton(c, callback_data=f"country|{c}"))
    return kb

# ================= START =================

@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(
        m.chat.id,
        "【 ILY OTP BOT 】",
        reply_markup=main_keyboard(m.from_user.id)
    )

# ================= ADMIN COMMANDS =================

@bot.message_handler(commands=["addadmin"])
def add_admin(m):
    if not is_owner(m.from_user.id):
        return
    try:
        uid = int(m.text.split()[1])
        admins_col.update_one({"user_id": uid}, {"$set": {"user_id": uid}}, upsert=True)
        bot.reply_to(m, "Admin added")
    except:
        pass

@bot.message_handler(commands=["addchat"])
def add_chat(m):
    if not is_admin(m.from_user.id):
        return
    try:
        cid = int(m.text.split()[1])
        chats_col.update_one({"chat_id": cid}, {"$set": {"chat_id": cid}}, upsert=True)
        bot.reply_to(m, "Chat added")
    except:
        pass

# ================= NUMBER SYSTEM =================

@bot.message_handler(func=lambda m: m.text == "📞 Get Number")
def get_number(m):
    bot.send_message(m.chat.id, "Select country:", reply_markup=country_inline())

@bot.callback_query_handler(func=lambda c: c.data.startswith("country|"))
def give_number(c):
    country = c.data.split("|", 1)[1]
    doc = numbers_col.find_one_and_delete({"country": country})
    if not doc:
        bot.answer_callback_query(c.id, "No numbers left")
        return

    num = doc["number"]
    owners_col.update_one(
        {"number": num},
        {"$set": {"number": num, "user_id": c.from_user.id}},
        upsert=True
    )

    text = (
        f"🌍 <b>{country}</b>\n\n"
        f"<code>{html.escape(num)}</code>\n\n"
        "⌛ Waiting for OTP..."
    )
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💬 OTP GROUP", url=GROUP_LINK))

    bot.edit_message_text(
        text,
        c.message.chat.id,
        c.message.message_id,
        parse_mode="HTML",
        reply_markup=kb
    )

# ================= UPLOAD NUMBERS =================

@bot.message_handler(func=lambda m: m.text == "📤 Upload Numbers" and is_admin(m.from_user.id))
def upload_numbers(m):
    msg = bot.send_message(m.chat.id, "Send country name:")
    bot.register_next_step_handler(msg, ask_numbers)

def ask_numbers(m):
    country = m.text.strip()
    msg = bot.send_message(m.chat.id, "Send numbers (comma/newline):")
    bot.register_next_step_handler(msg, lambda x: save_numbers(x, country))

def save_numbers(m, country):
    nums = [n.strip() for n in m.text.replace("\n", ",").split(",") if n.strip()]
    for n in nums:
        numbers_col.insert_one({"country": country, "number": n})
    bot.send_message(m.chat.id, f"Added {len(nums)} numbers")

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

            state = state_col.find_one({"_id": "state"})
            if state and state.get("last_uid") == uid:
                time.sleep(CHECK_INTERVAL)
                continue

            state_col.update_one(
                {"_id": "state"},
                {"$set": {"last_uid": uid}},
                upsert=True
            )

            number = row[2]
            if not number.startswith("+"):
                number = "+" + number

            otp = extract_otp(row[5])

            msg_user = (
                "📩 LIVE OTP\n\n"
                f"📞 `{number}`\n"
                f"🔢 `{otp}`"
            )

            msg_group = (
                "📩 LIVE OTP\n\n"
                f"📞 `{mask_number(number)}`\n"
                f"🔢 `{otp}`"
            )

            for chat in chats_col.find():
                bot.send_message(chat["chat_id"], msg_group, parse_mode="Markdown")

            owner = owners_col.find_one({"number": number})
            if owner:
                bot.send_message(owner["user_id"], msg_user, parse_mode="Markdown")

        except:
            pass

        time.sleep(CHECK_INTERVAL)

# ================= MAIN =================

threading.Thread(target=otp_worker, daemon=True).start()
bot.infinity_polling()
