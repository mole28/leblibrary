import os
import django
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings') 
django.setup()

from articles.models import Book, Chapter, Section

def clean_quotes(text):
    return text.replace('"', '').replace("'", "").replace("״", "").replace("׳", "").strip()

def import_appendix_b(file_path):
    title_with_br = "נספח ב' לספר גדרי החופה וברכותיה:<br>גדרי תקנת - בפני נכתב ובפני נחתם"
    
    Book.objects.filter(title=title_with_br).delete()
    Book.objects.filter(title="נספח ב' לספר גדרי החופה וברכותיה: גדרי תקנת - בפני נכתב ובפני נחתם").delete()
    
    book = Book.objects.create(
        title=title_with_br,
        author="משה לייבוביץ"
    )
    
    current_chapter = None
    current_section = None
    section_content = []
    
    chapter_order = 1
    section_order = 1

    section_pattern = re.compile(r'^([א-ת]{1,2})\.\s+(.*)')

    # --- רשימת כותרות מיוחדות שיוכרו כסעיפים (ללא מרכאות) ---
    special_exact_titles = [
        "גדר תקנת בפני נכתב ובפני נחתם",
        "מבוא",
        "שיטת רשי",
        "שיטת הרמבן והריטבא",
        "שיטת התוס והראש",
        "סיכום השיטות"
    ]

    # --- רשימת החרגות (לא יוכרו ככותרת, אלא כטקסט רגיל) ---
    excluded_prefixes = [
        "ב. מה ההפרש בין אם אין זמן"
    ]

    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            
            line = re.sub(r'^\d+\s*\|?\s*', '', line).strip()
            
            if not line:
                continue

            if line.startswith("קונטרס ") or line.startswith("נספח ") or line.startswith("סימן "):
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

            if not current_chapter:
                current_chapter = Chapter.objects.create(
                    book=book,
                    title="תוכן הנספח",
                    order=chapter_order
                )
                chapter_order += 1

            clean_line_no_colon = clean_quotes(line).rstrip(':').strip()
            is_special_title = clean_line_no_colon in special_exact_titles

            is_explicitly_excluded = any(clean_quotes(line).startswith(clean_quotes(prefix)) for prefix in excluded_prefixes)

            match = section_pattern.match(line)
            words_count = len(line.split())
            
            # אם זו כותרת מיוחדת - זה נכנס מיד. אחרת, נבדוק שזה תבנית של סעיף (עד 14 מילים) ולא מוחרג.
            is_valid_heading = is_special_title or (match and (words_count <= 14) and not is_explicitly_excluded)
            
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
                    title="פתיחה",
                    order=section_order
                )
                section_order += 1
                section_content.append(line)

        if current_section and section_content:
            current_section.content = "<p>" + "</p><p>".join(section_content) + "</p>"
            current_section.save()

if __name__ == '__main__':
    import_appendix_b('appendix_b_content.txt')