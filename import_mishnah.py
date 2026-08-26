import os
import django
import urllib.request
import urllib.parse
import json
import re
from time import sleep

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lab_library.settings')
django.setup()

from articles.models import TorahText

# רשימה מלאה של כל 63 המסכתות והשמות האפשריים שלהן בספריא באנגלית
ALL_MISHNAH_TRACTATES = {
    "ברכות": ["Berakhot"], "פאה": ["Peah"], "דמאי": ["Demai"], "כלאים": ["Kilayim"], "שביעית": ["Sheviit"],
    "תרומות": ["Terumot"], "מעשרות": ["Maaserot", "Ma'aserot"], "מעשר שני": ["Maaser Sheni", "Ma'aser Sheni"], 
    "חלה": ["Challah"], "ערלה": ["Orlah"], "ביכורים": ["Bikkurim"],
    
    "שבת": ["Shabbat"], "עירובין": ["Eruvin", "Erubin"], "פסחים": ["Pesachim"], "שקלים": ["Shekalim"], "יומא": ["Yoma"],
    "סוכה": ["Sukkah"], "ביצה": ["Beitzah"], "ראש השנה": ["Rosh Hashanah"], "תענית": ["Taanit"], "מגילה": ["Megillah"],
    "מועד קטן": ["Moed Katan"], "חגיגה": ["Chagigah"],
    
    "יבמות": ["Yevamot"], "כתובות": ["Ketubot"], "נדרים": ["Nedarim"], "נזיר": ["Nazir"], "סוטה": ["Sotah"], "גיטין": ["Gittin"], "קידושין": ["Kiddushin"],
    
    "בבא קמא": ["Bava Kamma"], "בבא מציעא": ["Bava Metzia"], "בבא בתרא": ["Bava Batra"], "סנהדרין": ["Sanhedrin"], "מכות": ["Makkot"],
    "שבועות": ["Shevuot"], "עדיות": ["Eduyot", "Ediyot"], "עבודה זרה": ["Avodah Zarah"], "אבות": ["Pirkei Avot", "Avot"], "הוריות": ["Horayot"],
    
    "זבחים": ["Zevachim"], "מנחות": ["Menachot"], "חולין": ["Chullin"], "בכורות": ["Bekhorot"], "ערכין": ["Arakhin"],
    "תמורה": ["Temurah"], "כריתות": ["Keritot"], "מעילה": ["Meilah"], "תמיד": ["Tamid"], "מדות": ["Middot"], "קינים": ["Kinnim"],
    
    "כלים": ["Kelim"], "אהלות": ["Oholot"], "נגעים": ["Negaim"], "פרה": ["Parah"], "טהרות": ["Tohorot_(Mishnah)", "Taharot"], 
    "מקואות": ["Mikvaot"], "נדה": ["Niddah"], "מכשירין": ["Makhshirin"], "זבים": ["Zavim"], "טבול יום": ["Tevul Yom"], "ידים": ["Yadayim"], "עוקצין": ["Uktzin", "Oktzin"]
}

def clean_text_func(text):
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'[\u0591-\u05C7]', '', clean)
    return " ".join(clean.split())

print("🚀 FORCE IMPORTING ALL 63 MISHNAH TRACTATES...")

for he_name, en_list in ALL_MISHNAH_TRACTATES.items():
    print(f"Processing tractate: {he_name}...")
    success = False
    
    for en_name in en_list:
        encoded = urllib.parse.quote(en_name)
        urls = [
            f"https://www.sefaria.org/api/texts/Mishnah_{encoded}?context=0",
            f"https://www.sefaria.org/api/texts/{encoded}?context=0"
        ]
        
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                response = urllib.request.urlopen(req, timeout=15)
                data = json.loads(response.read().decode('utf-8'))
                
                if 'error' in data:
                    continue
                    
                chapters = data.get('he', [])
                if not chapters:
                    continue
                
                # מחיקת הנתונים הישנים של המסכת הזו כדי למנוע כפילויות או זבל
                TorahText.objects.filter(book=he_name).delete()
                
                if isinstance(chapters[0], str):
                    for m_idx, m_text in enumerate(chapters):
                        if m_text and isinstance(m_text, str):
                            TorahText.objects.create(
                                book=he_name,
                                chapter="1",
                                verse=str(m_idx + 1),
                                text_with_nikkud=re.sub(r'<[^>]+>', '', m_text),
                                clean_text=clean_text_func(m_text)
                            )
                else:
                    for c_idx, chap in enumerate(chapters):
                        for m_idx, m_text in enumerate(chap):
                            if m_text and isinstance(m_text, str):
                                TorahText.objects.create(
                                    book=he_name,
                                    chapter=str(c_idx + 1),
                                    verse=str(m_idx + 1),
                                    text_with_nikkud=re.sub(r'<[^>]+>', '', m_text),
                                    clean_text=clean_text_func(m_text)
                                )
                print(f"  --> SUCCESSFULLY SAVED: {he_name}")
                success = True
                sleep(0.5)
                break
            except Exception as e:
                pass
        if success:
            break
    if not success:
        print(f"  --> FAILED TO DOWNLOAD: {he_name}")

print("🎉 DONE! All Mishnayot forced into database.")