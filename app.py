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

# ================== STRICT COLOR LOGIC (ฉบับแก้ไข: รองรับเฉดสีจากการ Copy) ==================
def is_allowed_color(color_hex):
    if not color_hex: return False
    # ล้างค่ารหัสสีให้เป็นตัวพิมพ์เล็กเพื่อเปรียบเทียบ
    c = color_hex.replace("#", "").lower().strip()
    
    # ✅ กลุ่มสีเหลือง (รวมเหลืองมาตรฐาน และเหลืองจากการ Copy/Paste เฉดต่างๆ)
    yellow_shades = ["ffff00", "fff2cc", "fce5cd", "fbef24", "f1c232", "ffe599", "fff2cc"]
    
    # ✅ กลุ่มสีฟ้า (รวมฟ้ามาตรฐาน และฟ้าจากการ Copy/Paste เฉดต่างๆ)
    blue_shades = ["00ffff", "c9daf8", "a4c2f4", "cfe2f3", "00eeee", "d0e0e3", "00ffff"]

    # ❌ รหัสสีชมพู (f4cccc) และเขียว (00ff00) จะไม่ถูกรวมในนี้ ทำให้บอทข้ามไปอัตโนมัติ
    return (c in yellow_shades) or (c in blue_shades)

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

# ================== SEARCH CORE (แก้ไข: ข้ามสีชมพู/เขียว และค้นหาเฉดเหลือง/ฟ้า) ==================
def get_district_info(district_name):
    target = district_name.replace(" ", "").strip()
    K_INDEX = 10  # HOSPITAL
    O_INDEX = 14  # พันธมิตร
    P_INDEX = 15  # หมายเหตุ

    with data_lock:
        working_data = latest_sheet_data.copy()

    if not working_data:
        return None

    # เรียงลำดับแถวจากบนลงล่าง
    try:
        sorted_keys = sorted(working_data.keys(), key=lambda x: int(x))
    except:
        sorted_keys = sorted(working_data.keys())

    found_any_name = False 

    for row_idx in sorted_keys:
        if str(row_idx) == "1": continue 
        
        cells = working_data[row_idx]
        if not isinstance(cells, list) or len(cells) <= P_INDEX:
            continue

        h_cell = cells[K_INDEX]
        h_val = str(h_cell.get("value", "") or "").strip()
        h_color = h_cell.get("color")

        if target == h_val:
            found_any_name = True
            
            # 🟢 เช็คว่าสีแถวนี้อยู่ในกลุ่ม "เหลือง" หรือ "ฟ้า" ที่เราอนุญาตหรือไม่
            # ❌ ถ้าเป็นสีชมพู/เขียว บอทจะวนลูปข้ามไปดูแถวถัดไปด้านล่างทันที
            if is_allowed_color(h_color):
                partner = str(cells[O_INDEX].get("value", "") or "").strip()
                note = str(cells[P_INDEX].get("value", "") or "").strip()
                
                return {
                    "status": "success", 
                    "data": {
                        "hospital": h_val,
                        "partner": partner,
                        "note": note
                    }
                }
    
    # หากหาจนจบทุุกแถวแล้วเจอแต่ชื่ออำเภอ แต่ไม่มีเฉดสีที่ต้องการเลย
    if found_any_name:
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
            res = info["data"]
            details = []
            if res['partner']: details.append(res['partner'])
            if res['note']: details.append(res['note'])
            
            detail_str = f" ({' '.join(details)})" if details else ""
            reply_text = f"มีรับกลับของ {res['hospital']}{detail_str}"
            
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