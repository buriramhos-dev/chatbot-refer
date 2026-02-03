from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import threading
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

# map ชื่ออำเภอแบบ clean
DISTRICT_MAP = {
    "".join(h.split()).lower(): h for h in BURIRAM_DISTRICTS
}

latest_rows = []
sheet_ready = False
lock = threading.Lock()

# ================= UTILS =================
def clean(txt):
    return str(txt or "").replace(" ", "").strip().lower()

# ✅ เช็กเฉพาะสีฟ้า + เหลือง (รองรับ Google Sheet)
def is_blue_or_yellow(color):
    c = str(color or "").strip().lower()
    return (
        c.startswith("#00b0f0") or   # ฟ้า
        c.startswith("#ffff00")     # เหลือง
    )

# ================= API =================
@app.route("/update", methods=["POST"])
def update():
    global latest_rows, sheet_ready
    data = request.json or {}
    rows = data.get("rows", [])

    # ❗ กันข้อมูลว่าง ไม่ล้างของเดิม
    if not rows:
        print("⚠️ IGNORE empty rows")
        return "IGNORED"

    with lock:
        latest_rows = rows
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
    rows.sort(key=lambda r: r.get("row_no", 0))

    for row in rows:
        if clean(row.get("hospital")) != target:
            continue

        found_name = True

        # ✅ ตอบเฉพาะสีฟ้า + เหลือง
        if not is_blue_or_yellow(row.get("color")):
            continue

        return {
            "hospital": hospital_name,
            "partner": row.get("partner", ""),
            "note": row.get("note", "")
        }

    if found_name:
        return "NO_ACCEPT"

    return None

# ================= LINE HANDLER =================
@handler.add(MessageEvent, message=TextMessage)
def handle(event):
    if not sheet_ready:
        return

    text = clean(event.message.text)

    # หาอำเภอจากข้อความ
    hospital = next(
        (real for key, real in DISTRICT_MAP.items() if key in text),
        None
    )

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
