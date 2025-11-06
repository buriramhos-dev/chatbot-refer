from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback
import os 

app = Flask(__name__)

# 💡 ใช้ os.environ.get เพื่อความปลอดภัยและความยืดหยุ่นในการ Deploy
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "vM+usFSHFuusmIgBb/CJ2VunpRjc7hAAEvay49L0a1PKC5vXrfUl5R0kbHyIkiOBUH1V0Ml+Sffwcg9Jnnv1w9EZhGROiaMI7vetYw219W4UG346Lr5rRMnRnhQfo0m1vCXNL09bmCtltxHa+hQNlQdB04t89/1O/w1cDnyilFU=")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "d379c29f26e039198e837c19a75f18c2")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN, timeout=15)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์", "คูเมือง", "กระสัง", "นางรอง", "หนองกี่", 
    "ละหานทราย", "ประโคนชัย", "บ้านกรวด", "พุทไธสง", "ลำปลายมาศ", 
    "สตึก", "จักราช", "ห้วยราช", "โนนสุวรรณ", "ปะคำ", 
    "นาโพธิ์", "หนองหงส์", "พลับพลาชัย", "เฉลิมพระเกียรติ", "ชำนิ", 
    "บ้านใหม่ไชยพจน์", "โนนดินแดง", "แคนดง" , "ลำทะเมนชัย" , "เมืองยาง" 
]

# รหัสสีที่อนุญาตให้ถือว่า "มีรอบรถกลับ"
allowed_return_trip_colors = ["#00ffff", "#ffff00"]

latest_sheet_data = {} 

@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data
    data = request.json
    print(f"** RECEIVED UPDATE REQUEST ** Data Keys: {data.keys()}") 

    if not data:
        print("🛑 No JSON data received") 
        return "No JSON data received", 400

    full_data = data.get("full_sheet_data")

    if full_data:
        latest_sheet_data = full_data 
        print(f"✅ Updated FULL SHEET data. Total Rows: {len(latest_sheet_data)}")
        edited_row = data.get("edited_row", "N/A")
        print(f"   (Detected original edit on row: {edited_row})")
    else:
        # โค้ดสำรองสำหรับกรณีที่ Apps Script อาจจะยังส่งข้อมูลทีละแถวมา
        row = data.get("row")
        row_cells = data.get("row_cells", [])
        if row is not None:
            latest_sheet_data[str(row)] = row_cells 
            print(f"⚠️ Fallback: Updated single row {row} with {len(row_cells)} cells")
        else:
            print("❌ Error: Data format is not recognized (Missing full_sheet_data or row)")
            return "Data format error", 400
            
    return "OK", 200

def has_round_for_district(district_name):
    """
    ตรวจสอบและคืนค่าผลลัพธ์พร้อมรายละเอียดหมายเหตุ (ถ้าพบสีเหลือง)
    - สีฟ้า (#00ffff): คืนค่า {"status": "CYAN", "note": ""}
    - สีเหลือง (#ffff00): คืนค่า {"status": "YELLOW", "note": "[ข้อความในช่อง P]"}
    - ไม่พบ: คืนค่า None
    """
    district_name_lower = district_name.lower().strip()
    
    # 💡 Index คอลัมน์: K = Index 10 (ชื่อ), P = Index 15 (หมายเหตุ)
    DISTRICT_COLUMN_INDEX = 10 
    NOTE_COLUMN_INDEX = 15    

    for row_number, cells in latest_sheet_data.items(): 
        if row_number == '1': 
             continue

        # 1. ตรวจสอบความยาวของแถว
        if len(cells) <= DISTRICT_COLUMN_INDEX:
            continue

        # 2. ดึงข้อมูลเซลล์ชื่ออำเภอ (Column K, Index 10)
        district_cell = cells[DISTRICT_COLUMN_INDEX]
        district_value = str(district_cell.get("value", "")).lower().strip()
        color_hex_rgb = str(district_cell.get("color", ""))[:7].lower() 
        
        is_district_match = district_name_lower in district_value
        
        if is_district_match:
            
            # 💡 กรณีที่ 1: สีฟ้า (#00ffff)
            if color_hex_rgb == "#00ffff":
                print(f"✅ FOUND MATCH: District '{district_name}' found (Cyan).")
                return {"status": "CYAN", "note": ""}
            
            # 💡 กรณีที่ 2: สีเหลือง (#ffff00)
            elif color_hex_rgb == "#ffff00":
                
                note_value = ""
                if len(cells) > NOTE_COLUMN_INDEX:
                    # 3. ดึงข้อมูลเซลล์หมายเหตุ (Column P, Index 15)
                    note_cell = cells[NOTE_COLUMN_INDEX]
                    note_value = str(note_cell.get("value", "")).strip() # ไม่ต้องแปลงเป็นตัวพิมพ์เล็ก
                
                print(f"✅ FOUND MATCH: District '{district_name}' found (Yellow) with note: '{note_value}'.")
                return {"status": "YELLOW", "note": note_value} 
            
    print(f"❌ NO MATCH FOUND for district '{district_name_lower}'.")
    return None # ไม่พบรับกลับตามเงื่อนไข

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        print(f"❌ ERROR in callback handler: {e}")
        traceback.print_exc()
        abort(500)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        text = event.message.text.strip()
        text_lower = text.lower()
        
        # 1. ค้นหาชื่ออำเภอที่ผู้ใช้ถามถึง
        found_districts = []
        for d in BURIRAM_DISTRICTS:
            if d.lower() in text_lower: 
                found_districts.append(d) 

        if not found_districts:
            # 💡 แก้ไขคำว่า "รอบรถกลับ" เป็น "รับกลับ" ในข้อความแจ้งเตือน
            if "รับกลับ" in text or "มีไหม" in text:
                reply = "❌ กรุณาระบุชื่อโรงพยาบาลในบุรีรัมย์ ที่ต้องการตรวจสอบรับกลับ"
            else:
                reply = "❌ กรุณาพิมพ์ชื่อโรงพยาบาลในบุรีรัมย์ เช่น 'นางรองมีรับกลับไหม'"
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

        # 2. วนลูปเช็คสี/รับกลับ สำหรับทุกอำเภอที่ตรวจพบ
        results = []
        for d in found_districts:
            check_result = has_round_for_district(d)
            
            if check_result is not None:
                status = check_result["status"]
                note = check_result["note"].strip()
                
                if status == "CYAN":
                    # 💡 สีฟ้า: ใช้คำว่า "มีรับกลับ"
                    results.append(f" มีรับกลับของ {d}")
                    
                elif status == "YELLOW":
                    # 💡 สีเหลือง: ใช้คำว่า "มีรับกลับ" พร้อมดึงหมายเหตุมาแสดง
                    if note:
                        # ถ้ามีหมายเหตุ (เช่น รับที่ตึก, โทรเช็ค)
                        results.append(f" มีรับกลับของ {d} **({note})**") 
                    else:
                        # ถ้าไม่มีหมายเหตุ (แต่เป็นสีเหลือง)
                        results.append(f"มีรับกลับของ {d}")
            else: # check_result is None
                # 💡 ใช้คำว่า "ไม่มีรับกลับ"
                results.append(f"ไม่มีรับกลับของ {d}")

        # 3. รวมผลลัพธ์ทั้งหมด
        reply = "\n".join(results)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

    except Exception as e:
        print("❌ ERROR in handle_message:", e)
        traceback.print_exc()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เกิดข้อผิดพลาดในการประมวลผลค่ะ 🙏"))

if __name__ == "__main__":
    app.run(debug=True)