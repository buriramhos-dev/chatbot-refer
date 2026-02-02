from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import requests
import threading
import time
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ================== CONFIG ==================
SHEET_TTL = 180  # 3 นาที (Railway-safe)

latest_sheet_data = None
sheet_ready = False
last_fetch_time = 0

# ================== DISTRICT ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

# ================== COLOR ==================
def hex_to_rgb(hex_color):
    if not hex_color:
        return None
    hex_color = str(hex_color).lstrip("#").strip()
    if len(hex_color) != 6:
        return None
    try:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except:
        return None

def normalize_color_to_rgb(color_data):
    if not color_data:
        return None

    if isinstance(color_data, str):
        c = color_data.strip().upper()
        if not c:
            return None
        if c.startswith("#"):
            return hex_to_rgb(c)
        if len(c) == 6 and all(x in "0123456789ABCDEF" for x in c):
            return hex_to_rgb("#" + c)

    if isinstance(color_data, dict):
        if "rgbColor" in color_data:
            rgb = color_data["rgbColor"]
            r = int(float(rgb.get("red", 0)) * 255)
            g = int(float(rgb.get("green", 0)) * 255)
            b = int(float(rgb.get("blue", 0)) * 255)
            return (r, g, b)

    return None

def is_allowed_color(color_data):
    rgb = normalize_color_to_rgb(color_data)
    if not rgb:
        return False

    r, g, b = rgb
    is_blue = (b >= 200 and g >= 200 and r <= 100)
    is_yellow = (r >= 200 and g >= 200 and b <= 50)
    return is_blue or is_yellow

# ================== FETCH SHEET (Railway-safe) ==================
def fetch_sheet_data(force=False):
    global latest_sheet_data, sheet_ready, last_fetch_time

    # TTL
    if not force and latest_sheet_data and time.time() - last_fetch_time < SHEET_TTL:
        return

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
            last_fetch_time = time.time()
            print(f"✅ Sheet loaded | rows={len(latest_sheet_data)}")
    except Exception as e:
        print(f"❌ Fetch error: {e}")

# ================== UPDATE FROM APPS SCRIPT ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready, last_fetch_time
    data = request.json

    if not data or "full_sheet_data" not in data:
        return "Invalid payload", 400

    latest_sheet_data = data["full_sheet_data"]
    sheet_ready = True
    last_fetch_time = time.time()
    print("✅ Sheet pushed from Apps Script")
    return "OK"

# ================== CORE CHECK ==================
def has_round_for_district(district_name):
    if not isinstance(latest_sheet_data, dict):
        return None

    district_name = district_name.lower().strip()
    DISTRICT_COL = 10
    PARTNER_COL = 14
    NOTE_COL = 15

    rows = sorted(latest_sheet_data.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 9999)

    for row_idx, cells in rows:
        if row_idx == "1" or not isinstance(cells, list):
            continue

        cell = cells[DISTRICT_COL] if len(cells) > DISTRICT_COL else {}
        name = str(cell.get("value", "")).strip()
        if district_name not in name.lower():
            continue

        for col in [DISTRICT_COL, PARTNER_COL, NOTE_COL]:
            if col < len(cells) and isinstance(cells[col], dict):
                for k in cells[col]:
                    if "color" in k.lower() and is_allowed_color(cells[col][k]):
                        return {
                            "hospital": name,
                            "partner": str(cells[PARTNER_COL].get("value", "")).strip() if len(cells) > PARTNER_COL else "",
                            "note": str(cells[NOTE_COL].get("value", "")).strip() if len(cells) > NOTE_COL else ""
                        }
    return None

# ================== CALLBACK ==================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ================== MESSAGE ==================
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

    # 🚨 Railway-safe: fetch ทุกข้อความ
    fetch_sheet_data()

    if not isinstance(latest_sheet_data, dict):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⏳ กำลังซิงค์ข้อมูล กรุณาลองใหม่อีกครั้งค่ะ")
        )
        return

    replies = []
    follow = False

    for d in districts:
        result = has_round_for_district(d)

        # 🔁 retry ถ้าไม่เจอ
        if result is None:
            fetch_sheet_data(force=True)
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
