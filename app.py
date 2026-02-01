from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback
import os
from dotenv import load_dotenv
import requests
import threading

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
        color_str = color_data.strip().upper()
        
        # กรอง empty string
        if not color_str:
            return None
        
        # ลบ whitespace และตรวจสอบรูปแบบ
        if color_str.startswith("#"):
            return hex_to_rgb(color_str)
        elif len(color_str) == 6:
            # ตรวจสอบว่าเป็น hex ที่ถูกต้อง
            if all(c in "0123456789ABCDEF" for c in color_str):
                return hex_to_rgb("#" + color_str)
        elif len(color_str) == 7 and color_str[0] != "#":
            # อาจมีรูปแบบอื่น
            if all(c in "0123456789ABCDEF" for c in color_str[:6]):
                return hex_to_rgb("#" + color_str[:6])
        
        # ลองแปลงโดยตรง
        return hex_to_rgb(color_str)
    
    # ถ้าเป็น dict ที่มี red, green, blue (0.0-1.0 หรือ 0-255)
    if isinstance(color_data, dict):
        # ลองหา color key ที่มี nested dict (colorFormat API)
        if "color" in color_data and isinstance(color_data["color"], dict):
            return normalize_color_to_rgb(color_data["color"])
        
        # ลองหา rgbColor
        if "rgbColor" in color_data:
            try:
                rgb = color_data["rgbColor"]
                if isinstance(rgb, dict):
                    r = int(float(rgb.get("red", 0)) * 255) if float(rgb.get("red", 0)) <= 1 else int(float(rgb.get("red", 0)))
                    g = int(float(rgb.get("green", 0)) * 255) if float(rgb.get("green", 0)) <= 1 else int(float(rgb.get("green", 0)))
                    b = int(float(rgb.get("blue", 0)) * 255) if float(rgb.get("blue", 0)) <= 1 else int(float(rgb.get("blue", 0)))
                    return (r, g, b)
            except (ValueError, TypeError, AttributeError):
                pass
        
        # ลองหา red, green, blue (0.0-1.0)
        if "red" in color_data and "green" in color_data and "blue" in color_data:
            try:
                red_val = float(color_data["red"])
                green_val = float(color_data["green"])
                blue_val = float(color_data["blue"])
                
                # ถ้าค่าอยู่ระหว่าง 0-1 ให้คูณ 255
                if red_val <= 1 and green_val <= 1 and blue_val <= 1:
                    r = int(red_val * 255)
                    g = int(green_val * 255)
                    b = int(blue_val * 255)
                else:
                    r = int(red_val)
                    g = int(green_val)
                    b = int(blue_val)
                return (r, g, b)
            except (ValueError, TypeError):
                pass
        
        # ถ้ามี hex ใน dict
        if "hex" in color_data:
            return hex_to_rgb(color_data["hex"])
    
    return None

def is_allowed_color(color_data):
    """เช็คว่าสีเป็นสีฟ้าหรือสีเหลืองที่อนุญาต
    - สีฟ้า: #00ffff (cyan) = RGB(0, 255, 255) - B และ G สูง, R ต่ำ
    - สีเหลือง: #ffff00 (yellow) = RGB(255, 255, 0) - R และ G สูง, B ต่ำ
    """
    if not color_data:
        return False
    
    # กรอง empty string
    if isinstance(color_data, str) and not color_data.strip():
        return False
    
    rgb = normalize_color_to_rgb(color_data)
    if not rgb:
        return False

    r, g, b = rgb
    
    # Debug: แสดง RGB เพื่อตรวจสอบ
    print(f"   🎨 Checking RGB({r}, {g}, {b}) | type: {type(r)}, {type(g)}, {type(b)}")
    
    # สีฟ้า (Cyan): ต้องมี B หรือ G สูงกว่า R อย่างชัดเจน
    # หลวมมาก: max(b,g) > min(r,g,b) แล้ว ถือว่าเป็นสีฟ้า
    is_blue = (max(b, g) > r + 50) or (b >= 80 or g >= 80) and (b > r or g > r)
    
    # สีเหลือง (Yellow): ต้องมี R และ G สูงกว่า B อย่างชัดเจน
    is_yellow = (max(r, g) > b + 50) or (r >= 80 or g >= 80) and (r > b or g > b)
    
    # Debug: แสดง RGB และผลการตรวจสอบ
    print(f"   ✓ RGB({r}, {g}, {b}) | Blue: {is_blue} | Yellow: {is_yellow}")
    
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
        # Debug: แสดงตัวอย่าง cell structure จากแถวแรกที่พบ
        for row_idx, cells in list(latest_sheet_data.items())[:3]:
            if isinstance(cells, list) and len(cells) > 10:
                sample_cell = cells[10]  # Column K
                if isinstance(sample_cell, dict):
                    print(f"📋 Sample cell structure (Row {row_idx}, Col K): {list(sample_cell.keys())}")
                    if "color" in sample_cell:
                        print(f"   Color value: {sample_cell['color']} (type: {type(sample_cell['color'])})")
    return "OK", 200

