import os
import django
import re

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book

def fix_footnotes():
    print("מתחיל בהתאמת פורמט ההערות בספר 'זמני המילה וברכותיה' לפורמט של שאר הספרים...")
    
    try:
        book = Book.objects.get(id=84)
    except Book.DoesNotExist:
        print("שגיאה: ספר עם ID 84 לא נמצא!")
        return

    total_fixed = 0

    for chapter in book.chapters.all():
        for section in chapter.sections.all():
            if not section.content:
                continue
                
            content = section.content
            original_content = content

            # 1. המרת ההפניות בגוף הטקסט (למשל מ-fnref-1 ל-_ftnref1)
            # מתאים את הפורמט לזה של הספר השני שעובד מעולה
            def replace_ref(match):
                num = match.group(1)
                # שומר על מבנה ה-title והטולטיפ אם קיים, ומחזיר את המחלקה והשמות המקוריים
                return f'<a class="sdfootnoteanc" name="_ftnref{num}" href="#_ftn{num}" title=""><u>[{num}]</u></a>'

            content = re.sub(r'<sup[^>]*><a[^>]*href="#fn-(\d+)"[^>]*>(.*?)</a></sup>', replace_ref, content)
            content = re.sub(r'<a[^>]*href="#fn-(\d+)"[^>]*>\[?(\d+)\]?</a>', replace_ref, content)

            # 2. המרת רשימת ההערות בסוף (למשל מ-id="fn-1" ל-id="_ftn1")
            def replace_fn_item(match):
                num = match.group(1)
                return f'<li id="_ftn{num}">'

            content = re.sub(r'<li id="fn-(\d+)">', replace_fn_item, content)

            # אם בוצע שינוי, נשמור את הסעיף מחדש במסד הנתונים
            if content != original_content:
                section.content = content
                section.save()
                total_fixed += 1

    print(f"התיקון הסתיים בהצלחה! עודכנו {total_fixed} סעיפים בספר. כעת ההפניות והטולטיפים יפעלו בדיוק כמו בשאר הספרים.")

if __name__ == '__main__':
    fix_footnotes()