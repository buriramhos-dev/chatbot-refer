from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from dotenv import load_dotenv
import threading

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

latest_sheet_data = {}
sheet_ready = False
data_lock = threading.Lock()

# ================== UTILS ==================
def clean_text(txt):
    return str(txt or "").replace(" ", "").strip().lower()

# ================== COLOR LOGIC (ฟ้า + เหลือง เท่านั้น) ==================
def is_allowed_color(color_hex):
    if not color_hex:
        return False

    c = color_hex.replace("#", "").lower().strip()

    yellow = {
        "ffff00", "fff2cc", "ffe599",
        "fff100", "f1c232", "fbef24"
    }

    blue = {
        "00ffff", "c9daf8", "a4c2f4",
        "cfe2f3", "d0e0e3", "a2c4c9"
    }

    return c in yellow or c in blue

# ================== API ENDPOINT ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready
    data = request.json
    if not data or "full_sheet_data" not in data:
        return "Invalid payload", 400

    with data_lock:
        latest_sheet_data = data["full_sheet_data"]
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

# ================== SEARCH CORE ==================
def get_district_info(district_name):
    target = clean_text(district_name)

    HOSP_COL = 10  # K
    PART_COL = 14  # O
    NOTE_COL = 15  # P

    with data_lock:
        data = latest_sheet_data.copy()

    if not data:
        return None

    try:
        row_keys = sorted(data.keys(), key=lambda x: int(x))
    except:
        row_keys = sorted(data.keys())

    found_name = False

    # 🔑 ไล่จากบน → ล่าง และเอาแถวบนสุดที่เป็น ฟ้า/เหลือง
    for row in row_keys:
        if str(row) == "1":
            continue

        cells = data.get(row)
        if not isinstance(cells, list) or len(cells) <= NOTE_COL:
            continue

        h_cell = cells[HOSP_COL]
        h_name = clean_text(h_cell.get("value"))
        h_color = h_cell.get("color")

        if h_name == target:
            found_name = True

            # ❌ สีไม่ใช่ฟ้า/เหลือง → ข้าม
            if not is_allowed_color(h_color):
                continue

            partner = str(cells[PART_COL].get("value") or "").strip()
            note = str(cells[NOTE_COL].get("value") or "").strip()

            # ✅ เจอแถวแรกที่สีผ่าน → ใช้ทันที
            return {
                "status": "success",
                "data": {
                    "hospital": district_name,
                    "partner": partner,
                    "note": note
                }
            }

    # มีชื่อ แต่ไม่มีฟ้า/เหลืองเลย
    if found_name:
        return {"status": "no_color_match", "hospital": district_name}

    return None

# ================== MESSAGE HANDLER ==================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not sheet_ready:
        return

    raw_text = event.message.text
    raw_clean = clean_text(raw_text)

    matched = next(
        (d for d in BURIRAM_DISTRICTS if clean_text(d) in raw_clean),
        None
    )

    if not matched:
        return

    info = get_district_info(matched)

    if info and info["status"] == "success":
        res = info["data"]

        parts = []
        if res["partner"]:
            parts.append(res["partner"])
        if res["note"]:
            parts.append(res["note"])

        detail = f" ({' '.join(parts)})" if parts else ""
        reply = f"มีรับกลับของ {res['hospital']}{detail}"

        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=reply),
                TextSendMessage(text="ล้อหมุนกี่โมงคะ?")
            ]
        )

    elif info and info["status"] == "no_color_match":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ไม่มีรับกลับของ {info['hospital']}")
        )

# ================== RUN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
