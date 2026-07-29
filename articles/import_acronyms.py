import os
import csv
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import sys
sys.path.append(BASE_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Acronym

def import_csv():
    csv_file_path = os.path.join(BASE_DIR, "final_acronyms.csv")
    
    if not os.path.exists(csv_file_path):
        print(f"שגיאה: לא נמצא קובץ בנתיב {csv_file_path}")
        return

    print("מנקה טבלה קודמת ומתחיל בייבוא...")
    Acronym.objects.all().delete()
    
    count = 0
    # ניסיון לקרוא עם קידודים שונים כדי למנוע שגיאות
    encodings_to_try = ['utf-8-sig', 'utf-8', 'cp1255', 'latin1']
    
    f = None
    for enc in encodings_to_try:
        try:
            f = open(csv_file_path, 'r', encoding=enc)
            f.readline() # בדיקה אם מצליח לקרוא שורה
            f.seek(0)    # חזרה להתחלה
            break
        except UnicodeDecodeError:
            if f: f.close()
            continue

    if not f:
        print("שגיאה: לא הצלחנו לפענח את קידוד הקובץ.")
        return

    with f:
        reader = csv.reader(f)
        next(reader, None)  # דילוג על שורת הכותרת
        
        objects_to_create = []
        for row in reader:
            if len(row) >= 2:
                short_text = row[0].strip()
                meaning_text = row[1].strip()
                objects_to_create.append(Acronym(short=short_text, meaning=meaning_text))
                count += 1
                
        Acronym.objects.bulk_create(objects_to_create)
        
    print(f"יובאו בהצלחה {count} ראשי תיבות למסד הנתונים! האוצר בפנים.")

if __name__ == '__main__':
    import_csv()