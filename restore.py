import os
import django
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from articles.models import Section

def restore_book_45():
    print("מתחיל שחזור... מחזיר את הטקסט המקורי ל-58 הסעיפים כדי לבטל את הבלבול!")
    
    excluded_substrings = [
        "משכ שמזה שהשווה", "הוא כתב שאין התלמוד", "לדבריו עולה שאנו", "לא מובן מה הראיה",
        "שברכת חתנים שייכת", "שפח נקראים דווקא", "תוקף הפח שייך", "במקום שאנו אומרים",
        "כפי שראינו יש הרבה", "הכלל שאין אומרים סבל", "אם דעתו שרק כשמברכים", "למה כאשר אין יין",
        "האם במקום שנוהגים לברך", "השוע כתב הדברים", "בבי ובשוע לא הוסיף", "בשביל הפח מספיק",
        "דווקא אדם חדש", "אצ שהחתן ירבה", "ניתן לברך אף", "האדם נחשב פח", "בשבת, יוט (אף יוט",
        "כפי שהתבאר למעלה", "מניין לחדש שיש", "דווקא פנים חדשות הגורמים", "בשבת וביוט מברכים",
        "מספיק אדם אחד בשביל", "לנישואי אלמנה או גרושה", "אסור מדרבנן לשאת אישה"
    ]
    
    file_path = 'book_content.txt'
    if not os.path.exists(file_path):
        print("שגיאה: הקובץ book_content.txt לא נמצא בתיקייה!")
        return

    db_sections = list(Section.objects.filter(chapter__book_id=45).order_by('chapter__order', 'order'))
    section_index = 0
    current_section = None
    section_content = []
    current_chapter_exists = False

    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line: continue
            line = re.sub(r'^\d+\s*\|?\s*', '', line).strip()
            if not line: continue

            if line.startswith("סימן ") or line in ["פתח דבר", "הקדמה", "קונטרס ראשון גדרי שליחות", "קונטרס שני גדר בפני נכתב ובפני נחתם", "דינים העולים מהספר"]:
                if current_section and section_content:
                    current_section.content = "<p>" + "</p><p>".join(section_content) + "</p>"
                    current_section.save()
                    section_content = []
                current_chapter_exists = True
                current_section = None
                continue

            clean_line = line.replace('"', '').replace("'", "").replace("״", "").replace("׳", "")
            match = re.compile(r'^([א-ת]{1,2})\.\s+(.*)').match(line)
            is_explicitly_excluded = any(sub in clean_line for sub in excluded_substrings)
            is_valid_heading = match and (len(line.split()) <= 14) and not is_explicitly_excluded

            if is_valid_heading:
                if current_chapter_exists:
                    if current_section and section_content:
                        current_section.content = "<p>" + "</p><p>".join(section_content) + "</p>"
                        current_section.save()
                    section_content = []
                    
                    if section_index < len(db_sections):
                        current_section = db_sections[section_index]
                        section_index += 1
                    continue

            if current_section:
                section_content.append(line)
            elif current_chapter_exists:
                if section_index < len(db_sections):
                    current_section = db_sections[section_index]
                    section_index += 1
                    section_content.append(line)

    if current_section and section_content:
        current_section.content = "<p>" + "</p><p>".join(section_content) + "</p>"
        current_section.save()

    print(f"השחזור עבר בהצלחה! {section_index} סעיפים נדרסו חזרה לטקסט המקורי והנקי שלהם.")

if __name__ == '__main__':
    restore_book_45()