import pytest
from django.urls import reverse

# הדקורטור הזה חובה לכל טסט שניגש למסד הנתונים או מנסה ליצור אובייקטים של ג'נגו
@pytest.mark.django_db
def test_article_list_view_loads_successfully(client):
    # 'client' הוא דפדפן וירטואלי ש-pytest מספק לנו
    url = reverse('articles:list')
    response = client.get(url)
    
    # הבדיקה עצמה: האם השרת החזיר קוד 200 (הכל תקין)?
    assert response.status_code == 200

import json
from django.test import TestCase, RequestFactory
from articles.models import Acronym
from articles.views import search_acronyms_api

class AcronymSearchAPITest(TestCase):
    def setUp(self):
        Acronym.objects.create(short='רמב"ם', meaning='רבי משה בן מימון')
        Acronym.objects.create(short="רש'י", meaning='רבי שלמה יצחקי')
        self.factory = RequestFactory()

    def test_search_normalizes_quotes(self):
        test_cases = [
            ('רמב"ם', 'רמב"ם'),
            ('רמב״ם', 'רמב"ם'),
            ('רמב”ם', 'רמב"ם'),
            ("רש'י", "רש'י"),
            ("רש׳י", "רש'י"),
            ("רש`י", "רש'י"),
        ]

        for query, expected_short in test_cases:
            request = self.factory.get('/dummy/', {'q': query, 'type': 'short'})
            response = search_acronyms_api(request)
            
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            
            self.assertTrue(len(data['results']) > 0, f"Search failed for: {query}")
            self.assertEqual(data['results'][0]['short'], expected_short)