from django.urls import path
from . import views
from django.http import HttpResponse

# השם הזה חשוב, בגלל שאנחנו קוראים לקישורים בתבניות בצורה כזו: 'articles:about'
app_name = 'articles'

urlpatterns = [
    # ==========================
    # עמודי מאמרים (הליבה)
    # ==========================
    path('', views.article_list, name='list'),
    path('index/', views.article_index, name='articles_index'),
    path('article/<int:pk>/', views.article_detail, name='detail'),
    path('article/new/', views.article_create, name='create'),
    path('article/<int:pk>/edit/', views.article_edit, name='edit'),
    path('article/<int:pk>/delete/', views.article_delete, name='delete'),
    
    # ==========================
    # ספרים
    # ==========================
    path('books/', views.books, name='books'),
    path('book/<int:pk>/', views.book_detail, name='book_detail'),
    
    # ==========================
    # שאלות ותשובות + פרשת שבוע
    # ==========================
    path('qa/', views.qa_list, name='qa'),
    path('parasha/', views.parasha_list, name='parasha'),
    
    # ==========================
    # מחשבוני חז"ל
    # ==========================
    path('calculator/', views.calculator, name='calculator'),
    path('volume-calculator/', views.volume_calculator, name='volume_calculator'),
    path('weight-calculator/', views.weight_calculator, name='weight_calculator'),
    
    # ==========================
    # יצירת קשר ושירותי API
    # ==========================
    path('contact/', views.contact, name='contact'),
    path('api/ai-chat/', views.ai_chat_endpoint, name='ai_chat'),
    path('api/live-search/', views.live_search, name='live_search'),
    path('api/ai-search/', views.ai_open_search, name='ai_open_search'), 
    path('api/search-acronyms/', views.search_acronyms_api, name='search_acronyms_api'),
    
    # API הקראה קולית (חדש)
    path('api/audio/article/<int:article_id>/', views.get_article_audio, name='get_article_audio'),
    path('api/audio/book/<int:book_id>/', views.get_book_audio, name='get_book_audio'),
    
    # ==========================
    # חנות ועגלת קניות (E-commerce)
    # ==========================
    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:book_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout/', views.checkout, name='checkout'),
    
    # ==========================
    # עמודי פוטר (Footer)
    # ==========================
    path('about/', views.about, name='about'),
    path('terms/', views.terms, name='terms'),
    path('recently-added/', views.recently_added, name='recently_added'),

    path('61b4763967a849e6aae88315f9092c0d.txt', lambda request: HttpResponse('61b4763967a849e6aae88315f9092c0d')),
]