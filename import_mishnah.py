import os
import django
import urllib.request
import json
import re
from time import sleep

# הגדרת סביבת העבודה של ג'אנגו כדי שנוכל לגשת למסד הנתונים
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lab_library.settings')
django.setup()

from articles.models import TorahText

MISHNAH_TRACTATES = {
    "Berakhot": "ברכות", "Peah": "פאה", "Demai": "דמאי", "Kilayim": "כלאים", "Sheviit": "שביעית",
    "Terumot": "תרומות", "Maaserot": "מעשרות", "Maaser_Sheni": "מעשר שני", "Challah": "חלה", "Orlah": "ערלה", "Bikkurim": "ביכורים",
    "Shabbat": "שבת", "Eruvin": "עירובין", "Pesachim": "פסחים", "Shekalim": "שקלים", "Yoma": "יומא",
    "Sukkah": "סוכה", "Beitzah": "ביצה", "Rosh_Hashanah": "ראש השנה", "Taanit": "תענית", "Megillah": "מגילה",
    "Moed_Katan": "מועד קטן", "Chagigah": "חגיגה",
    "Yevamot": "יבמות", "Ketubot": "כתובות", "Nedarim": "נדרים", "Nazir": "נזיר", "Sotah": "סוטה", "Gittin": "גיטין", "Kiddushin": "קידושין",
    "Bava_Kamma": "בבא קמא", "Bava_Metzia": "בבא מציעא", "Bava_Batra": "בבא בתרא", "Sanhedrin": "סנהדרין", "Makkot": "מכות",
    "Shevuot": "שבועות", "Eduyot": "עדיות", "Avodah_Zarah": "עבודה זרה", "Pirkei_Avot": "אבות", "Horayot": "הוריות",
    "Zevachim": "זבחים", "Menachot": "מנחות", "Chullin": "חולין", "Bekhorot": "בכורות", "Arakhin": "ערכין",
    "Temurah": "תמורה", "Keritot": "כריתות", "Meilah": "מעילה", "Tamid": "תמיד", "Middot": "מדות", "Kinnim": "קינים",
    "Kelim": "כלים", "Oholot": "אהלות", "Negaim": "נגעים", "Parah": "פרה", "Tohorot": "טהרות", "Mikvaot": "מקואות",
    "Niddah": "נדה", "Makhshirin": "מכשירין", "Zavim": "זבים", "Tevul_Yom": "טבול יום", "Yadayim": "ידים", "Oktzin": "עוקצין"
}

def strip_html_and_nikkud(text):
    # מחיקת תגיות HTML
    clean = re.sub(r'<[^>]+>', '', text)
    # מחיקת ניקוד וטעמים
    clean = re.sub(r'[\u0591-\u05C7]', '', clean)
    # ניקוי רווחים מיותרים
    clean = " ".join(clean.split())
    return clean

print("🚀 Starting Mishnah text download from Sefaria...")

for en_name, he_name in MISHNAH_TRACTATES.items():
    print(f"Downloading {he_name}...")
    
    # מנסים שתי תבניות URL מקובלות בספריא (לפעמים זה עם הקידומת Mishnah ולפעמים בלי)
    urls_to_try = [
        f"https://www.sefaria.org/api/texts/Mishnah_{en_name}?context=0",
        f"https://www.sefaria.org/api/texts/{en_name}?context=0"
    ]
    
    success = False
    for url in urls_to_try:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            response = urllib.request.urlopen(req)
            data = json.loads(response.read().decode('utf-8'))
            
            if 'error' in data:
                continue
                
            chapters = data.get('he', [])
            if not chapters:
                continue
                
            # שומרים כל פרק ומשנה במסד הנתונים
            for chap_idx, chapter in enumerate(chapters):
                for mishnah_idx, mishnah_text in enumerate(chapter):
                    if not mishnah_text or not isinstance(mishnah_text, str):
                        continue
                    
                    text_with_nikkud = re.sub(r'<[^>]+>', '', mishnah_text) 
                    clean_text = strip_html_and_nikkud(mishnah_text)
                    
                    TorahText.objects.update_or_create(
                        book=he_name,
                        chapter=str(chap_idx + 1),
                        verse=str(mishnah_idx + 1),
                        defaults={
                            'text_with_nikkud': text_with_nikkud,
                            'clean_text': clean_text
                        }
                    )
            print(f"  ✅ Saved {he_name} successfully.")
            success = True
            sleep(0.5)  # המתנה קטנה כדי לא להעמיס על השרתים של ספריא
            break
        except Exception as e:
            pass
            
    if not success:
        print(f"  ❌ Failed to download {he_name}. Check tractate name mapping.")

print("🎉 Finished importing all Mishnayot!")