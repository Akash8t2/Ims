#!/usr/bin/env python3
import os
import time
import re
import logging
import requests
from datetime import datetime
from pymongo import MongoClient

# ================= ENV CONFIG =================
AJAX_URL = os.getenv(
    "AJAX_URL",
    "http://144.217.66.209/ints/agent/res/data_smscdr.php"
)

MONGO_DB_URI = os.getenv("MONGO_DB_URI")
DB_NAME = "otp_bot"

PHPSESSID = os.getenv("PHPSESSID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "10"))

# ================= LOGGING =================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ================= SESSION =================
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01"
})
session.cookies.update({
    "PHPSESSID": PHPSESSID
})

# ================= MONGO =================
mongo = MongoClient(MONGO_DB_URI)
db = mongo[DB_NAME]

otps = db.otps
state = db.state   # store last_uid

# ================= STATE =================
def get_last_uid():
    doc = state.find_one({"_id": "last"})
    return doc["uid"] if doc else None

def set_last_uid(uid):
    state.update_one(
        {"_id": "last"},
        {"$set": {"uid": uid}},
        upsert=True
    )

# ================= HELPERS =================
def extract_otp(text):
    if not text:
        return None
    m = re.search(r"\b(\d{4,8})\b", text)
    return m.group(1) if m else None

def build_payload():
    today = datetime.now().strftime("%Y-%m-%d")
    return {
        "fdate1": f"{today} 00:00:00",
        "fdate2": f"{today} 23:59:59",
        "frange": "",
        "fclient": "",
        "fnum": "",
        "fcli": "",
        "fgdate": "",
        "fgmonth": "",
        "fgrange": "",
        "fgclient": "",
        "fgnumber": "",
        "fgcli": "",
        "fg": 0,
        "sEcho": 1,
        "iColumns": 9,
        "iDisplayStart": 0,
        "iDisplayLength": 25,
        "iSortCol_0": 0,
        "sSortDir_0": "desc",
        "iSortingCols": 1
    }

# ================= CORE =================
def fetch_latest_sms():
    try:
        r = session.get(AJAX_URL, params=build_payload(), timeout=20)

        # ---- HARD JSON SAFETY ----
        if r.status_code != 200:
            return
        if not r.text or not r.text.strip().startswith("{"):
            return

        data = r.json()
        rows = data.get("aaData", [])
        if not rows:
            return

        valid_rows = []
        for row in rows:
            if not isinstance(row, list):
                continue
            if not row or not isinstance(row[0], str):
                continue
            if not re.match(r"\d{4}-\d{2}-\d{2}", row[0]):
                continue
            valid_rows.append(row)

        if not valid_rows:
            return

        valid_rows.sort(
            key=lambda x: datetime.strptime(x[0], "%Y-%m-%d %H:%M:%S"),
            reverse=True
        )

        row = valid_rows[0]

        date = row[0]
        route_raw = row[1] or "Unknown"
        number = row[2] or ""
        service = row[3] or "Unknown"
        message = row[5] or ""

        if not number:
            return

        if not number.startswith("+"):
            number = "+" + number

        otp = extract_otp(message)
        if not otp:
            return

        country = route_raw.split("-")[0]
        uid = f"{date}:{number}:{otp}"

        last_uid = get_last_uid()

        # ---- FIRST RUN BASELINE ----
        if last_uid is None:
            set_last_uid(uid)
            logging.info("Baseline UID set")
            return

        # ---- DUPLICATE CHECK ----
        if uid == last_uid:
            return

        if otps.find_one({"uid": uid}):
            set_last_uid(uid)
            return

        # ---- SAVE OTP ----
        otps.insert_one({
            "uid": uid,
            "date": date,
            "number": number,
            "otp": otp,
            "service": service,
            "country": country,
            "route": route_raw,
            "message": message,
            "sent": False,
            "created_at": datetime.utcnow()
        })

        set_last_uid(uid)
        logging.info(f"NEW OTP SAVED → {number} | {otp}")

    except Exception as e:
        logging.exception("FETCH ERROR")

# ================= LOOP =================
logging.info("🚀 SCRIPT 1 STARTED (OTP FETCHER)")

while True:
    fetch_latest_sms()
    time.sleep(CHECK_INTERVAL)
