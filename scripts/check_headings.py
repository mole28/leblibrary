import os
import django
from bs4 import BeautifulSoup

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

with open("zmani_clean.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

print("--- מחפש סימנים בקובץ ---")
count = 0
for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'p', 'strong']):
    text = tag.get_text().strip()
    if 'סימן' in text and len(text) < 50:
        print(f"[{tag.name}] {text}")
        count += 1
        if count > 15:  # נדפיס את ה-15 הראשונים כדי לראות את המבנה
            break