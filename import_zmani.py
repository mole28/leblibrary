import os
import django
import re
from bs4 import BeautifulSoup

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zmani_book():
    book_title = "זמני המילה וברכותיה"
    
    book, _ = Book.objects.get_or_create(title=book_title)
    print(f"מעבד את הספר: {book.title}")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # הסרת אלמנטים מיותרים שיכולים ליצור התנגשויות
    for element in soup(["script", "style", "meta", "link", "form", "input", "button"]):
        element.decompose()

    # ניקוי פרקים וסעיפים קודמים של הספר למניעת כפילויות
    chapters_to_delete = Chapter.objects.filter(book=book)
    Section.objects.filter(chapter__in=chapters_to_delete).delete()
    chapters_to_delete.delete()
    print("נוקו פרקים וסעיפים ישנים.")

    full_text = str(soup)

    # פיצול הטקסט לפי מילת המפתח "סימן" (למשל: סימן א, סימן ב וכו')
    parts = re.split(r'(?i)(סימן\s+[א-ת]+(?:\s*–\s*[^<\n]+)?)', full_text)

    if len(parts) <= 1:
        # אם אין חלוקה לסימנים, ניצור פרק ברירת מחדל
        ch = Chapter.objects.create(book=book, title="זמני המילה וברכותיה", order=1)
        Section.objects.create(chapter=ch, title="תוכן הספר", content=full_text, order=1)
    else:
        # טיפול בחומר שקודם לסימן הראשון (פתח דבר, הקדמות)
        intro_content = parts[0]
        if intro_content.strip():
            intro_ch = Chapter.objects.create(book=book, title="פתח דבר והקדמה", order=1)
            Section.objects.create(chapter=intro_ch, title="פתח דבר", content=intro_content, order=1)

        # מעבר על כל סימן ויצירתו כפרק (מופיע מודגש בסרגל)
        ch_order = 2
        for i in range(1, len(parts), 2):
            siman_title = parts[i].strip()
            siman_body = parts[i+1] if i+1 < len(parts) else ""

            # יצירת הפרק (הסימן)
            chapter = Chapter.objects.create(
                book=book,
                title=siman_title,
                order=ch_order
            )

            # ניסיון לפצל את תוכן הסימן לסעיפים קטנים לפי אותיות (א., ב., ג. וכו')
            sub_parts = re.split(r'([ א-ת]\.\s+[^<\n]{2,50})', siman_body)

            if len(sub_parts) <= 1:
                # אם אין חלוקה פנימית לאותיות, נכניס את כל הסימן כסעיף יחיד תחתיו
                Section.objects.create(
                    chapter=chapter,
                    title=siman_title,
                    content=siman_body,
                    order=1
                )
            else:
                # טקסט מקדים לפני האות הראשונה אם קיים
                if sub_parts[0].strip():
                    Section.objects.create(
                        chapter=chapter,
                        title="הקדמה לסימן",
                        content=sub_parts[0],
                        order=1
                    )

                sec_order = 1
                for j in range(1, len(sub_parts), 2):
                    sec_title = sub_parts[j].strip()
                    sec_body = sub_parts[j+1] if j+1 < len(sub_parts) else ""

                    # יצירת סעיף (אות) תחת הסימן (מופיע לא מודגש בסרגל מתחת לסימן)
                    Section.objects.create(
                        chapter=chapter,
                        title=sec_title,
                        content=sec_body,
                        order=sec_order
                    )
                    sec_order += 1

            ch_order += 1

    print("הספר פוצץ והוכנס למסד הנתונים בהצלחה מלאה עם סימנים ואותיות!")

if __name__ == "__main__":
    import_zmani_book()