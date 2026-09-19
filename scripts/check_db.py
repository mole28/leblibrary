import os
import sqlite3

# מחפש את הקובץ בדיוק איפה שאתה נמצא עכשיו
db_path = 'db.sqlite3'

print("--- מחפש קישורים שגויים בתוך ה-Database המקומי ---")
try:
    if not os.path.exists(db_path):
        print(f"שגיאה: לא מצאתי את {db_path}. ודא שאתה מריץ את הסקריפט מתוך התיקייה mosheArticles.")
    else:
        # סריקה מהירה של כל הקובץ
        with open(db_path, 'rb') as f:
            if b'/https://' not in f.read():
                print("✅ מסד הנתונים נקי! זה לא שם.")
            else:
                print("🚨 בינגו! המחרוזת '/https://' נמצאה בתוך ה-Database שלך.")
                print("זה אומר שהקישור השגוי מסתתר בתוך טקסט שהזנת דרך מערכת הניהול!")
                
                # התחברות למסד הנתונים לאיתור מדויק
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # חיפוש במאמרים
                cursor.execute("SELECT id, title FROM articles_article WHERE content LIKE '%/https://%'")
                articles = cursor.fetchall()
                
                if articles:
                    print("\nמצאתי את התקלה במאמרים הבאים:")
                    for a in articles:
                        print(f"-> מאמר מספר {a[0]}: {a[1]}")
                    print("\nכנס למערכת הניהול, ערוך את המאמרים האלו, ותקן את הקישור השבור בטקסט.")
                else:
                    print("\nהמחרוזת קיימת, אבל לא בטבלת המאמרים. אולי היא בספרים או בהגדרות אחרות.")
except Exception as e:
    print("שגיאה בסריקה:", e)