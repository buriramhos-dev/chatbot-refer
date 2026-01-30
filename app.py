from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback, os, re
from dotenv import load_dotenv

# ================== LOAD ENV ==================
load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"), timeout=15)
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# ================== CONSTANT ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

latest_sheet_data = {}
sheet_ready = False

# ================== TIME ==================
TIME_PATTERN = re.compile(r'([01]?\d|2[0-3])[:.]([0-5]\d)|(\d+)\s*โมง')

# ================== COLOR ==================
def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0,2,4)) if len(h)==6 else None

def is_allowed_color(color):
    if not color: return False
    rgb = hex_to_rgb(color[:7].lower())
    if not rgb: return False
    r,g,b = rgb
    return (b>150 and g>150 and r<180) or (r>200 and g>200 and b<180)

# ================== UPDATE ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready
    data = request.json
    if not data: return "No JSON", 400

    full = data.get("full_sheet_data")
    if isinstance(full, dict):
        latest_sheet_data = full
        sheet_ready = True
        print("✅ Sheet updated", len(full))
        return "OK", 200

    return "Invalid payload", 400

# ================== CORE ==================
def has_round_for_district(name):
    name = name.lower()

    DISTRICT_COL = 10   # k
    PARTNER_COL  = 16   # Q
    NOTE_COL     = 17   # R

    for row, cells in latest_sheet_data.items():
        if str(row) == "1": continue
        if len(cells) <= DISTRICT_COL: continue

        district = str(cells[DISTRICT_COL].get("value","")).lower()
        if name not in district: continue

        if not any(is_allowed_color(c.get("color","")) for c in cells):
            continue

        return {
            "partner": str(cells[PARTNER_COL].get("value","")).strip(),
            "note": str(cells[NOTE_COL].get("value","")).strip()
        }

    return None

# ================== LINE ==================
@app.route("/callback", methods=["POST"])
def callback():
    try:
        handler.handle(
            request.get_data(as_text=True),
            request.headers.get("X-Line-Signature")
        )
    except InvalidSignatureError:
        abort(400)
    except Exception:
        traceback.print_exc()
        abort(500)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not sheet_ready:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⏳ ระบบกำลังซิงค์ข้อมูล กรุณาลองใหม่ค่ะ")
        )
        return

    text = event.message.text.lower()

    if TIME_PATTERN.search(text):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ล้อหมุนเวลา {event.message.text} นะคะ")
        )
        return

    districts = [d for d in BURIRAM_DISTRICTS if d.lower() in text]
    if not districts:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ กรุณาระบุชื่อโรงพยาบาลในบุรีรัมย์")
        )
        return

    msgs = []
    follow = False
    for d in districts:
        r = has_round_for_district(d)
        if r:
            follow = True
            m = f"มีรับกลับของ {d}"
            if r["partner"]: m += f" ({r['partner']})"
            if r["note"]: m += f" ({r['note']})"
            msgs.append(m)
        else:
            msgs.append(f"ไม่มีรับกลับของ {d}")

    out = [TextSendMessage(text="\n".join(msgs))]
    if follow:
        out.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

    line_bot_api.reply_message(event.reply_token, out)

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
