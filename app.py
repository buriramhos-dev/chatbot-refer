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

def is_allowed_color(color_hex):
    if not color_hex:
        return False

    rgb = hex_to_rgb(color_hex[:7])
    if not rgb:
        return False

    r, g, b = rgb

    # 🔵 ฟ้า / ฟ้าเขียว
    is_blue = (
        (b >= 200 and g >= 200 and r <= 120) or
        (b >= 200 and g <= 200 and r <= 150)
    )

    # 🟡 เหลือง
    is_yellow = (r >= 200 and g >= 200 and b <= 150)

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
def has_round_for_district(district_name):
    district_name = district_name.lower().strip()

    # คอลัมน์จริงจากชีท
    K_COL = 10  # HOSPITAL
    O_COL = 14  # พันธมิตร
    P_COL = 15  # หมายเหตุ

    if not isinstance(latest_sheet_data, dict):
        return None

    for row_idx, cells in latest_sheet_data.items():

        if str(row_idx) == "1":
            continue

        if not isinstance(cells, list) or len(cells) <= K_COL:
            continue

        # ===== HOSPITAL =====
        hospital_cell = cells[K_COL] or {}
        hospital_text = str(hospital_cell.get("value", "")).strip()
        hospital_lower = hospital_text.lower()

        if district_name not in hospital_lower:
            continue

        # ===== เช็คสี K / O / P =====
        color_cells = []
        for col in (K_COL, O_COL, P_COL):
            if len(cells) > col and isinstance(cells[col], dict):
                color_cells.append(cells[col])

        if not any(
            is_allowed_color((c.get("color") or "").lower())
            for c in color_cells
        ):
            continue

        # ===== ดึงข้อความ =====
        partner_text = ""
        note_text = ""

        if len(cells) > O_COL:
            partner_text = str((cells[O_COL] or {}).get("value", "")).strip()

        if len(cells) > P_COL:
            note_text = str((cells[P_COL] or {}).get("value", "")).strip()

        return {
            "hospital": hospital_text,
            "partner": partner_text,
            "note": note_text
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
            msg = f"มีรับกลับของ {result['hospital']}"
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
