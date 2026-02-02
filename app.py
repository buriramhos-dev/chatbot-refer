"""
LINE Bot for Buriram Hospital Referral Check
Checks if a hospital has referral rounds available
"""

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from dotenv import load_dotenv
import requests
import threading

# ==================== INIT ====================
load_dotenv()
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

latest_sheet_data = None
sheet_ready = False

# ==================== CONSTANTS ====================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์", "คูเมือง", "กระสัง", "นางรอง", "หนองกี่", "ละหานทราย",
    "ประโคนชัย", "บ้านกรวด", "พุทไธสง", "ลำปลายมาศ", "สตึก", "บ้านด่าน",
    "ห้วยราช", "โนนสุวรรณ", "ปะคำ", "นาโพธิ์", "หนองหงส์", "พลับพลาชัย",
    "เฉลิมพระเกียรติ", "ชำนิ", "บ้านใหม่ไชยพจน์", "โนนดินแดง", "แคนดง",
    "ลำทะเมนชัย", "เมืองยาง", "ชุมพวง"
]

DISTRICT_COL = 10  # K
PARTNER_COL = 14   # O
NOTE_COL = 15      # P

# ==================== COLOR (แก้ตรงนี้สำคัญ) ====================
def normalize_color_to_rgb(color_data):
    """
    รับเฉพาะ backgroundColor จาก Google Sheets เท่านั้น
    รูปแบบ: { red: 0-1, green: 0-1, blue: 0-1 }
    """
    if not isinstance(color_data, dict):
        return None

    try:
        r = int(float(color_data.get("red", 0)) * 255)
        g = int(float(color_data.get("green", 0)) * 255)
        b = int(float(color_data.get("blue", 0)) * 255)
        return (r, g, b)
    except (ValueError, TypeError):
        return None


def get_color_type(color_data):
    """
    ตรวจสอบประเภทสี:
    - 'blue': สีฟ้า (มีรับกลับ)
    - 'yellow': สีเหลือง (มีรับกลับแบบอื่น)
    - None: สีอื่นๆ (ไม่มีรับกลับ)
    """
    rgb = normalize_color_to_rgb(color_data)
    if not rgb:
        return None

    r, g, b = rgb

    is_blue = (b >= 200 and g >= 200 and r <= 100)
    is_yellow = (r >= 200 and g >= 200 and b <= 100)

    if is_blue:
        return 'blue'
    elif is_yellow:
        return 'yellow'
    return None

# ==================== SHEET ====================
def fetch_sheet_data():
    global latest_sheet_data, sheet_ready

    url = os.getenv("GOOGLE_APPS_SCRIPT_URL")
    if not url:
        print("❌ GOOGLE_APPS_SCRIPT_URL not set")
        return

    try:
        print("🔄 Fetching Google Sheet...")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        if "full_sheet_data" in data:
            latest_sheet_data = data["full_sheet_data"]
            sheet_ready = True
            print(f"✅ Sheet loaded ({len(latest_sheet_data)} rows)")
    except Exception as e:
        print("❌ Fetch error:", e)


@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready
    data = request.json

    if not data or "full_sheet_data" not in data:
        return "Invalid payload", 400

    latest_sheet_data = data["full_sheet_data"]
    sheet_ready = True
    print("✅ Sheet updated from Apps Script")
    return "OK", 200

# ==================== CORE LOGIC ====================
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

        # เช็คเฉพาะ backgroundColor ฟ้า/เหลือง
        for col in [DISTRICT_COL, PARTNER_COL, NOTE_COL]:
            cell = cells[col]
            if not isinstance(cell, dict):
                continue

            bg = cell.get("backgroundColor")
            color_type = get_color_type(bg)
            
            if color_type:
                return {
                    "hospital": hospital_name,
                    "partner": str(cells[PARTNER_COL].get("value", "")).strip(),
                    "note": str(cells[NOTE_COL].get("value", "")).strip()
                }

    return None

# ==================== LINE CALLBACK ====================
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

    if not sheet_ready:
        fetch_sheet_data()

    if not isinstance(latest_sheet_data, dict):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⏳ กำลังซิงค์ข้อมูล กรุณาลองใหม่")
        )
        return

    replies = []
    has_available = False

    for d in districts:
        result = has_round_for_district(d)

        if result:
            has_available = True
            msg = f"✅ มีรับกลับ {result['hospital']}"
            if result["partner"]:
                msg += f" ({result['partner']})"
            if result["note"]:
                msg += f" {result['note']}"
        else:
            msg = f"❌ ไม่มีรอบรับกลับ {d}"

        replies.append(msg)

    messages = [TextSendMessage(text="\n".join(replies))]
    if has_available:
        messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

    line_bot_api.reply_message(event.reply_token, messages)

# ==================== RUN ====================
if __name__ == "__main__":
    threading.Thread(target=fetch_sheet_data, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
