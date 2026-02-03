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

latest_rows = []
sheet_ready = False
lock = threading.Lock()

# ================= UTILS =================
def clean(txt):
    return str(txt or "").strip().lower()

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
def find_hospital_from_text(text):
    target_text = clean(text)

    with lock:
        rows = list(latest_rows)

    rows.sort(key=lambda r: r.get("row_no", 0))

    for row in rows:
        hospital_name = row.get("hospital", "")
        if clean(hospital_name) and clean(hospital_name) in target_text:

            # เจอชื่อโรงพยาบาลแล้ว → เช็คสี
            if not is_allowed_color(row.get("row_color")):
                return "NO_COLOR", hospital_name

            return "OK", {
                "hospital": hospital_name,
                "partner": row.get("partner", "").strip(),
                "note": row.get("note", "").strip()
            }

    return "NOT_FOUND", None

# ================= LINE HANDLER =================
@handler.add(MessageEvent, message=TextMessage)
def handle(event):
    if not sheet_ready:
        return

    text = event.message.text
    status, result = find_hospital_from_text(text)

    # ❌ ไม่พบชื่อโรงพยาบาล
    if status == "NOT_FOUND":
        return

    # ❌ เจอชื่อ แต่สีไม่ใช่ฟ้า/เหลือง
    if status == "NO_COLOR":
        hospital = result
        reply = f"ไม่มีรับกลับของ {hospital}"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return


    if status == "OK":
        hospital = result["hospital"]
        parts = []

        if result["partner"]:
            parts.append(result["partner"])
        if result["note"]:
            parts.append(result["note"])

        detail = f" ({' '.join(parts)})" if parts else ""
        reply = f"มีรับกลับของ {hospital}{detail}"

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
