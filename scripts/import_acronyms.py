import os
import csv
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mosheArticles.settings')  # ודא ששם הפרויקט שלך תואם
django.setup()

from articles.models import Acronym

def import_csv():
    csv_file_path = "final_acronyms.csv"
    
    if not os.path.exists(csv_file_path):
        print(f"שגיאה: לא קובץ ה-CSV נמצא בנתיב: {csv_file_path}")
        return

    print("מנקה טבלה קודמת ומתחיל בייבוא...")
    Acronym.objects.all().delete()
    
    count = 0
    with open(csv_file_path, 'r', encoding='utf-8-sig') as f:
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