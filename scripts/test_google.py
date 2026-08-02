import os
import urllib.request
import json
import concurrent.futures
from dotenv import load_dotenv

# פקודה זו קוראת את כל המשתנים ששמת בקובץ ה-.env ומכניסה אותם לסביבה
load_dotenv()

# כאן אנחנו שולפים את המפתח בבטחה. 
# ודא שבתוך קובץ ה-.env קראת למשתנה GOOGLE_API_KEY
API_KEY = os.getenv("GOOGLE_API_KEY")

if not API_KEY:
    print("שגיאה: לא נמצא מפתח API! ודא שיש קובץ .env עם המשתנה GOOGLE_API_KEY.")
    exit()

def check_single_model(target_model):
    url = f"https://generativelanguage.googleapis.com/v1beta/{target_model}:generateContent?key={API_KEY}"
    payload = {"contents": [{"parts": [{"text": "שלום"}]}]}
    data_bytes = json.dumps(payload).encode('utf-8')
    
    try:
        req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5)
        return f"[V] {target_model:<35} - תקין ועובד!"
    except Exception:
        return None

if __name__ == "__main__":
    print("1. מושך את רשימת המודלים המלאה מהשרת של גוגל...")
    try:
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={API_KEY}"
        req = urllib.request.Request(list_url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req)
        models_data = json.loads(response.read().decode('utf-8'))
        
        models_to_test = [m['name'] for m in models_data.get('models', []) if 'generateContent' in m.get('supportedGenerationMethods', [])]
        
        print(f"2. נמצאו {len(models_to_test)} מודלים. מבצע ירי מקבילי לכולם כדי למצוא את התקינים...\n" + "-"*50)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            results = executor.map(check_single_model, models_to_test)
            for res in results:
                if res:
                    print(res)
                    
    except Exception as e:
        print(f"שגיאה בשליפת הרשימה הראשונית: {e}")