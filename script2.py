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

numbers = db.numbers
user_numbers = db.user_numbers
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
        kb.add("📤 Upload Numbers", "🗑 Delete Country")
        kb.add("📊 Panel Status")
    kb.add("📞 Get Number")
    return kb

def country_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    for c in numbers.distinct("country"):
        kb.add(types.InlineKeyboardButton(c, callback_data=f"country|{c}"))
    return kb

def country_delete_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    for c in numbers.distinct("country"):
        kb.add(types.InlineKeyboardButton(c, callback_data=f"delcountry|{c}"))
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

# ================= UPLOAD NUMBERS =================
@bot.message_handler(func=lambda m: m.text == "📤 Upload Numbers")
def upload_numbers_start(m):
    if not is_admin(m.from_user.id):
        return
    msg = bot.send_message(m.chat.id, "🌍 Enter COUNTRY NAME:")
    bot.register_next_step_handler(msg, upload_numbers_country)

def upload_numbers_country(m):
    country = m.text.strip().upper()
    msg = bot.send_message(
        m.chat.id,
        f"✅ Country set: {country}\n\nSend numbers or upload .txt file"
    )
    bot.register_next_step_handler(msg, lambda x: save_numbers(x, country))

def save_numbers(m, country):
    added = 0
    try:
        if m.text:
            nums = [n.strip() for n in m.text.replace("\n", ",").split(",") if n.strip()]
        elif m.document:
            f = bot.get_file(m.document.file_id)
            content = bot.download_file(f.file_path).decode("utf-8", "ignore")
            nums = [n.strip() for n in content.replace("\n", ",").split(",") if n.strip()]
        else:
            bot.reply_to(m, "❌ Invalid input")
            return

        for n in nums:
            if not numbers.find_one({"number": n}):
                numbers.insert_one({
                    "country": country,
                    "number": n,
                    "added_at": datetime.utcnow()
                })
                added += 1

        bot.send_message(m.chat.id, f"✅ Added {added} numbers for {country}")

    except Exception as e:
        bot.send_message(m.chat.id, f"⚠️ Error: {e}")

# ================= DELETE COUNTRY =================
@bot.message_handler(func=lambda m: m.text == "🗑 Delete Country")
def delete_country(m):
    if not is_admin(m.from_user.id):
        return
    bot.send_message(
        m.chat.id,
        "🗑 Select country to delete:",
        reply_markup=country_delete_keyboard()
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("delcountry|"))
def confirm_delete_country(c):
    country = c.data.split("|")[1]
    numbers.delete_many({"country": country})
    bot.edit_message_text(
        f"🗑 All numbers deleted for {country}",
        c.message.chat.id,
        c.message.message_id
    )

# ================= USER =================
@bot.message_handler(func=lambda m: m.text == "📞 Get Number")
def get_number(m):
    if numbers.count_documents({}) == 0:
        bot.reply_to(m, "❌ No numbers available")
        return
    bot.send_message(m.chat.id, "🌍 Select country:", reply_markup=country_keyboard())

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
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "🆘 Support", "url": SUPPORT_URL},
                    {"text": "📲 Numbers", "url": NUMBERS_URL}
                ]]
            }
        },
        timeout=15
    )

# ================= OTP WORKER =================
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
