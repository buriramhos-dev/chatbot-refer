from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback
import os
from dotenv import load_dotenv
import re

load_dotenv()
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ================== DISTRICT ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

latest_sheet_data = None
sheet_ready = False

# ================== COLOR ==================
def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return None
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def is_allowed_color(color_hex):
    rgb = hex_to_rgb(color_hex[:7]) if color_hex else None
    if not rgb:
        return False

    r, g, b = rgb
    is_blue = b > 150 and g > 150 and r < 180
    is_yellow = r > 200 and g > 200 and b < 180
    return is_blue or is_yellow

# ================== UPDATE ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready
    data = request.json

    if not data or "full_sheet_data" not in data:
        return "Invalid payload", 400

    latest_sheet_data = data["full_sheet_data"]
    sheet_ready = True
    print("✅ Sheet synced")
    return "OK", 200

# ================== CORE CHECK ==================
def has_round_for_district(district):
    DISTRICT_COL = 11  # K
    PARTNER_COL = 17   # Q
    NOTE_COL = 18      # R

    for row in latest_sheet_data.values():
        if not isinstance(row, list) or len(row) <= DISTRICT_COL:
            continue

        district_text = str(row[DISTRICT_COL].get("value", "")).lower()
        if district.lower() not in district_text:
            continue

        # ✅ ต้องมีสีฟ้าหรือเหลืองอย่างน้อย 1 ช่องในแถว
        if not any(
            is_allowed_color(c.get("color", ""))
            for c in row if isinstance(c, dict)
        ):
            continue

        partner = row[PARTNER_COL].get("value", "") if len(row) > PARTNER_COL else ""
        note = row[NOTE_COL].get("value", "") if len(row) > NOTE_COL else ""

        return {"partner": partner, "note": note}

    return None

# ================== CALLBACK ==================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ================== MESSAGE ==================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not sheet_ready:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⏳ กำลังซิงค์ข้อมูลจากชีทค่ะ")
        )
        return

    text = event.message.text.lower()
    districts = [d for d in BURIRAM_DISTRICTS if d.lower() in text]

    if not districts:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ กรุณาระบุอำเภอในบุรีรัมย์")
        )
        return

    replies = []
    follow = False

    for d in districts:
        result = has_round_for_district(d)
        if result:
            follow = True
            msg = f"มีรับกลับของ {d}"
            if result["partner"]:
                msg += f" ({result['partner']})"
            if result["note"]:
                msg += f" ({result['note']})"
        else:
            msg = f"ไม่มีรับกลับของ {d}"
        replies.append(msg)

    messages = [TextSendMessage(text="\n".join(replies))]
    if follow:
        messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

    line_bot_api.reply_message(event.reply_token, messages)

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
