from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os, threading
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

latest_sheet_data = {}
sheet_ready = False
lock = threading.Lock()

# ---------- UTILS ----------
def clean(txt):
    return str(txt or "").replace(" ", "").strip().lower()

def is_allowed_color(hex_color):
    if not hex_color:
        return False

    c = hex_color.replace("#", "").lower()

    yellow = {
        "ffff00", "fff2cc", "ffe599", "fff100", "f1c232"
    }
    blue = {
        "00ffff", "c9daf8", "a4c2f4", "cfe2f3", "d0e0e3"
    }
    return c in yellow or c in blue

def row_has_allowed_color(cells):
    for cell in cells:
        if isinstance(cell, dict):
            if is_allowed_color(cell.get("bg")):
                return True
    return False

# ---------- API ----------
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready
    data = request.json
    if not data or "full_sheet_data" not in data:
        return "Invalid payload", 400

    with lock:
        latest_sheet_data = data["full_sheet_data"]
        sheet_ready = True

    return "OK"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ---------- CORE LOGIC ----------
def get_district_info(name):
    target = clean(name)

    HOSP_COL = 10
    PART_COL = 14
    NOTE_COL = 15

    with lock:
        data = latest_sheet_data.copy()

    rows = sorted(data.keys(), key=lambda x: int(x))

    found_name = False

    for r in rows:
        cells = data[r]
        if len(cells) <= NOTE_COL:
            continue

        hosp = clean(cells[HOSP_COL].get("value"))

        if hosp == target:
            found_name = True

            # ❌ ข้ามแถวที่ไม่ใช่ฟ้า/เหลือง
            if not row_has_allowed_color(cells):
                continue

            partner = str(cells[PART_COL].get("value") or "").strip()
            note = str(cells[NOTE_COL].get("value") or "").strip()

            return {
                "status": "success",
                "hospital": name,
                "partner": partner,
                "note": note
            }

    if found_name:
        return {"status": "no_color", "hospital": name}

    return None

# ---------- LINE HANDLER ----------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not sheet_ready:
        return

    text = clean(event.message.text)

    district = next(
        (d for d in BURIRAM_DISTRICTS if clean(d) in text),
        None
    )

    if not district:
        return

    info = get_district_info(district)

    if info and info["status"] == "success":
        parts = []
        if info["partner"]:
            parts.append(info["partner"])
        if info["note"]:
            parts.append(info["note"])

        detail = f" ({' '.join(parts)})" if parts else ""
        reply = f"มีรับกลับของ {info['hospital']}{detail}"

        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=reply),
                TextSendMessage(text="ล้อหมุนกี่โมงคะ?")
            ]
        )

    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ไม่มีรับกลับของ {district}")
        )

# ---------- RUN ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
