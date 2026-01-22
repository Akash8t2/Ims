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

numbers.create_index("number", unique=True)
user_numbers.create_index("number", unique=True)
admins.create_index("user_id", unique=True)
chats.create_index("chat_id", unique=True)

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
        kb.add("📊 Panel Status", "📊 Chats Status")
        kb.add("📊 Admin Status", "📊 Users Status")
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
        "【 ILY OTP BOT 】",
        reply_markup=main_keyboard(m.from_user.id)
    )

# ================= OWNER / ADMIN =================
@bot.message_handler(commands=["addadmin"])
def add_admin(m):
    if not is_owner(m.from_user.id):
        bot.reply_to(m, "Not allowed")
        return
    uid = int(m.text.split()[1])
    admins.update_one({"user_id": uid}, {"$set": {"user_id": uid}}, upsert=True)
    bot.reply_to(m, f"Admin added: {uid}")

@bot.message_handler(commands=["addchat"])
def add_chat(m):
    if not is_admin(m.from_user.id):
        bot.reply_to(m, "Not allowed")
        return
    cid = int(m.text.split()[1])
    chats.update_one({"chat_id": cid}, {"$set": {"chat_id": cid}}, upsert=True)
    bot.reply_to(m, f"Chat added: {cid}")

# ================= STATUS =================
@bot.message_handler(func=lambda m: m.text == "📊 Chats Status")
def chats_status(m):
    if not is_admin(m.from_user.id):
        return
    count = chats.count_documents({})
    text = f"Chats Count: {count}\n\n"
    for c in chats.find():
        text += f"{c['chat_id']}\n"
    bot.send_message(m.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "📊 Admin Status")
def admin_status(m):
    if not is_admin(m.from_user.id):
        return
    text = f"Owner: {OWNER_ID}\n\nAdmins:\n"
    for a in admins.find():
        text += f"{a['user_id']}\n"
    bot.send_message(m.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "📊 Users Status")
def users_status(m):
    if not is_admin(m.from_user.id):
        return
    total = user_numbers.count_documents({})
    text = f"Total Users With Numbers: {total}\n\n"
    for u in user_numbers.find():
        text += f"User: {u['user_id']} | {u['number']} ({u['country']})\n"
    bot.send_message(m.chat.id, text)

# ================= UPLOAD NUMBERS =================
@bot.message_handler(func=lambda m: m.text == "📤 Upload Numbers")
def upload_numbers_start(m):
    if not is_admin(m.from_user.id):
        return
    msg = bot.send_message(m.chat.id, "Enter COUNTRY NAME:")
    bot.register_next_step_handler(msg, upload_numbers_country)

def upload_numbers_country(m):
    country = m.text.strip().upper()
    msg = bot.send_message(
        m.chat.id,
        f"Country set: {country}\nSend numbers or upload .txt"
    )
    bot.register_next_step_handler(msg, lambda x: save_numbers(x, country))

def save_numbers(m, country):
    added = 0
    if m.text:
        nums = [n.strip() for n in m.text.replace("\n", ",").split(",") if n.strip()]
    elif m.document:
        f = bot.get_file(m.document.file_id)
        content = bot.download_file(f.file_path).decode("utf-8", "ignore")
        nums = [n.strip() for n in content.replace("\n", ",").split(",") if n.strip()]
    else:
        return

    for n in nums:
        try:
            numbers.insert_one({
                "country": country,
                "number": n,
                "added_at": datetime.utcnow()
            })
            added += 1
        except:
            pass

    bot.send_message(m.chat.id, f"Numbers added: {added}")

# ================= DELETE COUNTRY =================
@bot.message_handler(func=lambda m: m.text == "🗑 Delete Country")
def delete_country(m):
    if not is_admin(m.from_user.id):
        return
    bot.send_message(
        m.chat.id,
        "Select country:",
        reply_markup=country_delete_keyboard()
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("delcountry|"))
def confirm_delete_country(c):
    country = c.data.split("|")[1]
    numbers.delete_many({"country": country})
    user_numbers.delete_many({"country": country})
    bot.edit_message_text(
        f"Country deleted: {country}",
        c.message.chat.id,
        c.message.message_id
    )

# ================= PANEL STATUS =================
@bot.message_handler(func=lambda m: m.text == "📊 Panel Status")
def panel_status(m):
    if not is_admin(m.from_user.id):
        return

    text = "PANEL STATUS\n\n"
    total_available = 0
    total_used = 0

    countries = set(numbers.distinct("country")) | set(user_numbers.distinct("country"))
    for c in sorted(countries):
        available = numbers.count_documents({"country": c})
        used = user_numbers.count_documents({"country": c})
        total_available += available
        total_used += used
        text += f"{c}\nAvailable: {available}\nUsed: {used}\n\n"

    text += f"TOTAL AVAILABLE: {total_available}\nTOTAL USED: {total_used}"
    bot.send_message(m.chat.id, text)

# ================= USER =================
@bot.message_handler(func=lambda m: m.text == "📞 Get Number")
def get_number(m):
    if numbers.count_documents({}) == 0:
        bot.reply_to(m, "No numbers available")
        return
    bot.send_message(
        m.chat.id,
        "Select country:",
        reply_markup=country_keyboard()
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("country|"))
def give_number(c):
    country = c.data.split("|")[1]
    doc = numbers.find_one_and_delete({"country": country})
    if not doc:
        return

    user_numbers.update_one(
        {"number": doc["number"]},
        {"$set": {
            "user_id": c.from_user.id,
            "country": country,
            "assigned_at": datetime.utcnow()
        }},
        upsert=True
    )

    bot.edit_message_text(
        f"<code>{html.escape(doc['number'])}</code>\nWaiting for OTP…",
        c.message.chat.id,
        c.message.message_id,
        parse_mode="HTML"
    )

# ================= OTP FORMAT =================
def format_user_otp(o):
    return (
        "📩 *LIVE OTP RECEIVED*\n\n"
        f"📞 *Number:* `{o['number']}`\n"
        f"🔢 *OTP:* `{o['otp']}`\n"
        f"🏷 *Service:* {o['service']}\n"
        f"🌍 *Country:* {o['country']}\n"
        f"🕒 *Time:* {o['date']}\n\n"
        f"💬 *SMS:*\n{o['message']}"
    )

def format_group_otp(o):
    return (
        "📩 *LIVE OTP RECEIVED*\n\n"
        f"📞 *Number:* `{mask_number(o['number'])}`\n"
        f"🔢 *OTP:* `{o['otp']}`\n"
        f"🏷 *Service:* {o['service']}\n"
        f"🌍 *Country:* {o['country']}\n"
        f"🕒 *Time:* {o['date']}\n\n"
        f"💬 *SMS:*\n{o['message']}"
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
                    {"text": "Support", "url": SUPPORT_URL},
                    {"text": "Numbers", "url": NUMBERS_URL}
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
