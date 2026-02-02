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
        sheet_ready = True

    print(f"✅ Sheet synced: {len(latest_sheet_data)} rows")
    return "OK", 200

# ================== SEARCH CORE ==================
def get_district_info(district_name):
    target = district_name.replace(" ", "").strip()
    
    # ดัชนีคอลัมน์ตาม Google Sheets (A=0, K=10, O=14, P=15)
    K_INDEX = 10  # HOSPITAL
    O_INDEX = 14  # พันธมิตร
    P_INDEX = 15  # หมายเหตุ

    with data_lock:
        working_data = latest_sheet_data.copy()

    if not working_data:
        return None

    try:
        # เรียงลำดับแถวเพื่อให้ได้ข้อมูลที่อัปเดตล่าสุดตามลำดับชีท
        sorted_keys = sorted(working_data.keys(), key=lambda x: int(x))
    except:
        sorted_keys = working_data.keys()

    for row_idx in sorted_keys:
        if str(row_idx) == "1": continue  # ข้าม Header
        
        cells = working_data[row_idx]
        if not isinstance(cells, list) or len(cells) <= K_INDEX:
            continue

        # ดึงข้อมูล Cell แบบป้องกัน Error กรณี Array สั้นกว่าที่กำหนด
        h_cell = cells[K_INDEX] if len(cells) > K_INDEX else {}
        o_cell = cells[O_INDEX] if len(cells) > O_INDEX else {}
        p_cell = cells[P_INDEX] if len(cells) > P_INDEX else {}

        # ดึงค่า Value และล้างช่องว่าง
        h_val = str(h_cell.get("value", "") or "").strip()
        o_val = str(o_cell.get("value", "") or "").strip()
        p_val = str(p_cell.get("value", "") or "").strip()

        # 1. เช็คชื่อโรงพยาบาล/อำเภอ
        if target in h_val.replace(" ", ""):
            # 2. เช็คสีในคอลัมน์ K, O หรือ P
            has_valid_color = False
            for cell_data in [h_cell, o_cell, p_cell]:
                if cell_data and is_allowed_color(cell_data.get("color")):
                    has_valid_color = True
                    break
            
            # 3. ถ้าสีตรงเงื่อนไข ส่งข้อมูลกลับไปจัดรูปแบบ
            if has_valid_color:
                return {
                    "hospital": h_val,
                    "partner": o_val,
                    "note": p_val
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
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⏳ กำลังเตรียมข้อมูล..."))
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
            # รูปแบบ: มีรับกลับของ โรงพยาบาล (พันธมิตร) (หมายเหตุ)
            msg = f"มีรับกลับของ {info['hospital']}"
            if info['partner']:
                msg += f" ({info['partner']})"
            if info['note']:
                msg += f" ({info['note']})"
            results_text.append(msg)
        else:
            results_text.append(f"ไม่มีรับกลับของ {d}")

    # รวมทุกรายการส่งกลับในข้อความเดียว
    final_reply = "\n".join(results_text)
    reply_contents = [TextSendMessage(text=final_reply)]
    
    # ถ้ามีรายการที่มีรับกลับ ให้ส่งข้อความถามต่อ
    if found_any:
        reply_contents.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ?"))

    line_bot_api.reply_message(event.reply_token, reply_contents)

# ================== RUN ==================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)