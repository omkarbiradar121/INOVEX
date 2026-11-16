"""
Role choices and user alias for Round 2 integration.
Maps to the primary AUTH_USER_MODEL (assistant.CustomUser).
"""
from django.db import models
from django.contrib.auth import get_user_model
from assistant.models import CustomUser

User = CustomUser


class CaseInsensitiveStr(str):
    def __eq__(self, other):
        if isinstance(other, str):
            return self.lower() == other.lower()
        return super().__eq__(other)

    def __hash__(self):
        return hash(self.lower())


class UserRole(CaseInsensitiveStr, models.Choices):
    ADMIN = 'admin', 'Administrator'
    ENGINEER = 'engineer', 'Engineer'
    SUPERVISOR = 'supervisor', 'Supervisor'


__all__ = ['User', 'UserRole']
