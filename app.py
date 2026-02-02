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

# ================== COLOR LOGIC (เน้นฟ้าและเหลือง) ==================
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
    # 🔵 สีฟ้า (ครอบคลุมฟ้าอ่อน/เข้ม)
    is_blue = (b >= 150 and g >= 100)
    # 🟡 สีเหลือง (ครอบคลุมเหลืองอ่อน/เข้ม)
    is_yellow = (r >= 180 and g >= 150 and b <= 150)
    
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

# ================== SEARCH CORE (ปรับปรุงการดึงข้อมูล) ==================
def get_district_info(district_name):
    target = district_name.replace(" ", "").strip()
    
    # ดัชนีคอลัมน์อ้างอิง: J=9(WARD), K=10(HOSPITAL), O=14(พันธมิตร), P=15(หมายเหตุ)
    K_INDEX = 10  
    O_INDEX = 14  
    P_INDEX = 15  

    with data_lock:
        working_data = latest_sheet_data.copy()

    if not working_data:
        return None

    # แปลงคีย์เป็นตัวเลขเพื่อเรียงลำดับแถวจากบนลงล่าง
    try:
        sorted_keys = sorted(working_data.keys(), key=lambda x: int(x))
    except:
        sorted_keys = working_data.keys()

    for row_idx in sorted_keys:
        if str(row_idx) == "1": continue 
        
        cells = working_data[row_idx]
        if not isinstance(cells, list) or len(cells) <= K_INDEX:
            continue

        h_cell = cells[K_INDEX]
        h_val = str(h_cell.get("value", "") or "").strip()

        # 1. เช็คว่าชื่ออำเภอตรงกับคอลัมน์ HOSPITAL หรือไม่
        if target in h_val.replace(" ", ""):
            
            # 2. เช็คสี: แถวนั้นต้องมีสีฟ้าหรือเหลือง (เช็คจากช่อง Hospital เป็นหลัก)
            if is_allowed_color(h_cell.get("color")):
                
                # 3. ดึงข้อมูล พันธมิตร (O) และ หมายเหตุ (P)
                o_val = str(cells[O_INDEX].get("value", "") if len(cells) > O_INDEX else "").strip()
                p_val = str(cells[P_INDEX].get("value", "") if len(cells) > P_INDEX else "").strip()

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
            # ตอบข้อมูล: มีรับกลับของ โรงพยาบาล (พันธมิตร) (หมายเหตุ)
            msg = f"มีรับกลับของ {info['hospital']}"
            if info['partner']:
                msg += f" ({info['partner']})"
            if info['note']:
                msg += f" ({info['note']})"
            results_text.append(msg)

    if results_text:
        final_reply = "\n".join(results_text)
        reply_contents = [TextSendMessage(text=final_reply)]
        
        if found_any:
            reply_contents.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ?"))

        line_bot_api.reply_message(event.reply_token, reply_contents)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)