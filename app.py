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

# ================= CONFIG =================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

DISTRICT_MAP = { "".join(h.split()).lower(): h for h in BURIRAM_DISTRICTS }

latest_rows = []
sheet_ready = False
lock = threading.Lock()

# ================= UTILS =================
def clean(txt):
    return str(txt or "").replace(" ", "").strip().lower()

# ✅ ปรับปรุงการเช็กสีให้ยืดหยุ่นขึ้น (ใช้ startswith เพื่อดักรหัสสีเหลือง/ฟ้าทุกเฉด)
def is_blue_or_yellow(color):
    if not color: return False
    c = str(color).strip().lower()
    
    # เช็กสีเหลือง (กลุ่ม ffff... หรือ fff2...)
    is_yellow = c.startswith("#ffff") or c.startswith("#fff2") or c.startswith("#fce")
    # เช็กสีฟ้า (กลุ่ม 00ffff หรือเฉดใกล้เคียง)
    is_blue = c.startswith("#00ffff") or c.startswith("#c9d") or c.startswith("#a4c") or c.startswith("#cfe")
    
    return is_yellow or is_blue

# ================= API =================
@app.route("/update", methods=["POST"])
def update():
    global latest_rows, sheet_ready
    data = request.json or {}

    with lock:
        # ✅ แก้ไข: ดึงข้อมูลให้ถูกคีย์ (ลองเช็กทั้ง 'rows' และ 'full_sheet_data')
        latest_rows = data.get("rows") or data.get("full_sheet_data") or []
        sheet_ready = True

    print(f"✅ SYNC SUCCESS: {len(latest_rows)} items")
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
def find_hospital(hospital_name):
    target = clean(hospital_name)

    with lock:
        # ตรวจสอบว่า latest_rows เป็น dict หรือ list
        if isinstance(latest_rows, dict):
            rows_to_search = latest_rows.values()
        else:
            rows_to_search = latest_rows

    found_any_row = False

    for row in rows_to_search:
        # ดึงชื่อโรงพยาบาล (เผื่อคีย์อาจเป็น 'hospital' หรือ index)
        h_name = row.get("hospital")
        if clean(h_name) != target:
            continue

        found_any_row = True
        
        # ✅ เช็กสี ถ้าสีผ่านให้รีเทิร์นข้อมูลทันที
        if is_blue_or_yellow(row.get("color")):
            return {
                "hospital": hospital_name,
                "partner": str(row.get("partner") or "").strip(),
                "note": str(row.get("note") or "").strip()
            }

    # ถ้าวนจนจบแล้วเจอชื่อแต่สีไม่ผ่าน
    if found_any_row:
        return "NO_ACCEPT"
    return None

# ================= LINE HANDLER =================
@handler.add(MessageEvent, message=TextMessage)
def handle(event):
    if not sheet_ready:
        return

    text = clean(event.message.text)
    hospital = next((real for key, real in DISTRICT_MAP.items() if key in text), None)

    if not hospital:
        return

    result = find_hospital(hospital)

    if isinstance(result, dict):
        parts = []
        # กรองเอาเฉพาะที่มีข้อความจริงๆ ไม่เอา "None" หรือช่องว่าง
        if result["partner"] and result["partner"].lower() != "none":
            parts.append(result["partner"])
        if result["note"] and result["note"].lower() != "none":
            parts.append(result["note"])

        detail = f" ({' '.join(parts)})" if parts else ""

        line_bot_api.reply_message(
            event.reply_token,
            [
                TextSendMessage(text=f"มีรับกลับของ {hospital}{detail}"),
                TextSendMessage(text="ล้อหมุนกี่โมงคะ?")
            ]
        )
    else:
        # จะเข้าตรงนี้ถ้า result เป็น "NO_ACCEPT" หรือ None
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"ไม่มีรับกลับของ {hospital}")
        )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))