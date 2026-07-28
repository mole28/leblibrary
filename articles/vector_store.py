import os
import chromadb
from chromadb.utils import embedding_functions
from django.conf import settings
from django.utils.html import strip_tags
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Article

chroma_client = chromadb.PersistentClient(path=str(settings.BASE_DIR / 'chroma_db'))

# שימוש במנגנון הטמעה מקומי שאינו דורש מפתחות API חיצוניים
default_ef = embedding_functions.DefaultEmbeddingFunction()

collection = chroma_client.get_or_create_collection(
    name="leblibrary_articles", 
    embedding_function=default_ef
)

def index_article(article: Article):
    if not article.is_published:
        return
    clean_content = strip_tags(article.content).replace('\n', ' ').strip()
    if not clean_content:
        return
    
    collection.upsert(
        documents=[clean_content],
        metadatas=[{"title": article.title, "url": f"/article/{article.pk}/"}],
        ids=[str(article.pk)]
    )

def search_similar_articles(query: str, top_k: int = 3):
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k
        )
        structured_results = []
        if results['documents'] and results['documents'][0]:
            for i in range(len(results['documents'][0])):
                structured_results.append({
                    'id': results['ids'][0][i],
                    'title': results['metadatas'][0][i]['title'],
                    'url': results['metadatas'][0][i]['url'],
                    'content_snippet': results['documents'][0][i][:250] + '...'
                })
        return structured_results
    except Exception:
        return []

@receiver(post_save, sender=Article)
def auto_index_article(sender, instance, **kwargs):
    if instance.is_published:
        index_article(instance)
    else:
        try:
            collection.delete(ids=[str(instance.pk)])
        except:
            pass

@receiver(post_delete, sender=Article)
def auto_delete_article(sender, instance, **kwargs):
    try:
        collection.delete(ids=[str(instance.pk)])
    except:
        pass