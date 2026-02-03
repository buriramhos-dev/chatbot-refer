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

# ================= CONFIG =================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

latest_rows = []
sheet_ready = False
lock = threading.Lock()

# ================= UTILS =================
def clean(txt):
    return str(txt or "").replace(" ", "").strip().lower()

def is_allowed_color(color):
    if not color:
        return False

    c = color.replace("#", "").lower()

    yellow = {
        "ffff00", "fff2cc", "ffe599",
        "fff100", "f1c232", "fbef24"
    }
    blue = {
        "00ffff", "c9daf8", "a4c2f4",
        "cfe2f3", "d0e0e3", "a2c4c9"
    }
    return c in yellow or c in blue

# ================= API =================
@app.route("/update", methods=["POST"])
def update():
    global latest_rows, sheet_ready
    data = request.json

    with lock:
        latest_rows = data.get("rows", [])
        sheet_ready = True

    print("SYNC ROWS:", len(latest_rows))
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

# ================= CORE LOGIC =================
def find_hospital(hospital_name):
    target = clean(hospital_name)

    with lock:
        rows = list(latest_rows)

    found_name = False

    # ไล่จากบนลงล่าง (row_no น้อยก่อน)
    rows.sort(key=lambda r: r.get("row_no", 0))

    for row in rows:
        if clean(row.get("hospital")) != target:
            continue

        found_name = True

        if not is_allowed_color(row.get("row_color")):
            continue

        return {
            "hospital": hospital_name,
            "partner": row.get("partner", ""),
            "note": row.get("note", "")
        }

    if found_name:
        return "NO_COLOR"

    return None

# ================= LINE HANDLER =================
@handler.add(MessageEvent, message=TextMessage)
def handle(event):
    if not sheet_ready:
        return

    text = clean(event.message.text)
    hospital = next((h for h in BURIRAM_DISTRICTS if clean(h) in text), None)

    if not hospital:
        return

    result = find_hospital(hospital)

    if isinstance(result, dict):
        parts = []
        if result["partner"]:
            parts.append(result["partner"])
        if result["note"]:
            parts.append(result["note"])

        detail = f" ({' '.join(parts)})" if parts else ""
        reply = f"มีรับกลับของ {hospital}{detail}"

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
            TextSendMessage(text=f"ไม่มีรับกลับของ {hospital}")
        )

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