# ================== CORE CHECK ==================
def has_round_for_district(district_name):
    district_name = district_name.lower().strip()

    DISTRICT_COL = 10   # K โรงพยาบาล
    
    if not isinstance(latest_sheet_data, dict):
        return None

    # หา PARTNER_COL และ NOTE_COL จาก header (row 1)
    PARTNER_COL = None
    NOTE_COL = None
    
    if "1" in latest_sheet_data:
        header_row = latest_sheet_data["1"]
        if isinstance(header_row, list):
            for idx, cell in enumerate(header_row):
                if isinstance(cell, dict):
                    cell_value = str(cell.get("value", "")).lower().strip()
                    if "พันธมิตร" in cell_value or "partner" in cell_value:
                        PARTNER_COL = idx
                        print(f"📊 Found PARTNER_COL at index {idx}")
                    if "หมายเหตุ" in cell_value or "note" in cell_value or "remark" in cell_value:
                        NOTE_COL = idx
                        print(f"📊 Found NOTE_COL at index {idx}")

    # เรียง row_idx เป็นตัวเลขเพื่อให้ผลลัพธ์สม่ำเสมอ (ใช้ stable sort)
    def get_row_key(item):
        row_key = item[0]
        try:
            return int(row_key)
        except (ValueError, TypeError):
            return 999999
    
    sorted_rows = sorted(latest_sheet_data.items(), key=get_row_key)
    
    # เก็บผลลัพธ์ที่มีสีถูกต้องแถวแรก (ใช้แถวบนสุดเมื่อมีหลายแถว)
    first_valid_result = None
    
    # ตรวจสอบแต่ละแถว - ถ้าเจอสีที่ถูกต้องให้เก็บไว้
    for row_idx, cells in sorted_rows:
        if str(row_idx) == "1":
            continue

        if not isinstance(cells, list):
            continue

        if len(cells) <= NOTE_COL:
            continue

        # โรงพยาบาล - เก็บชื่อจริงและตัวเปรียบเทียบแยกกัน
        district_cell = cells[DISTRICT_COL] if isinstance(cells[DISTRICT_COL], dict) else {}
        district_value_original = str(district_cell.get("value", "")).strip()  # ชื่อจริง
        district_value = district_value_original.lower().strip()  # สำหรับเปรียบเทียบ

        # เปรียบเทียบชื่ออำเภอให้ตรงกันมากขึ้น
        if district_name not in district_value and district_value not in district_name:
            continue

        # เจอแถวที่ตรงกัน ตอนนี้เช็คสีเลย
        row_idx_display = row_idx
        print(f"🔍 {district_name} | Row {row_idx_display} | Found matching row, checking colors...")
        
        # เช็คสีเฉพาะ K O P
        color_cells = [
            (DISTRICT_COL, "K", cells[DISTRICT_COL]),
            (PARTNER_COL, "O", cells[PARTNER_COL]),
            (NOTE_COL, "P", cells[NOTE_COL])
        ]

        has_valid_color = False
        valid_color_col_idx = None
        
        for col_idx, col_name, c in color_cells:
            if not isinstance(c, dict):
                print(f"   ⚠️ {district_name} | Row {row_idx_display} | Col {col_name}({col_idx}) | Not a dict: {type(c)}")
                continue
            
            # ตรวจสอบทุก key ที่เป็นไปได้สำหรับ color
            color_data = None
            found_key = None
            
            # ลำดับความสำคัญ: color > backgroundColor > bgColor > fill > background
            priority_keys = ["color", "backgroundColor", "bgColor", "fill", "background"]
            for key in priority_keys:
                if key in c:
                    val = c[key]
                    # รับค่าได้ทั้ง string, dict, หรือค่า truthy อื่นๆ
                    if val:
                        color_data = val
                        found_key = key
                        print(f"   ✅ Found color in key '{key}': {color_data} (type: {type(color_data)})")
                        break
            
            # ถ้ายังไม่มี ลองค้นหา keys ที่มีคำว่า "color" ในชื่อ
            if not color_data:
                for key, value in c.items():
                    if isinstance(key, str) and "color" in key.lower() and key not in priority_keys:
                        if value:
                            color_data = value
                            found_key = key
                            print(f"   ✅ Found color in key '{key}': {color_data} (type: {type(color_data)})")
                            break
            
            # ถ้ายังไม่มี ลองดู values ทั้งหมดที่อาจเป็น color (hex string)
            if not color_data:
                for key, value in c.items():
                    if isinstance(value, str):
                        value_clean = value.strip().upper()
                        if value_clean.startswith("#") or (len(value_clean) == 6 and all(ch in "0123456789ABCDEF" for ch in value_clean)):
                            color_data = value
                            found_key = key
                            print(f"   ✅ Found hex color in key '{key}': {color_data}")
                            break
            
            # ตรวจสอบสี
            if color_data and is_allowed_color(color_data):
                has_valid_color = True
                valid_color_col_idx = col_idx
                print(f"   ✅✅ {district_name} | FOUND VALID COLOR in row {row_idx_display}, col {col_name}({col_idx}): {color_data}")
                break
        
        # ถ้าแถวนี้มีสีที่ถูกต้อง ให้เก็บไว้ (ใช้แถวบนสุดเมื่อมีหลายแถว)
        if has_valid_color:
            # ดึง partner และ note จากเฉพาะแถวนี้
            partner_text = ""
            note_text = ""
            
            # ดึงจาก PARTNER_COL ถ้าหาเจอ
            if PARTNER_COL is not None and len(cells) > PARTNER_COL:
                partner_cell = cells[PARTNER_COL]
                if isinstance(partner_cell, dict):
                    partner_text = str(partner_cell.get("value", "")).strip()
            
            # ดึงจาก NOTE_COL ถ้าหาเจอ
            if NOTE_COL is not None and len(cells) > NOTE_COL:
                note_cell = cells[NOTE_COL]
                if isinstance(note_cell, dict):
                    note_text = str(note_cell.get("value", "")).strip()
            
            # Filter ข้อมูลขยะ - ถ้ามี whitespace เท่านั้นให้ถือว่า empty
            partner_text = partner_text if partner_text and partner_text.replace(" ", "") else ""
            note_text = note_text if note_text and note_text.replace(" ", "") else ""
            
            print(f"   ✅✅✅ {district_name} | FOUND FIRST RESULT from row {row_idx_display} | hospital='{district_value_original}' | partner='{partner_text}' | note='{note_text}'")
            
            # เก็บผลลัพธ์แถวแรกเท่านั้น
            if first_valid_result is None:
                first_valid_result = {
                    "hospital": district_value_original,  # ใช้ชื่อจริง ไม่ใช่ lowercase
                    "partner": partner_text,
                    "note": note_text
                }
    
    # return ผลลัพธ์แถวบนสุด
    if first_valid_result:
        print(f"   ✅✅✅ {district_name} | RETURNING FINAL RESULT: {first_valid_result}")
        return first_valid_result

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
    text = event.message.text.lower()
    districts = [d for d in BURIRAM_DISTRICTS if d.lower() in text]

    if not districts:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ กรุณาระบุโรงพยาบาลในบุรีรัมย์")
        )
        return

    # ถ้ายังไม่มีข้อมูล
    if not latest_sheet_data or not isinstance(latest_sheet_data, dict):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⏳ กำลังซิงค์ข้อมูลจากชีทค่ะ กรุณารอสักครู่แล้วลองใหม่")
        )
        return

    replies = []
    follow = False

    for d in districts:
        result = has_round_for_district(d)
        if result:
            follow = True
            # รูปแบบ: มีรับกลับของ hospital(พันธมิตร ถ้ามี)(หมายเหตุ)
            hospital_text = result["hospital"].strip() if result["hospital"] else ""
            partner_text = result["partner"].strip() if result["partner"] else ""
            note_text = result["note"].strip() if result["note"] else ""
            
            # เริ่มจาก "มีรับกลับของ"
            msg = f"มีรับกลับของ {hospital_text if hospital_text else d}"
            
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
def fetch_sheet_data():
    """ดึงข้อมูล Google Sheets อัตโนมัติ"""
    global latest_sheet_data, sheet_ready
    
    google_apps_script_url = os.getenv("GOOGLE_APPS_SCRIPT_URL")
    if not google_apps_script_url:
        print("❌ GOOGLE_APPS_SCRIPT_URL not found in environment variables")
        return
    
    try:
        print("🔄 Fetching sheet data on startup...")
        response = requests.get(google_apps_script_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data and "full_sheet_data" in data:
            latest_sheet_data = data["full_sheet_data"]
            sheet_ready = True
            print("✅ Sheet data loaded successfully on startup")
            print(f"📊 Total rows: {len(latest_sheet_data)}")
        else:
            print("⚠️ Invalid response format from Google Apps Script")
    except requests.exceptions.Timeout:
        print("⏱️ Request timeout - sheet data will be loaded on first user message")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Error fetching sheet data: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    # ดึงข้อมูลในเธรดแยกเพื่อไม่บล็อก startup
    fetch_thread = threading.Thread(target=fetch_sheet_data, daemon=True)
    fetch_thread.start()
    
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
