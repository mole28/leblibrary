import google.generativeai as genai

# המפתח שלך
genai.configure(api_key="AQ.Ab8RN6KSDvqhRk10R9g9M3hmz5m-RN5qpsZSFaHzbtBhtTz-uQ")

print("מתחיל בדיקת תקשורת מול גוגל...")

try:
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content("שלום, האם אתה עובד?")
    print("הכל עובד מעולה! התשובה מגוגל:")
    print(response.text)
except Exception as e:
    print("\n--- הנה השגיאה האמיתית שגוגל מחזירה לנו: ---")
    print(e)