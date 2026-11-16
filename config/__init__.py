import pymysql

pymysql.install_as_MySQLdb()

# Django 6.1 enforces MySQL >= 8.4, allow MySQL 8.0.x on local system
from django.db.backends.base.base import BaseDatabaseWrapper
BaseDatabaseWrapper.check_database_version_supported = lambda self: None

from .celery import app as celery_app

__all__ = ('celery_app',)
