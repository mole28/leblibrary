import os
import django
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings') 
django.setup()

from articles.models import Book, Chapter, Section

def clean_for_search(text):
    return text.replace('"', '').replace("'", "").replace("״", "").replace("׳", "")

def import_book_from_text(file_path):
    Book.objects.filter(title="גדרי החופה וברכותיה").delete()
    
    book = Book.objects.create(
        title="גדרי החופה וברכותיה",
        author="משה לייבוביץ"
    )
    
    current_chapter = None
    current_section = None
    section_content = []
    
    chapter_order = 1
    section_order = 1

    section_pattern = re.compile(r'^([א-ת]{1,2})\.\s+(.*)')

    excluded_substrings = [
        "משכ שמזה שהשווה",
        "הוא כתב שאין התלמוד",
        "לדבריו עולה שאנו",
        "לא מובן מה הראיה",
        "שברכת חתנים שייכת",
        "שפח נקראים דווקא",
        "תוקף הפח שייך",
        "במקום שאנו אומרים",
        "כפי שראינו יש הרבה",
        "הכלל שאין אומרים סבל",
        "אם דעתו שרק כשמברכים",
        "למה כאשר אין יין",
        "האם במקום שנוהגים לברך",
        "השוע כתב הדברים",
        "בבי ובשוע לא הוסיף",
        "בשביל הפח מספיק",
        "דווקא אדם חדש",
        "אצ שהחתן ירבה",
        "ניתן לברך אף",
        "האדם נחשב פח",
        "בשבת, יוט (אף יוט",
        "כפי שהתבאר למעלה",
        "מניין לחדש שיש",
        "דווקא פנים חדשות הגורמים",
        "בשבת וביוט מברכים",
        "מספיק אדם אחד בשביל",
        "לנישואי אלמנה או גרושה",
        "אסור מדרבנן לשאת אישה"
    ]

    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            
            line = re.sub(r'^\d+\s*\|?\s*', '', line).strip()
            
            if not line:
                continue

            if line.startswith("סימן ") or line in ["פתח דבר", "הקדמה", "קונטרס ראשון גדרי שליחות", "קונטרס שני גדר בפני נכתב ובפני נחתם", "דינים העולים מהספר"]:
                if current_section and section_content:
                    current_section.content = "<p>" + "</p><p>".join(section_content) + "</p>"
                    current_section.save()
                    section_content = []

                current_chapter = Chapter.objects.create(
                    book=book,
                    title=line,
                    order=chapter_order
                )
                chapter_order += 1
                section_order = 1
                current_section = None
                continue

            clean_line = clean_for_search(line)
            match = section_pattern.match(line)
            
            is_explicitly_excluded = any(sub in clean_line for sub in excluded_substrings)
            
            words_count = len(line.split())
            is_valid_heading = match and (words_count <= 14) and not is_explicitly_excluded
            
            if is_valid_heading:
                if current_chapter:
                    if current_section and section_content:
                        current_section.content = "<p>" + "</p><p>".join(section_content) + "</p>"
                        current_section.save()
                    
                    section_content = []
                    current_section = Section.objects.create(
                        chapter=current_chapter,
                        title=line,
                        order=section_order
                    )
                    section_order += 1
                    continue
            
            if current_section:
                section_content.append(line)
            elif current_chapter:
                current_section = Section.objects.create(
                    chapter=current_chapter,
                    title="מבוא / פתיחה",
                    order=section_order
                )
                section_order += 1
                section_content.append(line)

        if current_section and section_content:
            current_section.content = "<p>" + "</p><p>".join(section_content) + "</p>"
            current_section.save()

if __name__ == '__main__':
    import_book_from_text('book_content.txt')