#!/usr/bin/env python3
import os
import time
import html
import threading
import requests
from datetime import datetime
from telebot import TeleBot, types
from pymongo import MongoClient

# ================= ENV =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
MONGO_DB_URI = os.getenv("MONGO_DB_URI")

SUPPORT_URL = "https://t.me/botcasx"
NUMBERS_URL = "https://t.me/CyberOTPCore"

DB_NAME = "otp_bot"

# ================= INIT =================
bot = TeleBot(BOT_TOKEN)
bot.remove_webhook()
time.sleep(1)

mongo = MongoClient(MONGO_DB_URI)
db = mongo[DB_NAME]

numbers = db.numbers          # {country, number}
user_numbers = db.user_numbers # {number, user_id}
otps = db.otps
admins = db.admins
chats = db.chats

# ================= HELPERS =================
def is_owner(uid):
    return uid == OWNER_ID

def is_admin(uid):
    return is_owner(uid) or admins.find_one({"user_id": uid})

def mask_number(num):
    return num[:3] + "******" + num[-2:]

def main_keyboard(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if is_admin(uid):
        kb.add("📤 Upload Numbers", "📊 Panel Status")
    kb.add("📞 Get Number")
    return kb

def country_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    for c in numbers.distinct("country"):
        kb.add(types.InlineKeyboardButton(c, callback_data=f"country|{c}"))
    return kb

# ================= START =================
@bot.message_handler(commands=["start"])
def start(m):
    bot.send_message(
        m.chat.id,
        "【 ILY OTP BOT 】\n\nSelect option 👇",
        reply_markup=main_keyboard(m.from_user.id)
    )

# ================= OWNER / ADMIN =================
@bot.message_handler(commands=["addadmin"])
def add_admin(m):
    if not is_owner(m.from_user.id):
        return
    uid = int(m.text.split()[1])
    admins.update_one({"user_id": uid}, {"$set": {"user_id": uid}}, upsert=True)
    bot.reply_to(m, "✅ Admin added")

@bot.message_handler(commands=["addchat"])
def add_chat(m):
    if not is_admin(m.from_user.id):
        return
    cid = int(m.text.split()[1])
    chats.update_one({"chat_id": cid}, {"$set": {"chat_id": cid}}, upsert=True)
    bot.reply_to(m, "✅ Group added")

# ================= USER =================
@bot.message_handler(func=lambda m: m.text == "📞 Get Number")
def get_number(m):
    if numbers.count_documents({}) == 0:
        bot.reply_to(m, "❌ No numbers available")
        return
    bot.send_message(
        m.chat.id,
        "🌍 Select country:",
        reply_markup=country_keyboard()
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("country|"))
def give_number(c):
    country = c.data.split("|")[1]
    doc = numbers.find_one_and_delete({"country": country})
    if not doc:
        bot.answer_callback_query(c.id, "No numbers left")
        return

    user_numbers.update_one(
        {"number": doc["number"]},
        {"$set": {"user_id": c.from_user.id}},
        upsert=True
    )

    bot.edit_message_text(
        f"📞 Your Number:\n<code>{html.escape(doc['number'])}</code>\n\n⌛ Waiting for OTP…",
        c.message.chat.id,
        c.message.message_id,
        parse_mode="HTML"
    )

# ================= OTP FORMAT =================
def format_user_otp(o):
    return (
        "📩 *LIVE OTP RECEIVED*\n\n"
        f"📞 *Number:* `{o['number']}`\n"
        f"🔢 *OTP:* 🔥 `{o['otp']}` 🔥\n"
        f"🏷 *Service:* {o['service']}\n"
        f"🌍 *Country:* {o['country']}\n"
        f"🕒 *Time:* {o['date']}\n\n"
        f"💬 *SMS:*\n{o['message']}\n\n"
        "⚡ *CYBER CORE OTP*"
    )

def format_group_otp(o):
    return (
        "📩 *LIVE OTP RECEIVED*\n\n"
        f"📞 *Number:* `{mask_number(o['number'])}`\n"
        f"🔢 *OTP:* 🔥 `{o['otp']}` 🔥\n"
        f"🏷 *Service:* {o['service']}\n"
        f"🌍 *Country:* {o['country']}\n"
        f"🕒 *Time:* {o['date']}\n\n"
        f"💬 *SMS:*\n{o['message']}\n\n"
        "⚡ *CYBER CORE OTP*"
    )

def send(chat_id, text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "🆘 Support", "url": SUPPORT_URL},
                    {"text": "📲 Numbers", "url": NUMBERS_URL}
                ]
            ]
        }
    }, timeout=15)

# ================= OTP DISPATCHER =================
def otp_worker():
    while True:
        otp = otps.find_one({"sent": False})
        if not otp:
            time.sleep(3)
            continue

        owner = user_numbers.find_one({"number": otp["number"]})
        if owner:
            send(owner["user_id"], format_user_otp(otp))

        for g in chats.find():
            send(g["chat_id"], format_group_otp(otp))

        otps.update_one(
            {"_id": otp["_id"]},
            {"$set": {"sent": True, "sent_at": datetime.utcnow()}}
        )

# ================= MAIN =================
threading.Thread(target=otp_worker, daemon=True).start()
bot.infinity_polling()
