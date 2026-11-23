import logging
import threading
import chromadb
from chromadb.utils import embedding_functions
from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.html import strip_tags
from .models import Article

logger = logging.getLogger(__name__)

_CHROMA_LOCK = threading.Lock()
_COLLECTION = None


def _get_collection():
    global _COLLECTION
    if _COLLECTION is not None:
        return _COLLECTION
    with _CHROMA_LOCK:
        if _COLLECTION is None:
            client = chromadb.PersistentClient(path=str(settings.BASE_DIR / 'chroma_db'))
            ef = embedding_functions.DefaultEmbeddingFunction()
            _COLLECTION = client.get_or_create_collection(
                name='leblibrary_articles',
                embedding_function=ef,
            )
    return _COLLECTION


def index_article(article: Article):
    if not article.is_published:
        return
    clean_content = strip_tags(article.content or '').replace('\n', ' ').strip()
    if not clean_content:
        return
    article_url = f"/article/{article.slug}/" if article.slug else f"/article/{article.pk}/"
    try:
        col = _get_collection()
        col.upsert(
            documents=[clean_content],
            metadatas=[{'title': article.title, 'url': article_url}],
            ids=[str(article.pk)],
        )
    except Exception:
        logger.warning('Failed indexing article %s in ChromaDB', article.pk, exc_info=True)


def search_similar_articles(query: str, top_k: int = 3):
    try:
        col = _get_collection()
        results = col.query(
            query_texts=[query],
            n_results=top_k,
        )
        structured_results = []
        docs = results.get('documents') or []
        if docs and docs[0]:
            for i in range(len(docs[0])):
                structured_results.append({
                    'id': results['ids'][0][i],
                    'title': results['metadatas'][0][i]['title'],
                    'url': results['metadatas'][0][i]['url'],
                    'content_snippet': docs[0][i][:250] + '...',
                })
        return structured_results
    except Exception:
        logger.warning('Semantic search failed in ChromaDB', exc_info=True)
        return []


@receiver(post_save, sender=Article)
def auto_index_article(sender, instance, **kwargs):
    if instance.is_published:
        index_article(instance)
    else:
        try:
            _get_collection().delete(ids=[str(instance.pk)])
        except Exception:
            logger.debug('Failed deleting unpublished article %s from ChromaDB', instance.pk, exc_info=True)


@receiver(post_delete, sender=Article)
def auto_delete_article(sender, instance, **kwargs):
    try:
        _get_collection().delete(ids=[str(instance.pk)])
    except Exception:
        logger.debug('Failed deleting article %s from ChromaDB', instance.pk, exc_info=True)