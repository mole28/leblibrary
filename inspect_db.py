import os
import django

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

print("=== שדות קיימים במודל Book ===")
print([f.name for f in Book._meta.get_fields()])

print("\n=== בדיקת ספרים ושמות הקשרים ביניהם ===")
for b in Book.objects.all():
    print(f"\nספר: '{b.title}' (מזהה: {b.id})")
    # נבדוק אילו מאפיינים קיימים תחת הספר בעזרת dir()
    attributes = [attr for attr in dir(b) if 'chapter' in attr.lower() or 'section' in attr.lower() or 'article' in attr.lower()]
    print(f"   מאפיינים קשורים נמצאו: {attributes}")