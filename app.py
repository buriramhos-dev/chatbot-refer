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

# สีที่ถือว่า "มีรับกลับ" (จากโค้ดแรก)
allowed_return_trip_colors = ["#00ffff", "#ffff00"]

latest_sheet_data = {}

# ================== REGEX เวลา ==================
TIME_PATTERN = re.compile(
    r'\b(?:'
    r'([01]?\d|2[0-3])[:.]([0-5]\d)'
    r'|([0-2]?\d)\s*(?:โมง|น\.)\s*(เช้า|บ่าย|เย็น)?'
    r')\b',
    re.IGNORECASE
)

# ================== RECEIVE SHEET UPDATE ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data
    data = request.json

    if not data:
        return "No JSON data", 400

    if "full_sheet_data" in data:
        latest_sheet_data = data["full_sheet_data"]

    elif "row" in data and "row_cells" in data:
        latest_sheet_data[str(data["row"])] = data["row_cells"]

    else:
        return "Invalid data format", 400

    return "OK", 200

# ================== CORE LOGIC ==================
def has_round_for_district(district_name: str):
    district_lower = district_name.lower().strip()

    for row_number, cells in latest_sheet_data.items():

        if row_number == "1":
            continue

        if not isinstance(cells, dict):
            continue

        # 👉 ใช้ชื่อคอลัมน์
        hospital_cell = cells.get("HOSPITAL", {})
        partner_cell = cells.get("พันธมิตร", {})
        note_cell = cells.get("หมายเหตุ", {})

        hospital_value = str(hospital_cell.get("value", "")).lower().strip()
        partner_text = str(partner_cell.get("value", "")).strip()
        note_text = str(note_cell.get("value", "")).strip()

        # 👉 สีดูจากคอลัมน์ "พันธมิตร"
        partner_color = (partner_cell.get("color", "") or "").lower()[:7]

        if district_lower in hospital_value:
            if partner_color in allowed_return_trip_colors:
                return {
                    "partner": partner_text,
                    "note": note_text,
                    "color": partner_color
                }

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
    except Exception as e:
        print("❌ CALLBACK ERROR:", e)
        traceback.print_exc()
        abort(500)

    return "OK"

# ================== LINE MESSAGE ==================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        text = event.message.text.strip()
        text_lower = text.lower()

        # ตรวจเวลา
        if TIME_PATTERN.search(text):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"ล้อหมุนเวลา {text} นะคะ ขอบคุณค่ะ")
            )
            return

        found_districts = [
            d for d in BURIRAM_DISTRICTS
            if d.lower() in text_lower
        ]

        if not found_districts:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาระบุชื่อโรงพยาบาลในบุรีรัมย์ค่ะ")
            )
            return

        results = []
        follow_up = False

        for d in found_districts:
            result = has_round_for_district(d)

            if result:
                follow_up = True
                msg = f"มีรับกลับของ {d}"

                if result["partner"]:
                    msg += f" ({result['partner']})"

                if result["note"]:
                    msg += f" ({result['note']})"

                results.append(msg)
            else:
                results.append(f"ไม่มีรับกลับของ {d}")

        reply_msgs = [TextSendMessage(text="\n".join(results))]

        if follow_up:
            reply_msgs.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

        line_bot_api.reply_message(event.reply_token, reply_msgs)

    except Exception as e:
        print("❌ MESSAGE ERROR:", e)
        traceback.print_exc()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="เกิดข้อผิดพลาดในการประมวลผลค่ะ 🙏")
        )

# ================== RUN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
