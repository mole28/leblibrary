from django.urls import path
from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.generic.base import RedirectView
from . import views
from .models import Article, Book

app_name = 'articles'


def legacy_article_id_redirect(request, pk):
    article = Article.objects.filter(pk=pk).first()
    if article and getattr(article, 'slug', None):
        return redirect('articles:detail', slug=article.slug, permanent=True)
    return redirect('articles:list', permanent=True)


def safe_book_detail(request, pk):
    if not Book.objects.filter(pk=pk).exists():
        return redirect('articles:books', permanent=True)
    return views.book_detail(request, pk=pk)


urlpatterns = [
    path('', views.article_list, name='list'),
    path('index/', views.article_index, name='articles_index'),

    path('article/new/', views.article_create, name='create'),
    path('article/<int:pk>/', legacy_article_id_redirect, name='legacy_article_detail'),
    path('article/<str:slug>/', views.article_detail, name='detail'),
    path('article/<str:slug>/edit/', views.article_edit, name='edit'),
    path('article/<str:slug>/delete/', views.article_delete, name='delete'),

    path('books/', views.books, name='books'),
    path('book/<int:pk>/', safe_book_detail, name='book_detail'),

    path('qa/', views.qa_list, name='qa'),
    path('parasha/', views.parasha_list, name='parasha'),

    path('calculator/', views.calculator, name='calculator'),
    path('volume-calculator/', views.volume_calculator, name='volume_calculator'),
    path('weight-calculator/', views.weight_calculator, name='weight_calculator'),

    path('acronyms/', RedirectView.as_view(url='/advanced-search/', permanent=True), name='acronyms_redirect'),
    path('acronyms', RedirectView.as_view(url='/advanced-search/', permanent=True)),

    path('contact/', views.contact, name='contact'),
    path('api/ai-chat/', views.ai_chat_endpoint, name='ai_chat'),
    path('api/live-search/', views.live_search, name='live_search'),
    path('api/ai-search/', views.ai_open_search, name='ai_open_search'),
    path('api/search-acronyms/', views.search_acronyms_api, name='search_acronyms_api'),

    path('api/audio/article/<str:identifier>/', views.get_article_audio, name='get_article_audio'),
    path('api/audio/book/<int:book_id>/', views.get_book_audio, name='get_book_audio'),

    path('cart/', views.cart_detail, name='cart_detail'),
    path('cart/add/<int:book_id>/', views.add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout/', views.checkout, name='checkout'),

    path('about/', views.about, name='about'),
    path('terms/', views.terms, name='terms'),
    path('recently-added/', views.recently_added, name='recently_added'),

    path('61b4763967a849e6aae88315f9092c0d.txt', lambda request: HttpResponse('61b4763967a849e6aae88315f9092c0d')),
    path('advanced-search/', views.advanced_search_view, name='advanced_search'),
    path('api/tanakh-search/', views.tanakh_advanced_search_api, name='tanakh_advanced_search_api'),
    path('api/torah-ai-insights/', views.torah_ai_insights_api, name='torah_ai_insights_api'),
    path('aramaic-translator/', views.aramaic_translator_view, name='aramaic_translator'),
    path('api/aramaic-translate/', views.aramaic_translate_api, name='aramaic_translate_api'),
]