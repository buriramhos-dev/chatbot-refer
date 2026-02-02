from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from dotenv import load_dotenv
import threading

load_dotenv()
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

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

# ================== COLOR LOGIC (เฉพาะฟ้าและเหลือง) ==================
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
    # 🔵 สีฟ้า และ 🟡 สีเหลือง (ตัดสีชมพูและเขียวออก)
    is_blue = (b >= 180 and g >= 150)
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

    print(f"✅ ข้อมูลซิงค์สำเร็จ: {len(latest_sheet_data)} แถว")
    return "OK", 200

# ================== SEARCH CORE (ดึงข้อมูล O และ P) ==================
def get_district_info(district_name):
    target = district_name.replace(" ", "").strip()
    
    # อ้างอิง Index จากตาราง: K=10, O=14, P=15
    K_INDEX = 10  # HOSPITAL
    O_INDEX = 14  # พันธมิตร
    P_INDEX = 15  # หมายเหตุ

    with data_lock:
        working_data = latest_sheet_data.copy()

    if not working_data:
        return None

    # เรียงลำดับแถวเพื่อให้ได้ข้อมูลที่ถูกต้อง
    try:
        sorted_keys = sorted(working_data.keys(), key=lambda x: int(x))
    except:
        sorted_keys = working_data.keys()

    for row_idx in sorted_keys:
        if str(row_idx) == "1": continue 
        
        cells = working_data[row_idx]
        if not isinstance(cells, list) or len(cells) <= P_INDEX:
            continue

        h_cell = cells[K_INDEX]
        h_val = str(h_cell.get("value", "") or "").strip()

        # ตรวจสอบชื่ออำเภอแบบตรงตัว และต้องเป็นสีฟ้า/เหลืองเท่านั้น
        if target == h_val and is_allowed_color(h_cell.get("color")):
            
            # ดึงข้อมูล พันธมิตร (O) และ หมายเหตุ (P)
            partner = str(cells[O_INDEX].get("value", "") or "").strip()
            note = str(cells[P_INDEX].get("value", "") or "").strip()

            return {
                "hospital": h_val,
                "partner": partner,
                "note": note
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
        return

    raw_text = event.message.text.strip()
    # ค้นหาอำเภอที่ตรงกับข้อความที่พิมพ์มา
    matched_district = next((d for d in BURIRAM_DISTRICTS if d in raw_text), None)

    if not matched_district:
        return

    info = get_district_info(matched_district)
    
    if info:
        # รวมข้อมูล พันธมิตร และ หมายเหตุ เข้าด้วยกัน
        details = []
        if info['partner']: details.append(info['partner'])
        if info['note']: details.append(info['note'])
        
        detail_str = f" ({' '.join(details)})" if details else ""
        
        reply_text = f"มีรับกลับของ {info['hospital']}{detail_str}"
        
        line_bot_api.reply_message(
            event.reply_token,
            [TextSendMessage(text=reply_text), 
             TextSendMessage(text="ล้อหมุนกี่โมงคะ?")]
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)