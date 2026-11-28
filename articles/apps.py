from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _configure_sqlite_connection(sender, connection, **kwargs):
    if connection.vendor != 'sqlite':
        return
    db_name = str(connection.settings_dict.get('NAME', ''))
    is_memory = not db_name or db_name == ':memory:' or 'mode=memory' in db_name
    with connection.cursor() as cursor:
        cursor.execute('PRAGMA busy_timeout = 20000;')
        cursor.execute('PRAGMA foreign_keys = ON;')
        cursor.execute('PRAGMA temp_store = MEMORY;')
        cursor.execute('PRAGMA cache_size = -16000;')
        if not is_memory:
            cursor.execute('PRAGMA journal_mode = WAL;')
            cursor.execute('PRAGMA synchronous = NORMAL;')


class ArticlesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'articles'

    def ready(self):
        connection_created.connect(
            _configure_sqlite_connection,
            dispatch_uid='leblibrary_sqlite_pragmas',
        )
