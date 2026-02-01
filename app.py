from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback
import os
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ================== DISTRICT ==================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์","คูเมือง","กระสัง","นางรอง","หนองกี่","ละหานทราย",
    "ประโคนชัย","บ้านกรวด","พุทไธสง","ลำปลายมาศ","สตึก","บ้านด่าน",
    "ห้วยราช","โนนสุวรรณ","ปะคำ","นาโพธิ์","หนองหงส์","พลับพลาชัย",
    "เฉลิมพระเกียรติ","ชำนิ","บ้านใหม่ไชยพจน์","โนนดินแดง","แคนดง",
    "ลำทะเมนชัย","เมืองยาง","ชุมพวง"
]

latest_sheet_data = None
sheet_ready = False

# ================== COLOR ==================
def hex_to_rgb(hex_color):
    if not hex_color:
        return None
    hex_color = str(hex_color).lstrip("#").strip()
    if len(hex_color) != 6:
        return None
    try:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return None

def normalize_color_to_rgb(color_data):
    """แปลงสีจากหลายรูปแบบเป็น RGB tuple"""
    if not color_data:
        return None
    
    # ถ้าเป็น string (hex)
    if isinstance(color_data, str):
        color_str = color_data.strip()
        if color_str.startswith("#"):
            return hex_to_rgb(color_str)
        elif len(color_str) == 6:
            return hex_to_rgb("#" + color_str)
        else:
            return hex_to_rgb(color_str)
    
    # ถ้าเป็น dict ที่มี red, green, blue (0.0-1.0)
    if isinstance(color_data, dict):
        if "red" in color_data and "green" in color_data and "blue" in color_data:
            try:
                r = int(float(color_data["red"]) * 255)
                g = int(float(color_data["green"]) * 255)
                b = int(float(color_data["blue"]) * 255)
                return (r, g, b)
            except (ValueError, TypeError):
                pass
        
        # ถ้ามี hex ใน dict
        if "hex" in color_data:
            return hex_to_rgb(color_data["hex"])
        
        # ถ้ามี color key ใน dict (nested)
        if "color" in color_data:
            return normalize_color_to_rgb(color_data["color"])
    
    return None

def is_allowed_color(color_data):
    """เช็คว่าสีเป็นสีฟ้าหรือสีเหลืองที่อนุญาต
    - สีฟ้า: #00ffff (cyan) = RGB(0, 255, 255) - B และ G สูง, R ต่ำ
    - สีเหลือง: #ffff00 (yellow) = RGB(255, 255, 0) - R และ G สูง, B ต่ำ
    """
    rgb = normalize_color_to_rgb(color_data)
    if not rgb:
        return False

    r, g, b = rgb
    
    # สีฟ้า (Cyan): #00ffff = (0, 255, 255)
    # เงื่อนไข: B และ G สูงมาก (>200), R ต่ำมาก (<50)
    is_blue = b > 200 and g > 200 and r < 50
    
    # สีเหลือง (Yellow): #ffff00 = (255, 255, 0)
    # เงื่อนไข: R และ G สูงมาก (>200), B ต่ำมาก (<50)
    is_yellow = r > 200 and g > 200 and b < 50
    
    return is_blue or is_yellow

# ================== UPDATE ==================
@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data, sheet_ready
    data = request.json

    if not data or "full_sheet_data" not in data:
        return "Invalid payload", 400

    latest_sheet_data = data["full_sheet_data"]
    sheet_ready = True
    print("✅ Sheet synced")
    # Debug: นับจำนวนแถว
    if isinstance(latest_sheet_data, dict):
        print(f"📊 Total rows: {len(latest_sheet_data)}")
    return "OK", 200

