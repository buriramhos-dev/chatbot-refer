from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from dotenv import load_dotenv
import threading

load_dotenv()
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ================== DISTRICT CONFIG ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

latest_sheet_data = {}
sheet_ready = False
data_lock = threading.Lock()

# ================== COLOR LOGIC ==================
def hex_to_rgb(hex_color):
    try:
        if not hex_color: return None
        hex_color = hex_color.replace("#", "").strip()
        if len(hex_color) != 6: return None
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except:
        return None

def is_allowed_color(color_hex):
    if not color_hex: return False
    rgb = hex_to_rgb(color_hex)
    if not rgb: return False

    r, g, b = rgb
    # 🔵 ฟ้า/ฟ้าเขียว (Blue-ish)
    is_blue = (b >= 180 and g >= 150)
    # 🟡 เหลือง (Yellow-ish)
    is_yellow = (r >= 200 and g >= 180 and b <= 160)
    
    return is_blue or is_yellow

# ================== API ENDPOINT ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready
    data = request.json
    if not data or "full_sheet_data" not in data:
        return "Invalid payload", 400

    with data_lock:
        latest_sheet_data = data["full_sheet_data"]
        # กรองข้อมูลเบื้องต้นเพื่อให้จัดการง่ายขึ้น
        sheet_ready = True

    print(f"✅ Sheet synced: {len(latest_sheet_data)} rows")
    return "OK", 200

# ================== SEARCH CORE ==================
def get_district_info(district_name):
    target = district_name.replace(" ", "").strip()
    
    K_COL = 10  # Hospital
    O_COL = 14  # Partner
    P_COL = 15  # Note

    with data_lock:
        working_data = latest_sheet_data.copy()

    if not working_data:
        return None

    try:
        sorted_rows = sorted(working_data.keys(), key=lambda x: int(x))
    except:
        sorted_rows = working_data.keys()

    for row_idx in sorted_rows:
        if str(row_idx) == "1": continue
        
        cells = working_data[row_idx]
        if not isinstance(cells, list) or len(cells) <= K_COL:
            continue

        hospital_cell = cells[K_COL] or {}
        hospital_val = str(hospital_cell.get("value", "")).strip()
        hospital_clean = hospital_val.replace(" ", "")

        if target in hospital_clean:
            has_color = False
            for col_idx in [K_COL, O_COL, P_COL]:
                if len(cells) > col_idx:
                    cell_info = cells[col_idx] or {}
                    color = (cell_info.get("color") or "").strip()
                    if is_allowed_color(color):
                        has_color = True
                        break
            
            if has_color:
                return {
                    "hospital": hospital_val,
                    "partner": str((cells[O_COL] or {}).get("value", "")).strip() if len(cells) > O_COL else "",
                    "note": str((cells[P_COL] or {}).get("value", "")).strip() if len(cells) > P_COL else ""
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
    return "OK"

# ================== MESSAGE HANDLER ==================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not sheet_ready:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⏳ กำลังโหลดข้อมูล... กรุณารอสักครู่ค่ะ"))
        return

    raw_text = event.message.text
    clean_user_text = raw_text.replace(" ", "")
    matched_districts = [d for d in BURIRAM_DISTRICTS if d.replace(" ", "") in clean_user_text]

    if not matched_districts:
        return

    results_text = []
    found_any = False

    for d in matched_districts:
        info = get_district_info(d)
        if info:
            found_any = True
            # --- รูปแบบข้อความ: มีรับกลับของ โรงพยาบาล (พันธมิตร) (หมายเหตุ) ---
            msg = f"มีรับกลับของ {info['hospital']}"
            if info['partner']:
                msg += f" ({info['partner']})"
            if info['note']:
                msg += f" ({info['note']})"
            results_text.append(msg)
        else:
            results_text.append(f"ไม่มีรับกลับของ {d}")

    # รวมทุกคำตอบเข้าด้วยกัน
    final_text = "\n".join(results_text)
    reply_messages = [TextSendMessage(text=final_text)]
    
    # ถ้ามีอย่างน้อย 1 ที่มีรับกลับ ให้ส่งคำถามปิดท้าย
    if found_any:
        reply_messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ?"))

    line_bot_api.reply_message(event.reply_token, reply_messages)

# ================== RUN ==================
if __name__ == "__main__":
    # ใช้ค่า Port 5000 เป็นค่าเริ่มต้นสำหรับ Local และดึงจาก Environment สำหรับ Server
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)