"""
LINE Bot for Buriram Hospital Referral Check
ตอบว่ามีรับกลับเฉพาะแถวที่เป็น "สีฟ้า หรือ สีเหลือง"
"""

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from dotenv import load_dotenv
import requests
import threading

# ================== INIT ==================
load_dotenv()
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_APPS_SCRIPT_URL = os.getenv("GOOGLE_APPS_SCRIPT_URL")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

latest_sheet_data = None

# ================== CONSTANT ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

DISTRICT_COL = 10  # K
PARTNER_COL = 14   # O
NOTE_COL = 15      # P

# ================== COLOR (เอาแค่ฟ้า/เหลือง) ==================
def is_allowed_color(bg):
    """
    รับเฉพาะ backgroundColor จาก Google Sheets
    รูปแบบ { red, green, blue } ค่า 0-1
    """
    if not isinstance(bg, dict):
        return False

    try:
        r = int(bg.get("red", 0) * 255)
        g = int(bg.get("green", 0) * 255)
        b = int(bg.get("blue", 0) * 255)
    except Exception:
        return False

    # 🟦 ฟ้า (cyan)
    is_blue = (b >= 200 and g >= 200 and r <= 100)
    # 🟨 เหลือง (yellow)
    is_yellow = (r >= 200 and g >= 200 and b <= 100)

    return is_blue or is_yellow

# ================== SHEET ==================
def fetch_sheet_data():
    global latest_sheet_data
    try:
        r = requests.get(GOOGLE_APPS_SCRIPT_URL, timeout=10)
        r.raise_for_status()
        latest_sheet_data = r.json().get("full_sheet_data")
        print("✅ Sheet loaded")
    except Exception as e:
        print("❌ Sheet error:", e)

@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data
    latest_sheet_data = request.json.get("full_sheet_data")
    print("✅ Sheet updated")
    return "OK", 200

# ================== CORE ==================
def has_round_for_district(district_name):
    if not isinstance(latest_sheet_data, dict):
        return None

    district_name = district_name.lower().strip()

    rows = sorted(
        latest_sheet_data.items(),
        key=lambda x: int(x[0]) if x[0].isdigit() else 999999
    )

    for row_idx, cells in rows:
        if row_idx == "1" or not isinstance(cells, list):
            continue
        if len(cells) <= NOTE_COL:
            continue

        hospital_cell = cells[DISTRICT_COL]
        hospital_name = str(hospital_cell.get("value", "")).strip()

        if district_name not in hospital_name.lower():
            continue

        # 🔑 เช็คเฉพาะ backgroundColor
        for col in [DISTRICT_COL, PARTNER_COL, NOTE_COL]:
            cell = cells[col]
            if not isinstance(cell, dict):
                continue

            bg = cell.get("backgroundColor")
            if is_allowed_color(bg):
                return {
                    "hospital": hospital_name,
                    "partner": str(cells[PARTNER_COL].get("value", "")).strip(),
                    "note": str(cells[NOTE_COL].get("value", "")).strip()
                }

    return None

# ================== LINE ==================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.lower()
    districts = [d for d in BURIRAM_DISTRICTS if d.lower() in text]

    if not districts:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ กรุณาระบุโรงพยาบาลในบุรีรัมย์")
        )
        return

    if not latest_sheet_data:
        fetch_sheet_data()

    replies = []
    follow = False

    for d in districts:
        result = has_round_for_district(d)
        if result:
            follow = True
            msg = f"มีรับกลับของ {result['hospital']}"
            if result["partner"]:
                msg += f"({result['partner']})"
            if result["note"]:
                msg += f"({result['note']})"
        else:
            msg = f"ไม่มีรอบรับกลับ {d}"

        replies.append(msg)

    messages = [TextSendMessage(text="\n".join(replies))]
    if follow:
        messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

    line_bot_api.reply_message(event.reply_token, messages)

# ================== RUN ==================
if __name__ == "__main__":
    threading.Thread(target=fetch_sheet_data, daemon=True).start()
    app.run(host="0.0.0.0", port=5000)
