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

# ================== IMPROVED COLOR LOGIC (ครอบคลุมเฉดสีได้มากขึ้น) ==================
def is_allowed_color(color_hex):
    if not color_hex: return False
    c = color_hex.replace("#", "").lower().strip()
    
    # ✅ รายการรหัสสีเหลือง/ฟ้า ที่พบบ่อยใน Google Sheets
    # (หมายเหตุ: สีเขียว 00ff00 ถูกถอดออกตามความต้องการของคุณแล้ว)
    target_shades = [
        "ffff00", "fff2cc", "fce5cd", "fbef24", "f1c232", "ffe599", "fff100", # กลุ่มสีเหลือง
        "00ffff", "c9daf8", "a4c2f4", "cfe2f3", "d0e0e3", "a2c4c9", "00eeee"  # กลุ่มสีฟ้า
    ]
    
    if c in target_shades: return True
    
    # แถม: กรณีสีเหลืองสว่างมากๆ (ตรวจสอบด้วยรหัสสีเบื้องต้น)
    if c.startswith("fff") or (c.startswith("ff") and c.endswith("00")):
        return True
        
    return False

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
    return "OK", 200

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ================== SEARCH CORE (ดึงข้อมูล O และ P) ==================
def get_district_info(district_name):
    target = district_name.replace(" ", "").strip()
    HOSP_COL = 10  # คอลัมน์ K
    PART_COL = 14  # คอลัมน์ O
    NOTE_COL = 15  # คอลัมน์ P

    with data_lock:
        working_data = latest_sheet_data.copy()
    if not working_data: return None

    try:
        # เรียงลำดับแถวตามตัวเลข
        row_keys = sorted(working_data.keys(), key=lambda x: int(x))
    except:
        row_keys = sorted(working_data.keys())

    found_rows = []
    for row_idx in row_keys:
        if str(row_idx) == "1": continue 
        cells = working_data[row_idx]
        
        if not isinstance(cells, list) or len(cells) <= NOTE_COL: continue

        h_cell = cells[HOSP_COL]
        h_val = str(h_cell.get("value", "") or "").strip()
        h_color = h_cell.get("color")

        if target == h_val:
            # ถ้าเจอชื่ออำเภอตรงกัน ให้เก็บไว้ตรวจสอบสี
            if is_allowed_color(h_color):
                partner = str(cells[PART_COL].get("value", "") or "").strip()
                note = str(cells[NOTE_COL].get("value", "") or "").strip()
                
                return {
                    "status": "success", 
                    "data": {"hospital": h_val, "partner": partner, "note": note}
                }
            else:
                found_rows.append(h_val)
    
    if found_rows:
        return {"status": "no_color_match", "hospital": target}
    return None

# ================== MESSAGE HANDLER ==================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not sheet_ready: return
    raw_text = event.message.text.strip()
    matched_district = next((d for d in BURIRAM_DISTRICTS if d in raw_text), None)
    if not matched_district: return

    info = get_district_info(matched_district)
    if info:
        if info["status"] == "success":
            res = info["data"]
            
            # รวมข้อมูลจากคอลัมน์ O (พันธมิตร) และ P (หมายเหตุ)
            display_parts = []
            if res['partner'] and res['partner'].lower() != "none":
                display_parts.append(res['partner'])
            if res['note'] and res['note'].lower() != "none":
                display_parts.append(res['note'])
            
            detail_str = f" ({' '.join(display_parts)})" if display_parts else ""
            reply_text = f"มีรับกลับของ {res['hospital']}{detail_str}"
            
            line_bot_api.reply_message(
                event.reply_token,
                [TextSendMessage(text=reply_text), TextSendMessage(text="ล้อหมุนกี่โมงคะ?")]
            )
        elif info["status"] == "no_color_match":
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"ไม่มีรับกลับของ {info['hospital']}")
            )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)