import pytest


@pytest.fixture(autouse=True)
def use_simple_staticfiles_storage(settings):
    settings.STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'