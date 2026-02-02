from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import requests
import time
import threading
from dotenv import load_dotenv

# ================== INIT ==================
load_dotenv()
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ================== CONFIG ==================
SHEET_TTL = 180
latest_sheet_data = None
last_fetch_time = 0
fetch_lock = threading.Lock()

# ================== DISTRICT ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

# ================== COLOR ==================
def normalize_color_to_rgb(color):
    if not isinstance(color, dict):
        return None

    r = int(float(color.get("red", 0)) * 255)
    g = int(float(color.get("green", 0)) * 255)
    b = int(float(color.get("blue", 0)) * 255)
    return (r, g, b)

def is_allowed_color(background_color):
    """
    มีรับกลับ = สีฟ้า หรือ สีเหลือง เท่านั้น
    """
    rgb = normalize_color_to_rgb(background_color)
    if not rgb:
        return False

    r, g, b = rgb

    is_blue = (b >= 200 and g >= 200 and r <= 120)
    is_yellow = (r >= 200 and g >= 200 and b <= 120)

    print(f"🎨 RGB={rgb} | blue={is_blue} | yellow={is_yellow}")
    return is_blue or is_yellow

# ================== FETCH SHEET ==================
def fetch_sheet_data(force=False):
    global latest_sheet_data, last_fetch_time

    with fetch_lock:
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
                last_fetch_time = time.time()
                print(f"✅ Sheet synced | rows={len(latest_sheet_data)}")
        except Exception as e:
            print(f"❌ Fetch error: {e}")

# ================== CORE CHECK ==================
def has_round_for_district(district_name):
    if not isinstance(latest_sheet_data, dict):
        return None

    DISTRICT_COL = 10
    PARTNER_COL = 14
    NOTE_COL = 15

    district_name = district_name.lower()

    rows = sorted(
        latest_sheet_data.items(),
        key=lambda x: int(x[0]) if x[0].isdigit() else 9999
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

        # ✅ เช็คสีจาก backgroundColor โดยตรง
        for col in [DISTRICT_COL, PARTNER_COL, NOTE_COL]:
            cell = cells[col]
            bg = cell.get("backgroundColor")

            if is_allowed_color(bg):
                return {
                    "hospital": hospital_name,
                    "partner": str(cells[PARTNER_COL].get("value", "")).strip(),
                    "note": str(cells[NOTE_COL].get("value", "")).strip(),
                }

    return False

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
            TextSendMessage(text="❌ กรุณาระบุโรงพยาบาลในจังหวัดบุรีรัมย์")
        )
        return

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

        if isinstance(result, dict):
            follow = True
            msg = f"มีรับกลับของ {result['hospital']}"
            if result["partner"]:
                msg += f" ({result['partner']})"
            if result["note"]:
                msg += f" ({result['note']})"
        else:
            msg = f"ไม่มีรอบรับกลับ {d}"

        replies.append(msg)

    messages = [TextSendMessage(text="\n".join(replies))]
    if follow:
        messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

    line_bot_api.reply_message(event.reply_token, messages)

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
