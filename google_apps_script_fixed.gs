var SPREADSHEET_ID = "1G0TBdoNavCR2jUwQMCMcRBJd9OFNEAmZhk6bb22p8Sw";
var SHEET_NAME = "1.Refer Back by Amb";
var API_URL = "https://web-production-5ad45.up.railway.app/update";

/**
 * ส่งข้อมูลทั้งชีท (value + color) ไปที่ Flask
 */
function sendSheetToFlask() {
  Logger.log("🔔 sendSheetToFlask() called");
  
  // ===== FIX 1: เพิ่ม delay ให้ Sheets render color เสร็จสมบูรณ์ =====
  Utilities.sleep(2000); // รอ 2.0 วินาที เพื่อให้สี render เสร็จ
  
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    Logger.log("❌ Lock not available");
    return;
  }

  try {
    var spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sheet = spreadsheet.getSheetByName(SHEET_NAME);

    if (!sheet) {
      throw new Error("Sheet '" + SHEET_NAME + "' not found");
    }

    var lastRow = sheet.getLastRow();
    var lastCol = sheet.getLastColumn();

    if (lastRow === 0 || lastCol === 0) {
      Logger.log("⚠️ Sheet ว่างเปล่า");
      return;
    }

    // ===== FIX 4: จำกัดจำนวนแถวที่จะส่ง เพื่อหลีกเลี่ยงการส่งแถวเปล่าจำนวนมาก =====
    var FIXED_MAX_ROWS = 1000;  // ลดจากเดิมเพื่อลดเวลาในการรัน/ขนาด payload

    // บางครั้ง getLastRow() อาจไม่แม่นยำ (format/สี/row hidden) -> สแกนค่าจริงเพื่อหา last non-empty row
    var sampleRange = sheet.getRange(1, 1, lastRow, lastCol);
    var sampleValues = sampleRange.getValues();
    var computedLastRow = 0;
    for (var i = sampleValues.length - 1; i >= 0; i--) {
      var rowHasValue = false;
      for (var j = 0; j < sampleValues[i].length; j++) {
        if (sampleValues[i][j] !== null && sampleValues[i][j] !== "") {
          rowHasValue = true;
          break;
        }
      }
      if (rowHasValue) {
        computedLastRow = i + 1;
        break;
      }
    }

    if (computedLastRow === 0) {
      Logger.log("⚠️ หลังสแกนไม่พบข้อมูล (empty) - getLastRow=" + lastRow);
      return;
    }

    var dataLastRow = Math.min(computedLastRow, FIXED_MAX_ROWS);
    Logger.log("📋 getLastRow()=" + lastRow + " | computedLastRow=" + computedLastRow + " | ใช้ dataLastRow=" + dataLastRow + " | คอลัมน์: " + lastCol);

    // ดึงข้อมูล + สี (ใช้ getBackgroundObjects แทน getBackgrounds)
    var range = sheet.getRange(1, 1, dataLastRow, lastCol);
    var values = range.getValues();
    var backgroundObjects = range.getBackgroundObjects();

    var full_sheet_data = {};

    for (var r = 0; r < values.length; r++) {
      var row = [];

      for (var c = 0; c < values[r].length; c++) {
        var cellValue = values[r][c] || "";
        var cellColor = "";
        
        try {
          // ===== FIX 2: ดึง RGB color จาก background object แล้วแปลงเป็น HEX =====
          var bgColor = backgroundObjects[r][c].asRgbColor();
          if (bgColor) {
            cellColor = bgColor.asHexString();  // ได้ค่า hex string เลย
          }
        } catch (e) {
          // ถ้าไม่มี color ให้ skip
          cellColor = "";
        }
        
        // ===== FIX 3: เก็บ color ทั้งหมด (ไม่กรอง #ffffff) =====
        // เพราะมีโรงพยาบาลที่ใช้สีต่าง ๆ ลองเก็บไว้แล้วให้ Flask filter
        
        row.push({
          value: cellValue,
          backgroundColor: cellColor
        });
      }

      full_sheet_data[r + 1] = row;
    }

    // ========== DEBUG: แสดง sample colors จากแถว 1-5 ==========
    // Temporarily disabled to speed up testing
    // Logger.log("\n🎨 ===== DEBUG: Sample Colors =====");
    // ... (code removed)
    // Logger.log("\n===== END DEBUG =====\n");

    var payload = {
      full_sheet_data: full_sheet_data,
      updated_at: new Date().toISOString()
    };

    Logger.log("📤 ส่งข้อมูล | แถว: " + dataLastRow + " | คอลัมน์: " + lastCol);

    // ===== เพิ่ม retry รอบการ POST เพื่อเพิ่มความทนทาน =====
    var maxAttempts = 3;
    var attempt = 0;
    var response = null;
    var success = false;

    while (attempt < maxAttempts && !success) {
      attempt++;
      try {
        response = UrlFetchApp.fetch(API_URL, {
          method: "post",
          contentType: "application/json",
          payload: JSON.stringify(payload),
          muteHttpExceptions: true
        });

        var statusCode = response.getResponseCode();
        var responseText = response.getContentText();

        if (statusCode >= 200 && statusCode < 300) {
          Logger.log("✅ ส่งข้อมูลสำเร็จ (attempt " + attempt + ") | แถว=" + dataLastRow + " | คอลัมน์=" + lastCol + " | status=" + statusCode);
          success = true;
          break;
        } else {
          Logger.log("⚠️ Attempt " + attempt + " returned " + statusCode + " | " + responseText);
        }
      } catch (e) {
        Logger.log("⚠️ Attempt " + attempt + " fetch error: " + e.message);
      }

      // backoff เล็กน้อยก่อน retry
      Utilities.sleep(500 * attempt);
    }

    if (!success) {
      Logger.log("❌ ไม่สามารถส่งข้อมูลได้หลังจาก " + maxAttempts + " ครั้ง");
      if (response) {
        Logger.log("Response last: " + response.getResponseCode() + " - " + response.getContentText());
      }
    }

  } catch (err) {
    Logger.log("🔥 ERROR: " + err.message + "\n" + err.stack);
  } finally {
    lock.releaseLock();
    Logger.log("🔚 sendSheetToFlask finished");
  }
}

/**
 * Trigger: เมื่อมีการแก้ไขชีท
 */
function onEdit(e) {
  Logger.log("📝 onEdit triggered");
  sendSheetToFlask();
}

/**
 * Trigger: Time-driven (ทุก 5 นาที)
 */
function syncByTimeTrigger() {
  Logger.log("⏰ Time-driven sync triggered");
  sendSheetToFlask();
}

/**
 * Manual trigger (ใช้ทำการดึงข้อมูลแบบ manual)
 */
function manualSync() {
  Logger.log("🔄 Manual sync started");
  sendSheetToFlask();
  Logger.log("🔄 Manual sync completed");
}

/**
 * ทดสอบการเชื่อมต่อ API
 */
function testConnection() {
  try {
    Logger.log("🧪 Testing API connection...");
    
    var payload = {
      test: true,
      timestamp: new Date().toISOString()
    };
    
    var response = UrlFetchApp.fetch(API_URL, {
      method: "post",
      contentType: "application/json",
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    
    Logger.log("✅ Response: " + response.getResponseCode() + " - " + response.getContentText());
    
  } catch (err) {
    Logger.log("❌ Error: " + err.message);
  }
}
