"""
LINE Bot for Buriram Hospital Referral Check
Checks if a hospital has referral rounds available
"""

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from dotenv import load_dotenv
import requests
import threading

load_dotenv()
app = Flask(__name__)

# ==================== CONFIG ====================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Global sheet data
latest_sheet_data = None
sheet_ready = False # ==================== CONSTANTS ====================
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์", "คูเมือง", "กระสัง", "นางรอง", "หนองกี่", "ละหานทราย",
    "ประโคนชัย", "บ้านกรวด", "พุทไธสง", "ลำปลายมาศ", "สตึก", "บ้านด่าน",
    "ห้วยราช", "โนนสุวรรณ", "ปะคำ", "นาโพธิ์", "หนองหงส์", "พลับพลาชัย",
    "เฉลิมพระเกียรติ", "ชำนิ", "บ้านใหม่ไชยพจน์", "โนนดินแดง", "แคนดง",
    "ลำทะเมนชัย", "เมืองยาง", "ชุมพวง"
]

DISTRICT_COL = 10  # K
PARTNER_COL = 14   # O
NOTE_COL = 15      # P

# ==================== COLOR UTILITIES ====================
def hex_to_rgb(hex_color: str) -> tuple | None:
    """Convert hex color string to RGB tuple"""
    if not hex_color:
        return None
    
    hex_color = str(hex_color).lstrip("#").strip()
    if len(hex_color) != 6:
        return None
    
    try:
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return None


def normalize_color_to_rgb(color_data) -> tuple | None:
    """Convert color from various formats to RGB tuple"""
    if not color_data:
        return None
    
    # Handle string (hex) format
    if isinstance(color_data, str):
        color_str = color_data.strip().upper()
        if not color_str:
            return None
        
        if color_str.startswith("#"):
            return hex_to_rgb(color_str)
        elif len(color_str) == 6 and all(c in "0123456789ABCDEF" for c in color_str):
            return hex_to_rgb("#" + color_str)
        elif len(color_str) == 7 and all(c in "0123456789ABCDEF" for c in color_str[:6]):
            return hex_to_rgb("#" + color_str[:6])
        
        return hex_to_rgb(color_str)
    
    # Handle dict format (Google Sheets API)
    if isinstance(color_data, dict):
        # Try nested color object
        if "color" in color_data and isinstance(color_data["color"], dict):
            return normalize_color_to_rgb(color_data["color"])
        
        # Try rgbColor
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
        
        # Try direct RGB values
        if "red" in color_data and "green" in color_data and "blue" in color_data:
            try:
                red_val = float(color_data["red"])
                green_val = float(color_data["green"])
                blue_val = float(color_data["blue"])
                
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
        
        # Try hex in dict
        if "hex" in color_data:
            return hex_to_rgb(color_data["hex"])
    
    return None


def is_allowed_color(color_data) -> bool:
    """Check if color is allowed (blue or yellow)
    
    - Blue (Cyan): RGB(0, 255, 255) - B and G high, R low
    - Yellow: RGB(255, 255, 0) - R and G high, B low
    """
    if not color_data:
        return False
    
    if isinstance(color_data, str) and not color_data.strip():
        return False
    
    rgb = normalize_color_to_rgb(color_data)
    if not rgb:
        return False
    
    r, g, b = rgb
    
    # Blue (Cyan)
    is_blue = (b >= 200 and g >= 200 and r <= 100)
    # Yellow
    is_yellow = (r >= 200 and g >= 200 and b <= 50)
    
    return is_blue or is_yellow
 
