from functools import wraps
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import render
from rest_framework.permissions import BasePermission
from .models import UserRole


def role_required(allowed_roles):
    """
    Decorator for views that checks whether a user is authenticated
    and belongs to at least one of the specified roles.
    If unauthenticated, redirects to login with next param.
    If authenticated but unauthorized, renders a clean 403 Forbidden page.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            user_role = str(getattr(request.user, 'role', '')).lower()
            normalized_allowed = []
            for r in allowed_roles:
                val = r.value if hasattr(r, 'value') else str(r)
                normalized_allowed.append(str(val).lower())

            is_allowed = False
            if 'admin' in normalized_allowed and getattr(request.user, 'is_administrator', False):
                is_allowed = True
            elif 'engineer' in normalized_allowed and getattr(request.user, 'is_engineer', False):
                is_allowed = True
            elif 'supervisor' in normalized_allowed and getattr(request.user, 'is_supervisor', False):
                is_allowed = True
            elif user_role in normalized_allowed:
                is_allowed = True
            elif ('admin' in normalized_allowed) and request.user.is_superuser:
                is_allowed = True

            if not is_allowed:
                context = {
                    'required_roles': [str(getattr(r, 'label', getattr(r, 'value', r))) for r in allowed_roles],
                    'user_role': request.user.get_role_display() if hasattr(request.user, 'get_role_display') else str(user_role),
                }
                try:
                    return render(request, 'accounts/access_denied.html', context, status=403)
                except Exception:
                    return render(request, 'access_denied.html', context, status=403)

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def admin_required(view_func):
    return role_required([UserRole.ADMIN])(view_func)


def engineer_required(view_func):
    return role_required([UserRole.ENGINEER])(view_func)


def supervisor_required(view_func):
    return role_required([UserRole.SUPERVISOR])(view_func)


# Django REST Framework Permissions

class IsAdministratorUser(BasePermission):
    """
    Allows access only to authenticated Administrator users.
    """
    message = "Administrator role required to access this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_administrator)


class IsEngineerUser(BasePermission):
    """
    Allows access only to authenticated Engineer users.
    """
    message = "Engineer role required to access this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_engineer)


class IsSupervisorUser(BasePermission):
    """
    Allows access only to authenticated Supervisor users.
    """
    message = "Supervisor role required to access this endpoint."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_supervisor)
