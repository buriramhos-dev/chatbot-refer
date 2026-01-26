from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback
import os
from dotenv import load_dotenv
import re

# ================== LOAD ENV ==================
load_dotenv()

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN, timeout=15)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ================== CONSTANT ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์", "คูเมือง", "กระสัง", "นางรอง", "หนองกี่",
    "ละหานทราย", "ประโคนชัย", "บ้านกรวด", "พุทไธสง", "ลำปลายมาศ",
    "สตึก", "บ้านด่าน", "ห้วยราช", "โนนสุวรรณ", "ปะคำ",
    "นาโพธิ์", "หนองหงส์", "พลับพลาชัย", "เฉลิมพระเกียรติ", "ชำนิ",
    "บ้านใหม่ไชยพจน์", "โนนดินแดง", "แคนดง", "ลำทะเมนชัย",
    "เมืองยาง", "ชุมพวง"
]

latest_sheet_data = {}

TIME_PATTERN = re.compile(
    r'\b(?:'
    r'([01]?\d|2[0-3])[:.]([0-5]\d)'
    r'|([0-2]?\d)\s*(?:โมง|น\.)\s*(เช้า|บ่าย|เย็น)?'
    r')\b',
    re.IGNORECASE
)

# ================== COLOR CHECK ==================
def is_allowed_color(color_hex):
    """
    ตรวจว่าสีเป็นกลุ่ม ฟ้า / เหลือง หรือไม่
    รองรับสีธีมจาก Google Sheet
    """
    if not color_hex:
        return False

    color_hex = color_hex.lower()[:7]

    # ฟ้า / ฟ้าอ่อน / cyan
    if color_hex.startswith(("#00", "#66", "#7f", "#9e")):
        return True

    # เหลือง
    if color_hex.startswith("#ff"):
        return True

    return False

# ================== UPDATE FROM SHEET ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data
    data = request.json

    if not data:
        return "No JSON", 400

    full_data = data.get("full_sheet_data")
    if full_data:
        latest_sheet_data = full_data
        print("✅ Sheet updated:", len(full_data), "rows")
        return "OK", 200

    return "Invalid payload", 400

# ================== CORE LOGIC ==================
def has_round_for_district(district_name):
    district_name = district_name.lower().strip()

    DISTRICT_COL = 10  # K
    PARTNER_COL = 14   # O
    NOTE_COL = 15      # P

    for row, cells in latest_sheet_data.items():

        if str(row) == "1":
            continue

        if not isinstance(cells, list):
            continue

        if len(cells) <= max(DISTRICT_COL, PARTNER_COL, NOTE_COL):
            continue

        district_cell = cells[DISTRICT_COL] or {}
        partner_cell = cells[PARTNER_COL] or {}
        note_cell = cells[NOTE_COL] or {}

        district_value = str(district_cell.get("value", "")).lower()

        if district_name in district_value:
            partner_text = str(partner_cell.get("value", "")).strip()
            note_text = str(note_cell.get("value", "")).strip()
            color_hex = (partner_cell.get("color", "") or "").lower()[:7]

            print("DEBUG COLOR:", district_name, color_hex)

            if is_allowed_color(color_hex):
                return {
                    "partner": partner_text,
                    "note": note_text
                }

    return None

# ================== LINE CALLBACK ==================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
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

        # เวลา
        if TIME_PATTERN.search(text):
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"ล้อหมุนเวลา {text} นะคะ ขอบคุณค่ะ")
            )
            return

        districts = [d for d in BURIRAM_DISTRICTS if d.lower() in text_lower]

        if not districts:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาระบุชื่อโรงพยาบาลในบุรีรัมย์")
            )
            return

        results = []
        follow_up = False

        for d in districts:
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

        messages = [TextSendMessage(text="\n".join(results))]
        if follow_up:
            messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

        line_bot_api.reply_message(event.reply_token, messages)

    except Exception as e:
        print("❌ MESSAGE ERROR:", e)
        traceback.print_exc()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="เกิดข้อผิดพลาดค่ะ 🙏")
        )

# ================== RUN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
