from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from dotenv import load_dotenv

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

def is_allowed_color(color):
    if not color:
        return False

    color = color.lower().strip()

    # ----- hex -----
    if color.startswith("#"):
        color = color[:7]

        if color in ["#00ffff", "#ffff00"]:
            return True

        rgb = hex_to_rgb(color)
        if not rgb:
            return False

        r, g, b = rgb
        return (
            (b > 150 and g > 150 and r < 150) or   # ฟ้า
            (r > 200 and g > 200 and b < 150)     # เหลือง
        )

    # ----- rgb() -----
    if color.startswith("rgb"):
        nums = [int(n) for n in color if n.isdigit()]
        if len(nums) >= 3:
            r, g, b = nums[:3]
            return (
                (b > 150 and g > 150 and r < 150) or
                (r > 200 and g > 200 and b < 150)
            )

    return False

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
def has_round_for_district(district_name):
    district_name = district_name.lower().strip()

    DISTRICT_COL = 10   # K โรงพยาบาล
    PARTNER_COL  = 16   # Q พันธมิตร
    NOTE_COL     = 17   # R หมายเหตุ

    if not isinstance(latest_sheet_data, dict):
        return None

    for row_idx, cells in latest_sheet_data.items():

        if str(row_idx) == "1":  # skip header
            continue

        if not isinstance(cells, list) or len(cells) <= NOTE_COL:
            continue

        hospital_cell = cells[DISTRICT_COL] or {}
        hospital_name = str(hospital_cell.get("value", "")).strip()
        hospital_lower = hospital_name.lower()

        if district_name not in hospital_lower:
            continue

        # เช็คสีเฉพาะ K Q R
        check_cells = [
            cells[DISTRICT_COL],
            cells[PARTNER_COL],
            cells[NOTE_COL]
        ]

        if not any(
            is_allowed_color((c.get("color") or ""))
            for c in check_cells if isinstance(c, dict)
        ):
            continue

        partner = str((cells[PARTNER_COL] or {}).get("value", "")).strip()
        note = str((cells[NOTE_COL] or {}).get("value", "")).strip()

        return {
            "hospital": hospital_name,
            "partner": partner,
            "note": note
        }

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
            TextSendMessage(text="❌ กรุณาระบุโรงพยาบาลในบุรีรัมย์")
        )
        return

    replies = []
    follow = False

    for d in districts:
        result = has_round_for_district(d)
        if result:
            follow = True
            msg = f"มีรอบรับกลับ {result['hospital']}"
            if result["partner"]:
                msg += f" ({result['partner']})"
            if result["note"]:
                msg += f" ({result['note']})"
        else:
            msg = f"ไม่มีรอบรับกลับ {d}"

        replies.append(msg)

    messages = [TextSendMessage(text="\n".join(replies))]
    if follow:
        messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

    line_bot_api.reply_message(event.reply_token, messages)

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
