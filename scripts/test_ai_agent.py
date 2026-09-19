import pytest
import json
import io
from unittest.mock import patch
from django.urls import reverse
from articles.models import Article

@pytest.mark.django_db
@patch('urllib.request.urlopen')  # מיירטים את שליחת ה-HTTP הישירה של הפונקציה
def test_ai_agent_returns_mocked_response(mock_urlopen, client):
    # 1. יוצרים מאמר דמה במסד הנתונים כדי שמנגנון ה-RAG ימצא חומרים
    Article.objects.create(
        title="מאמר בדיקה על הלכה ותלמוד",
        content="תוכן בדיקה עבור הסוכן החכם של הספרייה."
    )

    # 2. מדמים תשובת HTTP מוצלחת (קוד 200 עם JSON תקין שהמודל מחזיר)
    class MockHttpRespons:
        def read(self):
            # מבנה התשובה הגולמי שה-API של גוגל מחזיר בדרך כלל בבקשות HTTP
            response_payload = {
                "candidates": [{
                    "content": {
                        "parts": [{"text": "זוהי תשובה מזויפת מה-Mock לצורכי בדיקה. המודל עובד!"}]
                    }
                }]
            }
            return json.dumps(response_payload).encode('utf-8')
        
        def __enter__(self):
            return self
            
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_urlopen.return_value = MockHttpRespons()
    
    url = reverse('articles:ai_chat') 
    
    payload = json.dumps({
        'prompt': 'היי סוכן, מה המצב?',
        'message': 'היי סוכן, מה המצב?',
        'question': 'היי סוכן, מה המצב?',
        'text': 'היי סוכן, מה המצב?'
    })
    
    # הוספנו כאן secure=True
    response = client.post(url, data=payload, content_type='application/json', secure=True)
    
    assert response.status_code == 200
    
    response_data = response.json()
    assert "זוהי תשובה מזויפת" in response_data.get('answer', '')