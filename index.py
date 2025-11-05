# index.py
from app import app as application # นำเข้า app object จากไฟล์ app.py ของคุณ

# ไม่ต้องเพิ่ม app.run() เพราะ Vercel จะรันให้เอง
# ไฟล์นี้แค่บอกว่า application object อยู่ที่ไหน