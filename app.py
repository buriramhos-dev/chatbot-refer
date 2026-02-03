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

def clean(txt):
    return str(txt or "").replace(" ", "").strip().lower()

def is_allowed_color(color):
    if not color:
        return False
    c = color.replace("#", "").lower()
    yellow = {"ffff00","fff2cc","ffe599","fff100","f1c232","fbef24"}
    blue = {"00ffff","c9daf8","a4c2f4","cfe2f3","d0e0e3","a2c4c9"}
    return c in yellow or c in blue

def row_has_allowed_color(cells):
    for cell in cells:
        if is_allowed_color(cell.get("color")):
            return True
    return False

@app.route("/update", methods=["POST"])
def update():
    global latest_sheet_data, sheet_ready
    data = request.json
    with lock:
        latest_sheet_data = data.get("full_sheet_data", {})
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

def find_hospital(name):
    target = clean(name)

    with lock:
        data = latest_sheet_data.copy()

    for row in sorted(data.keys(), key=lambda x: int(x)):
        cells = data[row]
        if clean(cells[10]["value"]) != target:
            continue

        # ⭐ หัวใจของระบบ
        if not row_has_allowed_color(cells):
            continue

        partner = str(cells[14]["value"] or "").strip()
        note = str(cells[15]["value"] or "").strip()

        return partner, note

    return None

@handler.add(MessageEvent, message=TextMessage)
def handle(event):
    if not sheet_ready:
        return

    text = clean(event.message.text)
    hospital = next((h for h in BURIRAM_DISTRICTS if clean(h) in text), None)
    if not hospital:
        return

    result = find_hospital(hospital)

    if result:
        partner, note = result
        extra = " ".join(p for p in [partner, note] if p)
        msg = f"มีรับกลับของ {hospital}"
        if extra:
            msg += f" ({extra})"

        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=msg),
                TextSendMessage(text="ล้อหมุนกี่โมงคะ?")
            ]
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ไม่มีรับกลับของ {hospital}")
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
