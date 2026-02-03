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

# ================== COLOR LOGIC (แก้ไขตามค่าจริงจาก Log ของคุณ) ==================
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
    clean_hex = color_hex.replace("#", "").lower().strip()
    
    # 1. รายการสีที่ยอมรับ (อ้างอิงจาก Log ที่คุณส่งมา)
    # เราเพิ่ม '00ff00' เพราะใน Log ยืนยันว่าแถวที่มีข้อมูลคือสีนี้
    allowed_list = [
        "00ff00",  # ✅ สีเขียว/ฟ้า ที่พบในแถว 117, 171, 188 (หนองกี่)
        "ffff00",  # สีเหลืองมาตรฐาน
        "00ffff",  # สีฟ้ามาตรฐาน
        "00ecec",  # สีฟ้า Cyan อีกโทน
        "cyan", "yellow"
    ]
    
    if clean_hex in allowed_list:
        return True

    rgb = hex_to_rgb(clean_hex)
    if not rgb: return False
    r, g, b = rgb

    # 2. Logic สำรอง: ตรวจสอบโทนสีสว่าง (เน้น Green สูงสำหรับสีในชีทคุณ)
    is_yellow = (r > 180 and g > 180 and b < 150)
    is_cyan_blue = (g > 180 and b > 180 and r < 180)
    is_bright_green = (g > 200 and r < 100 and b < 100) # สำหรับ #00ff00

    return is_yellow or is_cyan_blue or is_bright_green

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

# ================== SEARCH CORE ==================
def get_district_info(district_name):
    target = district_name.replace(" ", "").strip()
    
    K_INDEX = 10  # HOSPITAL
    O_INDEX = 14  # พันธมิตร
    P_INDEX = 15  # หมายเหตุ

    with data_lock:
        working_data = latest_sheet_data.copy()

    if not working_data:
        return None

    try:
        sorted_keys = sorted(working_data.keys(), key=lambda x: int(x))
    except:
        sorted_keys = working_data.keys()

    found_name_match = False

    for row_idx in sorted_keys:
        if str(row_idx) == "1": continue 
        
        cells = working_data[row_idx]
        if not isinstance(cells, list) or len(cells) <= P_INDEX:
            continue

        h_cell = cells[K_INDEX]
        h_val = str(h_cell.get("value", "") or "").strip()
        h_color = h_cell.get("color")

        if target == h_val:
            found_name_match = True 
            
            # ดูค่าสีจริงใน Console เพื่อปรับแต่งภายหลัง
            print(f"DEBUG: เจอ '{h_val}' ที่แถว {row_idx} ค่าสีคือ '{h_color}'")
            
            if is_allowed_color(h_color):
                partner = str(cells[O_INDEX].get("value", "") or "").strip()
                note = str(cells[P_INDEX].get("value", "") or "").strip()

                return {
                    "status": "success",
                    "hospital": h_val,
                    "partner": partner,
                    "note": note
                }
    
    if found_name_match:
        return {"status": "no_color_match", "hospital": target}
    
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
    matched_district = next((d for d in BURIRAM_DISTRICTS if d in raw_text), None)

    if not matched_district:
        return

    info = get_district_info(matched_district)
    
    if info:
        if info["status"] == "success":
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
        elif info["status"] == "no_color_match":
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"ไม่มีรับกลับของ {info['hospital']}")
            )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)