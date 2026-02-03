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
    return str(txt or "").replace(" ", "").strip().lower()

# ================= API =================
@app.route("/update", methods=["POST"])
def update():
    global latest_rows, sheet_ready
    data = request.json or {}

    with lock:
        latest_rows = data.get("rows", [])
        sheet_ready = True

    print("✅ SYNC ROWS:", len(latest_rows))
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
def find_hospital_by_query(query_text):
    query = clean(query_text)

    with lock:
        rows = list(latest_rows)

    # เรียงจากบนลงล่าง
    rows.sort(key=lambda r: r.get("row_no", 0))

    for row in rows:
        hospital_name = clean(row.get("hospital"))

        # ✅ ใช้คำที่ user พิมพ์ ไปค้นชื่อ รพ.
        if query not in hospital_name:
            continue

        # ✅ ต้องเป็นแถวที่รับกลับ (ฟ้า / เหลือง)
        if not row.get("has_accept", False):
            continue

        return {
            "hospital": row.get("hospital"),
            "partner": row.get("partner", ""),
            "note": row.get("note", "")
        }

    return None

# ================= LINE HANDLER =================
@handler.add(MessageEvent, message=TextMessage)
def handle(event):
    if not sheet_ready:
        return

    user_text = event.message.text
    result = find_hospital_by_query(user_text)

    if isinstance(result, dict):
        parts = []
        if result["partner"]:
            parts.append(result["partner"])
        if result["note"]:
            parts.append(result["note"])

        detail = f" ({' '.join(parts)})" if parts else ""

        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(
                    text=f"มีรับกลับของ {result['hospital']}{detail}"
                ),
                TextSendMessage(text="ล้อหมุนกี่โมงคะ?")
            ]
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="ไม่มีรับกลับค่ะ")
        )

# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
