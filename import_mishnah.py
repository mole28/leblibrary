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

MISHNAH_TRACTATES = {
    "ברכות": ["Berakhot"], "פאה": ["Peah"], "דמאי": ["Demai"], "כלאים": ["Kilayim"], "שביעית": ["Sheviit"],
    "תרומות": ["Terumot"], "מעשרות": ["Ma'aserot", "Maaserot", "Maasrot"], "מעשר שני": ["Ma'aser Sheni", "Maaser Sheni"], 
    "חלה": ["Challah"], "ערלה": ["Orlah"], "ביכורים": ["Bikkurim"],
    
    "שבת": ["Shabbat"], "עירובין": ["Eruvin", "'Eruvin", "Erubin"], "פסחים": ["Pesachim"], "שקלים": ["Shekalim"], "יומא": ["Yoma"],
    "סוכה": ["Sukkah"], "ביצה": ["Beitzah"], "ראש השנה": ["Rosh Hashanah"], "תענית": ["Taanit"], "מגילה": ["Megillah", "Megilla"],
    "מועד קטן": ["Moed Katan"], "חגיגה": ["Chagigah"],
    
    "יבמות": ["Yevamot"], "כתובות": ["Ketubot"], "נדרים": ["Nedarim"], "נזיר": ["Nazir"], "סוטה": ["Sotah"], "גיטין": ["Gittin"], "קידושין": ["Kiddushin"],
    
    "בבא קמא": ["Bava Kamma"], "בבא מציעא": ["Bava Metzia"], "בבא בתרא": ["Bava Batra"], "סנהדרין": ["Sanhedrin"], "מכות": ["Makkot"],
    "שבועות": ["Shevuot"], "עדיות": ["Eduyot", "Eduyyot", "Ediyot"], "עבודה זרה": ["Avodah Zarah"], "אבות": ["Pirkei Avot", "Avot"], "הוריות": ["Horayot"],
    
    "זבחים": ["Zevachim"], "מנחות": ["Menachot"], "חולין": ["Chullin"], "בכורות": ["Bekhorot", "Bechorot"], "ערכין": ["Arakhin"],
    "תמורה": ["Temurah"], "כריתות": ["Keritot"], "מעילה": ["Meilah"], "תמיד": ["Tamid"], "מדות": ["Middot", "Midot"], "קינים": ["Kinnim", "Kinim"],
    
    "כלים": ["Kelim"], "אהלות": ["Oholot", "Ohalot"], "נגעים": ["Negaim"], "פרה": ["Parah"], "טהרות": ["Tohorot", "Tehorot"], "מקואות": ["Mikvaot", "Mikva'ot"],
    "נדה": ["Niddah"], "מכשירין": ["Makhshirin"], "זבים": ["Zavim"], "טבול יום": ["Tevul Yom", "Tevool Yom"], "ידים": ["Yadayim"], "עוקצין": ["Uktzin", "Oktzin", "Uktsin"]
}

def strip_html_and_nikkud(text):
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'[\u0591-\u05C7]', '', clean)
    clean = " ".join(clean.split())
    return clean

print("🚀 Starting Mishnah text download for missing tractates...")

for he_name, en_names in MISHNAH_TRACTATES.items():
    # דילוג על מסכתות שכבר ירדו בהצלחה!
    if TorahText.objects.filter(book=he_name).exists():
        print(f"  ✅ {he_name} already exists in database. Skipping...")
        continue
        
    print(f"Downloading {he_name}...")
    
    success = False
    for en_name in en_names:
        encoded_name = urllib.parse.quote(en_name)
        urls_to_try = [
            f"https://www.sefaria.org/api/texts/Mishnah_{encoded_name}?context=0",
            f"https://www.sefaria.org/api/texts/{encoded_name}?context=0"
        ]
        
        for url in urls_to_try:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                response = urllib.request.urlopen(req, timeout=10)
                data = json.loads(response.read().decode('utf-8'))
                
                if 'error' in data:
                    continue
                    
                chapters = data.get('he', [])
                if not chapters:
                    continue
                    
                # בדיקה אם קיבלנו מערך חד מימדי (פרק בודד) או דו מימדי
                if chapters and isinstance(chapters[0], str):
                    for mishnah_idx, mishnah_text in enumerate(chapters):
                        if not mishnah_text or not isinstance(mishnah_text, str): continue
                        text_with_nikkud = re.sub(r'<[^>]+>', '', mishnah_text) 
                        clean_text = strip_html_and_nikkud(mishnah_text)
                        TorahText.objects.update_or_create(book=he_name, chapter="1", verse=str(mishnah_idx + 1), defaults={'text_with_nikkud': text_with_nikkud, 'clean_text': clean_text})
                else:
                    for chap_idx, chapter in enumerate(chapters):
                        for mishnah_idx, mishnah_text in enumerate(chapter):
                            if not mishnah_text or not isinstance(mishnah_text, str): continue
                            text_with_nikkud = re.sub(r'<[^>]+>', '', mishnah_text) 
                            clean_text = strip_html_and_nikkud(mishnah_text)
                            TorahText.objects.update_or_create(book=he_name, chapter=str(chap_idx + 1), verse=str(mishnah_idx + 1), defaults={'text_with_nikkud': text_with_nikkud, 'clean_text': clean_text})
                
                print(f"  ✅ Saved {he_name} successfully.")
                success = True
                sleep(1) # המתנה של שניה למניעת חסימה של ספריא
                break
            except Exception as e:
                pass
                
        if success:
            break
            
    if not success:
        print(f"  ❌ Failed to download {he_name}.")

print("🎉 Finished importing all Mishnayot!")