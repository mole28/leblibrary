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
        ('Genesis', 'בראשית'), ('Exodus', 'שמות'), ('Leviticus', 'ויקרא'),
        ('Numbers', 'במדבר'), ('Deuteronomy', 'דברים'),
        
        # נביאים
        ('Joshua', 'יהושע'), ('Judges', 'שופטים'), ('I Samuel', 'שמואל א'),
        ('II Samuel', 'שמואל ב'), ('I Kings', 'מלכים א'), ('II Kings', 'מלכים ב'),
        ('Isaiah', 'ישעיהו'), ('Jeremiah', 'ירמיהו'), ('Ezekiel', 'יחזקאל'),
        ('Hosea', 'הושע'), ('Joel', 'יואל'), ('Amos', 'עמוס'), ('Obadiah', 'עובדיה'),
        ('Jonah', 'יונה'), ('Micah', 'מיכה'), ('Nahum', 'נחום'), ('Habakkuk', 'חבקוק'),
        ('Zephaniah', 'צפניה'), ('Haggai', 'חגי'), ('Zechariah', 'זכריה'),
        ('Malachi', 'מלאכי'),
        
        # כתובים
        ('Psalms', 'תהילים'), ('Proverbs', 'משלי'), ('Job', 'איוב'),
        ('Song of Songs', 'שיר השירים'), ('Ruth', 'רות'), ('Lamentations', 'איכה'),
        ('Ecclesiastes', 'קהלת'), ('Esther', 'אסתר'), ('Daniel', 'דניאל'),
        ('Ezra', 'עזרא'), ('Nehemiah', 'נחמיה'), ('I Chronicles', 'דברי הימים א'),
        ('II Chronicles', 'דברי הימים ב')
    ]
    
    print('מנקה נתונים ישנים מהמאגר כדי למנוע כפילויות...')
    TorahText.objects.all().delete()
    
    print('מתחיל בהורדת כל ספרי התנ"ך מספריא (Sefaria) - פרק אחרי פרק...')
    
    total_saved = 0
    for eng_name, heb_name in tanakh_books:
        print(f'מוריד את ספר {heb_name}...')
        chap_idx = 1
        book_saved = 0
        
        while True:
            # מבקשים פרק ספציפי (לדוגמה: Genesis 1, Genesis 2)
            encoded_eng_name = urllib.parse.quote(f"{eng_name} {chap_idx}")
            url = f'https://www.sefaria.org/api/texts/{encoded_eng_name}?context=0'
            
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            try:
                response = urllib.request.urlopen(req)
                data = json.loads(response.read().decode('utf-8'))
                verses = data.get('he', [])
                
                # אם הגענו לפרק ריק, הספר הסתיים
                if not verses or 'error' in data:
                    break
                    
                for verse_idx, verse_text in enumerate(verses):
                    if not isinstance(verse_text, str):
                        continue
                        
                    nikkud_text = verse_text
                    cleaned = clean_hebrew_text(verse_text)
                    
                    if not cleaned:
                        continue
                        
                    TorahText.objects.create(
                        book=heb_name,
                        chapter=str(chap_idx),
                        verse=str(verse_idx + 1),
                        text_with_nikkud=nikkud_text,
                        clean_text=cleaned
                    )
                    book_saved += 1
                    total_saved += 1
                    
                chap_idx += 1
                time.sleep(0.1) # מנוחה קלה כדי לא לחסום את שרתי ספריא
                
            except Exception as e:
                # קבלת שגיאה (כמו 404 או 400) אומרת שהפרק לא קיים - הספר הסתיים
                break
                
        print(f'-> נשמרו {book_saved} פסוקים לספר {heb_name}.')
        
    print(f'\nסיום! סך הכל נשמרו {total_saved} פסוקים מכל ספרי התנ"ך במסד הנתונים.')

if __name__ == '__main__':
    fetch_all_tanakh()