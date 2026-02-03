from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from dotenv import load_dotenv
import threading

# ================== INIT ==================
load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# ================== DISTRICT CONFIG ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

latest_sheet_data = []     # rows จาก Google Sheet
sheet_ready = False
data_lock = threading.Lock()

# ================== UTILS ==================
def clean_text(txt):
    return str(txt or "").replace(" ", "").strip().lower()

# ================== COLOR LOGIC ==================
def is_allowed_color(color_hex):
    if not color_hex:
        return False

    c = color_hex.replace("#", "").lower().strip()

    yellow = {
        "ffff00", "fff2cc", "ffe599",
        "fff100", "f1c232", "fbef24"
    }

    blue = {
        "00ffff",        # ฟ้าชัด
        "c9daf8", "a4c2f4",
        "cfe2f3", "d0e0e3", "a2c4c9"
    }

    return c in yellow or c in blue

# ================== API ENDPOINT ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready
    data = request.json

    if not data or "rows" not in data:
        return "Invalid payload", 400

    with data_lock:
        latest_sheet_data = data["rows"]
        sheet_ready = True

    return "OK", 200

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

# ================== SEARCH CORE (FIXED) ==================
def get_district_info(district_name):
    target = clean_text(district_name)

    with data_lock:
        rows = list(latest_sheet_data)

    if not rows:
        return None

    found_name = False

    # ✅ ไล่จากบน → ล่าง ตามลำดับชีท
    for row in rows:
        hospital_raw = row.get("hospital")
        hospital = clean_text(hospital_raw)

        # ✅ FIX ใหญ่ที่สุด (ไม่ต้องตรงเป๊ะ)
        if target not in hospital:
            continue

        found_name = True
        color = row.get("row_color")

        # สีไม่ผ่าน → ข้าม แต่ยังหาต่อ
        if not is_allowed_color(color):
            continue

        # ✅ เจอชื่อ + สีผ่าน
        return {
            "status": "success",
            "data": {
                "hospital": district_name,
                "partner": row.get("partner", ""),
                "note": row.get("note", "")
            }
        }

    # เจอชื่อ แต่ไม่มีสีผ่าน
    if found_name:
        return {"status": "no_color_match", "hospital": district_name}

    return None

# ================== MESSAGE HANDLER ==================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not sheet_ready:
        return

    raw_text = event.message.text.strip()
    raw_clean = clean_text(raw_text)

    matched_district = next(
        (d for d in BURIRAM_DISTRICTS if clean_text(d) in raw_clean),
        None
    )

    if not matched_district:
        return

    info = get_district_info(matched_district)

    # ===== มีรับกลับ =====
    if info and info["status"] == "success":
        res = info["data"]

        display_parts = []
        if res["partner"] and res["partner"].lower() != "none":
            display_parts.append(res["partner"])
        if res["note"] and res["note"].lower() != "none":
            display_parts.append(res["note"])

        detail = f" ({' '.join(display_parts)})" if display_parts else ""
        reply_text = f"มีรับกลับของ {res['hospital']}{detail}"

        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=reply_text),
                TextSendMessage(text="ล้อหมุนกี่โมงคะ?")
            ]
        )

    # ===== ไม่มีรับกลับ =====
    elif info and info["status"] == "no_color_match":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ไม่มีรับกลับของ {info['hospital']}")
        )

# ================== RUN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
