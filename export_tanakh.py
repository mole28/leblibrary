import os
import django
import csv

# התיקון הקריטי: הגדרת שם הפרויקט האמיתי שלך (core)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import TorahText

def export_to_csv():
    verses = TorahText.objects.all().order_by('id')
    print(f"Exporting {verses.count()} verses...")
    
    with open('tanakh_data.csv', 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, delimiter='|')
        # שורת כותרות לסידור הנתונים
        writer.writerow(['Book', 'Chapter', 'Verse', 'CleanText', 'TextWithNikkud'])
        
        for v in verses:
            # נדאג שהטקסט הנקי באמת יכיל רק אותיות ורווחים
            clean = "".join([c for c in str(v.clean_text) if c.isalpha() or c.isspace()])
            writer.writerow([v.book, v.chapter, v.verse, clean, v.text_with_nikkud])
            
    print("Export complete! File saved as tanakh_data.csv")

if __name__ == '__main__':
    export_to_csv()