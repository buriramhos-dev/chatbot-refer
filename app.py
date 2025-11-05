from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import traceback

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = "vM+usFSHFuusmIgBb/CJ2VunpRjc7hAAEvay49L0a1PKC5vXrfUl5R0kbHyIkiOBUH1V0Ml+Sffwcg9Jnnv1w9EZhGROiaMI7vetYw219W4UG346Lr5rRMnRnhQfo0m1vCXNL09bmCtltxHa+hQNlQdB04t89/1O/w1cDnyilFU="
LINE_CHANNEL_SECRET = "d379c29f26e039198e837c19a75f18c2"
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN, timeout=15)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# รายการชื่ออำเภอทั้งหมดในจังหวัดบุรีรัมย์ (ต้องเป็นตัวพิมพ์เล็กทั้งหมด)
# ใช้ชื่อหลักที่คาดว่าจะพบใน Google Sheet
BURIRAM_DISTRICTS = [
    "เมืองบุรีรัมย์", "คูเมือง", "กระสัง", "นางรอง", "หนองกี่", 
    "ละหานทราย", "ประโคนชัย", "บ้านกรวด", "พุทไธสง", "ลำปลายมาศ", 
    "สตึก", "จักราช", "ห้วยราช", "โนนสุวรรณ", "ปะคำ", 
    "นาโพธิ์", "หนองหงส์", "พลับพลาชัย", "เฉลิมพระเกียรติ", "ชำนิ", 
    "บ้านใหม่ไชยพจน์", "โนนดินแดง", "แคนดง" 
    # ตรวจสอบชื่ออำเภอเหล่านี้ให้แน่ใจว่าตรงกับข้อมูลใน Google Sheet
]

# รหัสสีที่อนุญาตให้ถือว่า "มีรอบรถกลับ"
allowed_return_trip_colors = ["#00ffff", "#ffff00"]# เฉพาะสีฟ้า (Cyan) ที่คุณต้องการ

latest_sheet_data = {}  # {row: [ {value, color}, ... ] }

# ต้องมีการประกาศตัวแปร global 'latest_sheet_data' นอกฟังก์ชัน
# global latest_sheet_data = {} (หรือดึงมาจากไฟล์, แล้วแต่โค้ดของคุณ)

@app.route("/update", methods=["POST"])
def update_sheet():
    global latest_sheet_data # ประกาศตัวแปร global เพื่ออัปเดตข้อมูล

    data = request.json
    print(f"** RECEIVED UPDATE REQUEST ** Data Keys: {data.keys()}") 

    if not data:
        print("🛑 No JSON data received") 
        return "No JSON data received", 400

    # 1. 💡 ตรวจสอบและดึงข้อมูลทั้งชีท (คีย์ใหม่จาก Apps Script)
    full_data = data.get("full_sheet_data")

    if full_data:
        # 2. 💡 อัปเดตตัวแปร global ด้วยข้อมูลทั้งชีทที่ได้รับมา
        latest_sheet_data = full_data 
        
        # 3. แสดง Log ว่าอัปเดตข้อมูลทั้งหมดแล้ว
        print(f"✅ Updated FULL SHEET data. Total Rows: {len(latest_sheet_data)}")
        
        # (Optional) Log เพื่อตรวจสอบแถวที่มีการแก้ไขล่าสุด
        edited_row = data.get("edited_row", "N/A")
        print(f"   (Detected original edit on row: {edited_row})")
        
    else:
        # โค้ดสำรองสำหรับกรณีที่ Apps Script อาจจะยังส่งข้อมูลทีละแถวมา
        row = data.get("row")
        row_cells = data.get("row_cells", [])
        if row is not None:
            latest_sheet_data[str(row)] = row_cells # ใช้ str(row) เพื่อให้เข้ากันกับ Apps Script
            print(f"⚠️ Fallback: Updated single row {row} with {len(row_cells)} cells")
        else:
            print("❌ Error: Data format is not recognized (Missing full_sheet_data or row)")
            return "Data format error", 400
            
    return "OK", 200

