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

# ================== STRICT COLOR LOGIC (แก้ไข: ตัดเขียวออกแล้ว) ==================
def is_allowed_color(color_hex):
    if not color_hex: return False
    clean_hex = color_hex.replace("#", "").lower().strip()
    
    # ✅ บอทจะยอมรับและ "หยุดตอบ" เฉพาะ 2 สีนี้เท่านั้น:
    # ffff00 = สีเหลืองมาตรฐาน
    # 00ffff = สีฟ้ามาตรฐาน
    # (รหัสสีเขียว 00ff00 และชมพู f4cccc จะถูกข้ามไปโดยอัตโนมัติ)
    allowed_strictly = ["ffff00", "00ffff"]
    
    return clean_hex in allowed_strictly

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

# ================== SEARCH CORE (แก้ไข: สแกนหาจนเจอสีเป้าหมายตัวแรกจากบนลงล่าง) ==================
def get_district_info(district_name):
    target = district_name.replace(" ", "").strip()
    K_INDEX = 10  # HOSPITAL
    O_INDEX = 14  # พันธมิตร
    P_INDEX = 15  # หมายเหตุ

    with data_lock:
        working_data = latest_sheet_data.copy()

    if not working_data:
        return None

    # เรียงลำดับแถวจาก 1 ไปถึงแถวสุดท้าย เพื่อให้สแกนจากบนลงล่าง
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
            # DEBUG ดูว่าบอทกำลังมองแถวไหนอยู่
            print(f"DEBUG: ตรวจสอบ '{h_val}' แถว {row_idx} สีคือ '{h_color}'")
            
            # ✅ ถ้าเป็นสีชมพู หรือสีเขียว บอทจะ "ไม่เข้า" เงื่อนไขนี้ 
            # และจะวน Loop ไปเช็คแถวถัดไปด้านล่างทันที
            if is_allowed_color(h_color):
                print(f"DEBUG: ✅ เจอสีเหลือง/ฟ้าแล้ว! ที่แถว {row_idx}")
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
    
    # ถ้าวนจนจบลูปแล้ว เจอชื่อแต่ไม่มีสีเหลืองหรือฟ้าเลย
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