import os
import django
import re

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zmani_book():
    book_title = "זמני המילה וברכותיה"
    
    book = Book.objects.filter(title=book_title).first()
    if not book:
        book = Book.objects.create(title=book_title)
        print(f"נוצר ספר חדש: {book.title}")
    else:
        print(f"נמצא ספר קיים: {book.title}")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # ניקוי פרקים וסעיפים קודמים
    chapters_to_delete = Chapter.objects.filter(book=book)
    Section.objects.filter(chapter__in=chapters_to_delete).delete()
    chapters_to_delete.delete()
    print("נוקו פרקים וסעיפים ישנים.")

    # חלוקה חכמה לפי זיהוי "סימן" בטקסט (כותרות או פסקאות)
    # נחלק את ה-HTML לחלקים לפי מילת המפתח "סימן"
    parts = re.split(r'(?i)(סימן\s+[א-ת\-\s]+)', html_content)
    
    if len(parts) <= 1:
        # אם פאנדוק לא פירק לפי כותרות ברורות, ניצור פרק מבוא ופרקים כלליים
        print("לא נמצאו סימנים מובהקים ברגולר, יוצר חלוקה ראשונית...")
        ch = Chapter.objects.create(book=book, title="פתח דבר וסקירה כללית", order=1)
        Section.objects.create(chapter=ch, title="תוכן הספר", content=html_content, order=1)
    else:
        # יצירת מבוא למה שקורה לפני הסימן הראשון
        intro_content = parts[0]
        if intro_content.strip():
            intro_ch = Chapter.objects.create(book=book, title="הקדמה ופתח דבר", order=1)
            Section.objects.create(chapter=intro_ch, title="פתח דבר", content=intro_content, order=1)
        
        # מעבר על הסימנים שנמצאו
        ch_order = 2
        for i in range(1, len(parts), 2):
            siman_title = parts[i].strip()
            siman_body = parts[i+1] if i+1 < len(parts) else ""
            
            # יצירת פרק לכל סימן (שיופיע מודגש בסרגל)
            chapter = Chapter.objects.create(
                book=book,
                title=siman_title,
                order=ch_order
            )
            
            # יצירת סעיף תחת הסימן (שיופיע רגיל בסרגל)
            Section.objects.create(
                chapter=chapter,
                title=f"תוכן {siman_title}",
                content=siman_body,
                order=1
            )
            ch_order += 1

    print("הספר פוצץ והוכנס למסד הנתונים בהצלחה רבה!")

if __name__ == "__main__":
    import_zmani_book()