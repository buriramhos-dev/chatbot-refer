from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback
import os
from dotenv import load_dotenv
import re

# โหลดค่า environment variables จากไฟล์ .env
load_dotenv()

app = Flask(__name__)

# ดึงค่า token และ secret จาก environment
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN, timeout=15)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์", "คูเมือง", "กระสัง", "นางรอง", "หนองกี่",
    "ละหานทราย", "ประโคนชัย", "บ้านกรวด", "พุทไธสง", "ลำปลายมาศ",
    "สตึก", "จักราช", "ห้วยราช", "โนนสุวรรณ", "ปะคำ",
    "นาโพธิ์", "หนองหงส์", "พลับพลาชัย", "เฉลิมพระเกียรติ", "ชำนิ",
    "บ้านใหม่ไชยพจน์", "โนนดินแดง", "แคนดง", "ลำทะเมนชัย", "เมืองยาง"
]

allowed_return_trip_colors = ["#00ffff", "#ffff00"]
latest_sheet_data = {}

# Regex สำหรับตรวจเวลาครอบคลุมหลายรูปแบบ
TIME_PATTERN = re.compile(
    r'\b(?:'
    r'([01]?\d|2[0-3])[:.]([0-5]\d)'
    r'|([0-2]?\d)\s*(?:โมง|น\.)\s*(เช้า|บ่าย|เย็น)?'
    r')\b',
    re.IGNORECASE
)

@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data
    data = request.json
    if not data:
        return "No JSON data received", 400

    full_data = data.get("full_sheet_data")
    if full_data:
        latest_sheet_data = full_data
    else:
        row = data.get("row")
        row_cells = data.get("row_cells", [])
        if row is not None:
            latest_sheet_data[str(row)] = row_cells
        else:
            return "Data format error", 400

    return "OK", 200

def has_round_for_district(district_name):
    district_name_lower = district_name.lower().strip()
    DISTRICT_COLUMN_INDEX = 10  # คอลัมน์ K
    PARTNER_COLUMN_INDEX = 14   # คอลัมน์ O
    NOTE_COLUMN_INDEX = 15      # คอลัมน์ P

    for row_number, cells in latest_sheet_data.items():
        if row_number == '1':
            continue
        if len(cells) <= max(DISTRICT_COLUMN_INDEX, PARTNER_COLUMN_INDEX, NOTE_COLUMN_INDEX):
            continue

        district_cell = cells[DISTRICT_COLUMN_INDEX]
        district_value = str(district_cell.get("value", "")).lower().strip()

        if district_name_lower in district_value:
            partner_cell = cells[PARTNER_COLUMN_INDEX]
            partner_text = str(partner_cell.get("value", "")).strip()
            color_hex_rgb = str(partner_cell.get("color", "")).lower()[:7]

            note_cell = cells[NOTE_COLUMN_INDEX]
            note_value = str(note_cell.get("value", "")).strip()

            if color_hex_rgb in allowed_return_trip_colors:
                return {
                    "status": color_hex_rgb,
                    "note": note_value,
                    "partner": partner_text
                }

    return None

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        print(f"❌ ERROR in callback: {e}")
        traceback.print_exc()
        abort(500)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        if event.source.type not in ["user", "group", "room"]:
            return

        text = event.message.text.strip()
        text_lower = text.lower()
        found_districts = [d for d in BURIRAM_DISTRICTS if d.lower() in text_lower]

        time_match = TIME_PATTERN.search(text)
        if time_match:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"ล้อหมุนเวลา {text.strip()} นะคะ ขอบคุณค่ะ")
            )
            return

        if not found_districts:
            reply = "❌ กรุณาระบุชื่อโรงพยาบาลในบุรีรัมย์ เช่น 'นางรองมีรับกลับไหม'"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

        results = []
        follow_up = False
        for d in found_districts:
            check_result = has_round_for_district(d)
            if check_result:
                follow_up = True
                partner_text = check_result["partner"].strip()
                note_text = check_result["note"].strip()
                msg_parts = [f"มีรับกลับของ {d}"]

                if partner_text:
                    msg_parts.append(f"({partner_text})")
                if note_text:
                    msg_parts.append(f"({note_text})")

                results.append(" ".join(msg_parts))
            else:
                results.append(f"ไม่มีรับกลับของ {d}")

        reply_messages = [TextSendMessage(text="\n".join(results))]
        if follow_up:
            reply_messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

        line_bot_api.reply_message(event.reply_token, reply_messages)

    except Exception as e:
        print("❌ ERROR in handle_message:", e)
        traceback.print_exc()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="เกิดข้อผิดพลาดในการประมวลผลค่ะ 🙏")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
