import pytest
import json
import os
from django.urls import reverse
from django.test import TestCase, RequestFactory
from django.conf import settings
from articles.models import Acronym
from articles.views import search_acronyms_api

# הדקורטור הזה חובה לכל טסט שניגש למסד הנתונים או מנסה ליצור אובייקטים של ג'נגו
@pytest.mark.django_db
def test_article_list_view_loads_successfully(client):
    # 'client' הוא דפדפן וירטואלי ש-pytest מספק לנו
    url = reverse('articles:list')
    # הוספנו כאן secure=True כדי למנוע את שגיאת ההפניה (301)
    response = client.get(url, secure=True)
    
    # הבדיקה עצמה: האם השרת החזיר קוד 200 (הכל תקין)?
    assert response.status_code == 200

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

class ResponsiveDesignTest(TestCase):
    def test_base_html_has_responsive_meta_and_css(self):
        base_html_path = os.path.join(settings.BASE_DIR, 'articles', 'templates', 'articles', 'base.html')
        
        # Verify the file exists
        self.assertTrue(os.path.exists(base_html_path), "base.html file not found in the expected path.")
        
        with open(base_html_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # 1. Check for standard viewport meta tag (crucial for mobile)
            self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1.0">', content, 
                          "Viewport meta tag is missing. Site won't scale properly on mobile.")
            
            # 2. Check for the word-break fix we added
            self.assertTrue('overflow-wrap: break-word' in content or 'word-break: break-word' in content, 
                            "Missing CSS rule to prevent long words from breaking the mobile screen layout.")
            
            # 3. Check for the image scaling fix
            self.assertIn('max-width: 100%', content, 
                          "Missing CSS rule to constrain image widths on mobile screens.")
            
            # 4. Check for dynamic base font size in media queries
            self.assertTrue('html { font-size:' in content or '@media' in content, 
                            "Missing media queries or dynamic base font sizing for responsive typography.")