import os
import django
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings') 
django.setup()

from articles.models import Book, Chapter, Section

def clean_quotes(text):
    return text.replace('"', '').replace("'", "").replace("״", "").replace("׳", "").strip()

def import_appendix_from_text(file_path):
    Book.objects.filter(title="הנספחים לספרי גדרי החופה וברכותיה").delete()
    Book.objects.filter(title="נספח א' לספר גדרי החופה וברכותיה: גדרי שליחות").delete()
    
    book = Book.objects.create(
        title="נספח א' לספר גדרי החופה וברכותיה: גדרי שליחות",
        author="משה לייבוביץ"
    )
    
    current_chapter = None
    current_section = None
    section_content = []
    
    chapter_order = 1
    section_order = 1

    section_pattern = re.compile(r'^([א-ת]{1,2})\.\s+(.*)')

    special_exact_titles = [
        "שיטת רשי",
        "שיטת הרמבן והריטבא",
        "שיטת התוס והראש",
        "סיכומא דמילתא"
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

            clean_line = clean_quotes(line)
            clean_line_no_colon = clean_line.rstrip(':')
            
            is_special_title = clean_line_no_colon in special_exact_titles
            match = section_pattern.match(line)
            is_excluded = clean_line.startswith("א. לתוס ולראש") or clean_line.startswith("ב. לתוס ולראש")

            if (match and not is_excluded) or is_special_title:
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
                    title="מבוא",
                    order=section_order
                )
                section_order += 1
                section_content.append(line)

        if current_section and section_content:
            current_section.content = "<p>" + "</p><p>".join(section_content) + "</p>"
            current_section.save()

if __name__ == '__main__':
    import_appendix_from_text('appendix_content.txt')