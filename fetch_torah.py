import os
import django
import urllib.request
import urllib.parse
import json
import re
import time

# הגדרת סביבת Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import TorahText

def clean_hebrew_text(text):
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'[^א-ת]', '', text)
    return clean

def fetch_all_tanakh():
    tanakh_books = [
        # תורה
        ('Genesis', 'בראשית'),
        ('Exodus', 'שמות'),
        ('Leviticus', 'ויקרא'),
        ('Numbers', 'במדבר'),
        ('Deuteronomy', 'דברים'),
        
        # נביאים
        ('Joshua', 'יהושע'),
        ('Judges', 'שופטים'),
        ('I Samuel', 'שמואל א'),
        ('II Samuel', 'שמואל ב'),
        ('I Kings', 'מלכים א'),
        ('II Kings', 'מלכים ב'),
        ('Isaiah', 'ישעיהו'),
        ('Jeremiah', 'ירמיהו'),
        ('Ezekiel', 'יחזקאל'),
        ('Hosea', 'הושע'),
        ('Joel', 'יואל'),
        ('Amos', 'עמוס'),
        ('Obadiah', 'עובדיה'),
        ('Jonah', 'יונה'),
        ('Micah', 'מיכה'),
        ('Nahum', 'נחום'),
        ('Habakkuk', 'חבקוק'),
        ('Zephaniah', 'צפניה'),
        ('Haggai', 'חגי'),
        ('Zechariah', 'זכריה'),
        ('Malachi', 'מלאכי'),
        
        # כתובים
        ('Psalms', 'תהילים'),
        ('Proverbs', 'משלי'),
        ('Job', 'איוב'),
        ('Song of Songs', 'שיר השירים'),
        ('Ruth', 'רות'),
        ('Lamentations', 'איכה'),
        ('Ecclesiastes', 'קהלת'),
        ('Esther', 'אסתר'),
        ('Daniel', 'דניאל'),
        ('Ezra', 'עזרא'),
        ('Nehemiah', 'נחמיה'),
        ('I Chronicles', 'דברי הימים א'),
        ('II Chronicles', 'דברי הימים ב')
    ]
    
    print('מתחיל בהורדת כל ספרי התנך מספריא (Sefaria)...')
    
    total_saved = 0
    for eng_name, heb_name in tanakh_books:
        print(f'מוריד את ספר {heb_name}...')
        
        # קידוד השם באנגלית כך שרווחים יהפכו ל-%20 באופן תקין ל-URL
        encoded_eng_name = urllib.parse.quote(eng_name)
        url = f'https://www.sefaria.org/api/texts/{encoded_eng_name}?context=0'
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            response = urllib.request.urlopen(req)
            data = json.loads(response.read().decode('utf-8'))
            chapters = data.get('he', [])
            
            if chapters and isinstance(chapters[0], str):
                chapters = [chapters]
                
            for chap_idx, chapter in enumerate(chapters):
                if not isinstance(chapter, list):
                    continue
                for verse_idx, verse_text in enumerate(chapter):
                    if not isinstance(verse_text, str):
                        continue
                        
                    nikkud_text = verse_text
                    cleaned = clean_hebrew_text(verse_text)
                    
                    if not cleaned:
                        continue
                        
                    TorahText.objects.update_or_create(
                        book=heb_name,
                        chapter=str(chap_idx + 1),
                        verse=str(verse_idx + 1),
                        defaults={
                            'text_with_nikkud': nikkud_text,
                            'clean_text': cleaned
                        }
                    )
                    total_saved += 1
            print(f'ספר {heb_name} נשמר בהצלחה.')
            time.sleep(0.3)
            
        except Exception as e:
            print(f'שגיאה בהורדת {heb_name}: {e}')
            
    print(f'סיום! סך הכל נשמרו {total_saved} פסוקים מכל ספרי התנך במסד הנתונים.')

if __name__ == '__main__':
    fetch_all_tanakh()