import csv
import os
import django

# הגדרת סביבת ג'אנגו כדי שנוכל לגשת למסד הנתונים מחוץ לאתר
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import TorahText

csv_file = 'tanakh_data.csv'

if not os.path.exists(csv_file):
    print(f"שגיאה: הקובץ {csv_file} לא נמצא בתיקייה!")
else:
    print("מנקה נתונים ישנים מהמאגר (אם יש)...")
    TorahText.objects.all().delete()

    print("מתחיל לקרוא את קובץ ה-CSV ולהזריק למסד הנתונים...")
    
    with open(csv_file, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file, delimiter='|')
        batch = []
        count = 0
        
        for row in reader:
            batch.append(TorahText(
                book=row.get('Book', '').strip(),
                chapter=row.get('Chapter', '').strip(),
                verse=row.get('Verse', '').strip(),
                clean_text=row.get('CleanText', '').strip(),
                text_with_nikkud=row.get('TextWithNikkud', '').strip()
            ))
            
            if len(batch) >= 2000:
                TorahText.objects.bulk_create(batch)
                count += len(batch)
                print(f"הוזרקו {count} פסוקים למאגר...")
                batch = []
                
        if batch:
            TorahText.objects.bulk_create(batch)
            count += len(batch)

    print("========================================")
    print(f"סיום בהצלחה! סך הכל פסוקים במאגר כעת: {TorahText.objects.count()}")
    print("========================================")