from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback
import os
from dotenv import load_dotenv
import re

# ================== SETUP ==================
load_dotenv()
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN, timeout=15)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ================== DATA ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์", "คูเมือง", "กระสัง", "นางรอง", "หนองกี่",
    "ละหานทราย", "ประโคนชัย", "บ้านกรวด", "พุทไธสง", "ลำปลายมาศ",
    "สตึก", "บ้านด่าน", "ห้วยราช", "โนนสุวรรณ", "ปะคำ",
    "นาโพธิ์", "หนองหงส์", "พลับพลาชัย", "เฉลิมพระเกียรติ", "ชำนิ",
    "บ้านใหม่ไชยพจน์", "โนนดินแดง", "แคนดง", "ลำทะเมนชัย",
    "เมืองยาง", "ชุมพวง"
]

# เก็บข้อมูล Sheet ล่าสุด
latest_sheet_data = {}

# ================== REGEX เวลา ==================
TIME_PATTERN = re.compile(
    r'\b(?:'
    r'([01]?\d|2[0-3])[:.]([0-5]\d)'
    r'|([0-2]?\d)\s*(?:โมง|น\.)'
    r')\b'
)

# ================== RECEIVE SHEET UPDATE ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data
    data = request.json

    if not data or "full_sheet_data" not in data:
        return "Invalid data format", 400

    latest_sheet_data.clear()
    latest_sheet_data.update(data["full_sheet_data"])

    return "OK", 200

# ================== CORE LOGIC (FIX BUG ลำทะเมนชัย) ==================
def has_round_for_district(district_name: str):
    district_lower = district_name.lower().strip()

    # ไล่จากแถวบน → ล่าง (ตามลำดับจริงใน Sheet)
    for row_number in sorted(map(int, latest_sheet_data.keys())):
        cells = latest_sheet_data.get(str(row_number))
        if not isinstance(cells, dict):
            continue

        hospital_value = str(
            cells.get("HOSPITAL", {}).get("value", "")
        ).lower().strip()

        if district_lower not in hospital_value:
            continue

        # 🔥 เจอชื่อโรงพยาบาลแล้ว = ตัดสินที่แถวนี้ทันที
        if cells.get("_has_return_trip") is True:
            partner = str(
                cells.get("พันธมิตร", {}).get("value", "")
            ).strip()

            note = str(
                cells.get("หมายเหตุ", {}).get("value", "")
            ).strip()

            return {
                "partner": partner or "",
                "note": note or ""
            }

        # ❌ เจอชื่อ แต่ไม่ใช่สีฟ้า/เหลือง → ไม่มีรับกลับ
        return None

    return None

# ================== LINE CALLBACK ==================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception:
        traceback.print_exc()
        abort(500)

    return "OK"

# ================== LINE MESSAGE ==================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        text_raw = event.message.text.strip()
        text = text_raw.lower()

        # ตรวจจับเวลา
        if TIME_PATTERN.search(text):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"ล้อหมุนเวลา {text_raw} นะคะ")
            )
            return

        found_districts = [
            d for d in BURIRAM_DISTRICTS
            if d.lower() in text
        ]

        if not found_districts:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาระบุชื่อโรงพยาบาลในบุรีรัมย์ค่ะ")
            )
            return

        replies = []
        follow_up = False

        for d in found_districts:
            result = has_round_for_district(d)

            if result:
                follow_up = True
                msg = f"มีรับกลับของ {d}"

                extra = []
                if result["partner"]:
                    extra.append(result["partner"])
                if result["note"]:
                    extra.append(result["note"])

                if extra:
                    msg += f" ({', '.join(extra)})"
            else:
                msg = f"ไม่มีรับกลับของ {d}"

            replies.append(msg)

        messages = [TextSendMessage(text="\n".join(replies))]

        if follow_up:
            messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

        line_bot_api.reply_message(event.reply_token, messages)

    except Exception:
        traceback.print_exc()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="เกิดข้อผิดพลาดค่ะ 🙏")
        )

# ================== RUN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