# ================== CORE CHECK ==================
def has_round_for_district(district_name):
    district_name = district_name.lower().strip()

    DISTRICT_COL = 10   # K โรงพยาบาล
    PARTNER_COL  = 14   # O พันธมิตร
    NOTE_COL     = 15   # P หมายเหตุ

    if not isinstance(latest_sheet_data, dict):
        return None

    # รวบรวมแถวที่ตรงกับชื่ออำเภอก่อน (เรียงตาม row_idx เพื่อให้ผลลัพธ์สม่ำเสมอ)
    matching_rows = []
    
    # เรียง row_idx เป็นตัวเลขเพื่อให้ผลลัพธ์สม่ำเสมอ
    sorted_rows = sorted(
        latest_sheet_data.items(),
        key=lambda x: int(x[0]) if str(x[0]).isdigit() else 999999
    )
    
    for row_idx, cells in sorted_rows:
        if str(row_idx) == "1":
            continue

        if not isinstance(cells, list):
            continue

        if len(cells) <= NOTE_COL:
            continue

        # โรงพยาบาล
        district_cell = cells[DISTRICT_COL] if isinstance(cells[DISTRICT_COL], dict) else {}
        district_value = str(district_cell.get("value", "")).lower().strip()

        # เปรียบเทียบชื่ออำเภอให้ตรงกันมากขึ้น
        if district_name not in district_value and district_value not in district_name:
            continue

        matching_rows.append((row_idx, cells, district_value))

    # ตรวจสอบสีจากแถวที่ตรงกันทั้งหมด
    for row_idx, cells, district_value in matching_rows:
        # เช็คสีเฉพาะ K Q R
        color_cells = [
            cells[DISTRICT_COL],
            cells[PARTNER_COL],
            cells[NOTE_COL]
        ]

        # ตรวจสอบสีจากแต่ละ cell
        has_valid_color = False
        for c in color_cells:
            if not isinstance(c, dict):
                continue
            
            # ลองหลายรูปแบบของ color
            color_data = (
                c.get("color") or 
                c.get("backgroundColor") or 
                c.get("bgColor") or
                c.get("fill") or
                None
            )
            
            if is_allowed_color(color_data):
                has_valid_color = True
                break
        
        # ถ้าแถวนี้มีสีที่ถูกต้อง ให้ return ทันที
        if has_valid_color:
            partner_cell = cells[PARTNER_COL] if isinstance(cells[PARTNER_COL], dict) else {}
            note_cell = cells[NOTE_COL] if isinstance(cells[NOTE_COL], dict) else {}
            partner_text = str(partner_cell.get("value", "")).strip()
            note_text = str(note_cell.get("value", "")).strip()

            return {
                "hospital": district_value,
                "partner": partner_text,
                "note": note_text
            }

    return None

# ================== CALLBACK ==================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ================== MESSAGE ==================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not sheet_ready:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⏳ กำลังซิงค์ข้อมูลจากชีทค่ะ")
        )
        return

    text = event.message.text.lower()
    districts = [d for d in BURIRAM_DISTRICTS if d.lower() in text]

    if not districts:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ กรุณาระบุโรงพยาบาลในบุรีรัมย์")
        )
        return

    replies = []
    follow = False

    for d in districts:
        result = has_round_for_district(d)
        if result:
            follow = True
            # รูปแบบ: hospital(พันธมิตร ถ้ามี)(หมายเหตุ)
            hospital_text = result["hospital"].strip() if result["hospital"] else ""
            partner_text = result["partner"].strip() if result["partner"] else ""
            note_text = result["note"].strip() if result["note"] else ""
            
            # เริ่มจาก hospital
            msg = hospital_text if hospital_text else f"มีรอบรับกลับ {d}"
            
            # เพิ่มพันธมิตรถ้ามี
            if partner_text:
                msg += f"({partner_text})"
            
            # เพิ่มหมายเหตุถ้ามี
            if note_text:
                msg += f"({note_text})"
        else:
            msg = f"ไม่มีรอบรับกลับ {d}"
        replies.append(msg)

    messages = [TextSendMessage(text="\n".join(replies))]
    if follow:
        messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))

    line_bot_api.reply_message(event.reply_token, messages)

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