# รายการอำเภอและสีที่อนุญาตยังคงอยู่เหมือนเดิม
# BURIRAM_DISTRICTS = [...]
# allowed_return_trip_colors = ["#00ffff", "#ffff00"] 

def has_round_for_district(district_name):
    # ฟังก์ชันนี้จะเช็คว่าอำเภอที่ถาม (district_name) มีสีที่กำหนดหรือไม่
    district_name_lower = district_name.lower().strip()

    # วนลูปผ่านทุกแถว (ข้อมูลทั้งชีท)
    for row_number, cells in latest_sheet_data.items(): 
        if row_number == '1': # ข้ามแถวหัวข้อ
             continue

        # วนลูปผ่านทุกเซลล์ในแถวนั้น
        for cell in cells:
            value = str(cell.get("value", "")).lower().strip()
            color_hex_rgb = str(cell.get("color", ""))[:7].lower() 
            
            # ตรวจสอบ: อำเภอที่ผู้ใช้ถาม ต้องอยู่ในค่าเซลล์ AND สีต้องเป็นสีที่กำหนด
            is_district_found = district_name_lower in value 
            is_color_ok = color_hex_rgb in allowed_return_trip_colors

            if is_district_found and is_color_ok:
                # Log และส่งค่ากลับทันที
                print(f"✅ FOUND MATCH: District '{district_name}' found in row {row_number} with color {color_hex_rgb}.")
                return True # พบรอบรถกลับ
                
    # ถ้าวนลูปทั้งหมดแล้วไม่เจอเลย
    print(f"❌ NO MATCH FOUND for district '{district_name_lower}'.")
    return False # ไม่มีรอบรถกลับ

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    try:
        text = event.message.text.strip()
        text_lower = text.lower()  # 💡 แปลงข้อความที่ผู้ใช้พิมพ์เป็นตัวพิมพ์เล็ก
        
        # 1. ค้นหาชื่ออำเภอที่ผู้ใช้ถามถึง (รองรับหลายอำเภอในข้อความเดียว)
        found_districts = []
        for d in BURIRAM_DISTRICTS:
            if d.lower() in text_lower: # 💡 เปรียบเทียบกับรายการอำเภอที่แปลงเป็นตัวพิมพ์เล็กแล้ว
                found_districts.append(d) # เก็บชื่ออำเภอ (ตัวพิมพ์ใหญ่ตามต้นฉบับ)

        if not found_districts:
            # เพิ่มการเช็คคำถามทั่วไปที่ไม่มีชื่ออำเภอ เช่น "มีรอบรถกลับไหม"
            if "รอบรถกลับ" in text or "มีไหม" in text:
                 # 💡 ถ้าถามถึงรอบรถกลับแต่ไม่ระบุอำเภอ ให้ตอบว่าไม่พบชื่ออำเภอ
                 reply = "❌ กรุณาระบุชื่ออำเภอในบุรีรัมย์ที่ต้องการตรวจสอบรอบรถกลับ"
            else:
                 reply = "❌ กรุณาพิมพ์ชื่ออำเภอในบุรีรัมย์ เช่น 'นางรองมีรอบรถกลับไหม'"
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

        # 2. วนลูปเช็คสี/รอบรถ สำหรับทุกอำเภอที่ตรวจพบ
        results = []
        for d in found_districts:
            # โค้ดนี้จะเรียกฟังก์ชัน has_round_for_district(d) ซึ่งจะไปเช็คสีใน latest_sheet_data
            if has_round_for_district(d):
                results.append(f"มีรอบรถกลับของอำเภอ {d}")
            else:
                results.append(f"ไม่มีรอบรถกลับของอำเภอ {d}")

        # 3. รวมผลลัพธ์ทั้งหมด
        reply = "\n".join(results)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

    except Exception as e:
        print("❌ ERROR in handle_message:", e)
        # ใช้ traceback.format_exc() เพื่อส่งข้อมูล error ที่ละเอียดขึ้น
        import traceback
        error_message = traceback.format_exc()
        # ส่งข้อความแจ้งเตือนผู้ใช้และส่ง error ไปที่ Log
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เกิดข้อผิดพลาดในการประมวลผลค่ะ 🙏"))
if __name__ == "__main__":
    app.run(debug=True)