# ==================== SHEET MANAGEMENT ====================
def fetch_sheet_data():
    """Fetch Google Sheets data from Apps Script"""
    global latest_sheet_data, sheet_ready
    
    google_apps_script_url = os.getenv("GOOGLE_APPS_SCRIPT_URL")
    if not google_apps_script_url:
        print("❌ GOOGLE_APPS_SCRIPT_URL not set")
        return
    
    try:
        print("🔄 Fetching sheet data...")
        response = requests.get(google_apps_script_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data and "full_sheet_data" in data:
            latest_sheet_data = data["full_sheet_data"]
            sheet_ready = True
            print("✅ Sheet data loaded")
            if isinstance(latest_sheet_data, dict):
                print(f"📊 Total rows: {len(latest_sheet_data)}")
        else:
            print("⚠️ Invalid response format")
    except requests.exceptions.Timeout:
        print("⏱️ Request timeout")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Request error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


@app.route("/update", methods=["POST"])
def update_sheet():
    """Update sheet data from Apps Script webhook"""
    global latest_sheet_data, sheet_ready
    
    data = request.json
    if not data or "full_sheet_data" not in data:
        return "Invalid payload", 400
    
    latest_sheet_data = data["full_sheet_data"]
    sheet_ready = True
    print("✅ Sheet data updated")
    
    if isinstance(latest_sheet_data, dict):
        print(f"📊 Total rows: {len(latest_sheet_data)}")
    
    return "OK", 200
 # ==================== DISTRICT LOOKUP ====================
def has_round_for_district(district_name: str) -> dict | None:
    district_name = district_name.lower().strip()

    if not isinstance(latest_sheet_data, dict):
        return None

    # sort แถวตามลำดับจริง
    rows = sorted(
        latest_sheet_data.items(),
        key=lambda x: int(x[0]) if x[0].isdigit() else 999999
    )

    for row_idx, cells in rows:
        if row_idx == "1" or not isinstance(cells, list):
            continue

        if len(cells) <= NOTE_COL:
            continue

        # ✅ 1. ชื่อโรงพยาบาลต้องตรงก่อน
        hospital_cell = cells[DISTRICT_COL]
        hospital_name = str(hospital_cell.get("value", "")).strip()
        hospital_lower = hospital_name.lower()

        if district_name not in hospital_lower:
            continue

        # ✅ 2. เช็คเฉพาะ backgroundColor ของแถวนี้
        for col in [DISTRICT_COL, PARTNER_COL, NOTE_COL]:
            cell = cells[col]
            if not isinstance(cell, dict):
                continue

            bg_color = cell.get("backgroundColor")
            if is_allowed_color(bg_color):
                # ✅ เจอฟ้า/เหลืองจริง → ใช้แถวนี้
                partner = ""
                note = ""

                if PARTNER_COL < len(cells):
                    partner = str(cells[PARTNER_COL].get("value", "")).strip()

                if NOTE_COL < len(cells):
                    note = str(cells[NOTE_COL].get("value", "")).strip()

                return {
                    "hospital": hospital_name,
                    "partner": partner,
                    "note": note
                }

    # ❌ มีแต่สีอื่นทั้งหมด
    return None

 
# ==================== LINE WEBHOOK ====================
@app.route("/callback", methods=["POST"])
def callback():
    """LINE webhook callback"""
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """Handle text messages from LINE"""
    text = event.message.text.lower()
    districts = [d for d in BURIRAM_DISTRICTS if d.lower() in text]
    
    if not districts:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ กรุณาระบุโรงพยาบาลในบุรีรัมย์")
        )
        return
    
    # Fetch data if not available
    if not latest_sheet_data or not isinstance(latest_sheet_data, dict):
        fetch_sheet_data()
    
    if not latest_sheet_data or not isinstance(latest_sheet_data, dict):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="⏳ กำลังซิงค์ข้อมูล กรุณารอสักครู่แล้วลองใหม่")
        )
        return
    
    # Check each district
    replies = []
    follow = False
    
    for d in districts:
        result = has_round_for_district(d)
        
        if result:
            follow = True
            hospital = result["hospital"].strip() if result["hospital"] else d
            partner = result["partner"].strip() if result["partner"] else ""
            note = result["note"].strip() if result["note"] else ""
            
            msg = f"มีรับกลับของ {hospital}"
            if partner:
                msg += f"({partner})"
            if note:
                msg += f"({note})"
        else:
            msg = f"ไม่มีรอบรับกลับ {d}"
        
        replies.append(msg)
    
    messages = [TextSendMessage(text="\n".join(replies))]
    if follow:
        messages.append(TextSendMessage(text="ล้อหมุนกี่โมงคะ"))
    
    line_bot_api.reply_message(event.reply_token, messages)


# ==================== MAIN ====================
if __name__ == "__main__":
    # Fetch data on startup in background
    fetch_thread = threading.Thread(target=fetch_sheet_data, daemon=True)
    fetch_thread.start()
    
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
