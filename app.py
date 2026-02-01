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
    
    # สีฟ้า (Cyan): #00ffff = (0, 255, 255)
    # เงื่อนไข: B และ G สูงมาก (>=180), R ต่ำมาก (<=75)
    # ยืดหยุ่นมากขึ้นเพื่อรองรับการเปลี่ยนแปลงเล็กน้อยจาก Google Sheets
    is_blue = b >= 180 and g >= 180 and r <= 75
    
    # สีเหลือง (Yellow): #ffff00 = (255, 255, 0)
    # เงื่อนไข: R และ G สูงมาก (>=200 สำหรับแม่นยำ), B ต่ำมาก (<=50)
    # ยืดหยุ่นเหมาะสม
    is_yellow = (r >= 200 and g >= 200 and b <= 50)
    
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
    PARTNER_COL  = 14   # O พันธมิตร
    NOTE_COL     = 15   # P หมายเหตุ

    if not isinstance(latest_sheet_data, dict):
        return None

    # รวบรวมแถวที่ตรงกับชื่ออำเภอก่อน (เรียงตาม row_idx เพื่อให้ผลลัพธ์สม่ำเสมอ)
    matching_rows = []
    
    # เรียง row_idx เป็นตัวเลขเพื่อให้ผลลัพธ์สม่ำเสมอ (ใช้ stable sort)
    def get_row_key(item):
        row_key = item[0]
        try:
            return int(row_key)
        except (ValueError, TypeError):
            return 999999
    
    sorted_rows = sorted(latest_sheet_data.items(), key=get_row_key)
    
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

    # ตรวจสอบสีจากแถวที่ตรงกันทั้งหมด (เรียงตาม row_idx เพื่อให้ผลลัพธ์สม่ำเสมอ)
    for row_idx, cells, district_value in matching_rows:
        # เช็คสีเฉพาะ K O P
        color_cells = [
            (DISTRICT_COL, "K", cells[DISTRICT_COL]),
            (PARTNER_COL, "O", cells[PARTNER_COL]),
            (NOTE_COL, "P", cells[NOTE_COL])
        ]

        # ตรวจสอบสีจากแต่ละ cell อย่างครอบคลุม
        has_valid_color = False
        
        # Debug: แสดงข้อมูล cell ทั้งหมด
        print(f"🔍 {district_name} | Row {row_idx} | Checking cells...")
        print(f"   Cell K keys: {list(cells[DISTRICT_COL].keys()) if isinstance(cells[DISTRICT_COL], dict) else 'Not a dict'}")
        print(f"   Cell O keys: {list(cells[PARTNER_COL].keys()) if isinstance(cells[PARTNER_COL], dict) else 'Not a dict'}")
        print(f"   Cell P keys: {list(cells[NOTE_COL].keys()) if isinstance(cells[NOTE_COL], dict) else 'Not a dict'}")
        
        for col_idx, col_name, c in color_cells:
            if not isinstance(c, dict):
                print(f"   ⚠️ {district_name} | Row {row_idx} | Col {col_name}({col_idx}) | Not a dict: {type(c)}")
                continue
            
            # Debug: แสดง keys ทั้งหมดใน cell
            print(f"   📋 {district_name} | Row {row_idx} | Col {col_name}({col_idx}) | All keys: {list(c.keys())}")
            
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
            
            # ถ้ายังไม่มี แสดงทุก values เพื่อ debug
            if not color_data:
                print(f"   ⚠️ {district_name} | Row {row_idx} | Col {col_name}({col_idx}) | No color found. All values: {dict(c)}")
            else:
                # Debug: แสดงข้อมูลสีที่พบ
                rgb = normalize_color_to_rgb(color_data)
                if rgb:
                    is_valid = is_allowed_color(color_data) if color_data else False
                    print(f"   🎨 {district_name} | Row {row_idx} | Col {col_name}({col_idx}) | key={found_key} | color={color_data} | rgb={rgb} | valid={is_valid}")
                else:
                    print(f"   ⚠️ {district_name} | Row {row_idx} | Col {col_name}({col_idx}) | key={found_key} | color={color_data} | rgb=None (cannot normalize)")
            
            # ตรวจสอบสี
            if color_data and is_allowed_color(color_data):
                has_valid_color = True
                print(f"   ✅✅ {district_name} | FOUND VALID COLOR in row {row_idx}, col {col_name}({col_idx}): {color_data}")
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
    # เช็คว่ามีข้อมูลหรือไม่ (ไม่ต้องรอ sheet_ready)
    if not latest_sheet_data or not isinstance(latest_sheet_data, dict):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⏳ กำลังซิงค์ข้อมูลจากชีทค่ะ กรุณารอสักครู่แล้วลองใหม่")
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
