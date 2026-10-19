# Minimal test settings for Django 1.1 (this branch predates
# tests/test_sqlite.py). Per this branch's own
# docs/internals/contributing.txt, the unit tests need a settings module
# "but only for database connection info, with the DATABASE_ENGINE setting",
# and with sqlite3 "a temporary database will be created in memory when
# running the tests." The runner overrides everything else it needs
# (ALWAYS_INSTALLED_APPS, ROOT_URLCONF, ...) itself.
DATABASE_ENGINE = 'sqlite3'

# The global_settings default is ''; a non-empty key for the few tests that
# sign or hash with it.
SECRET_KEY = 'django-tests-secret-key'
