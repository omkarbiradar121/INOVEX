from rest_framework import permissions

class IsAdminRole(permissions.BasePermission):
    """
    Allows access only to Administrator users.
    Engineers and Supervisors are explicitly denied.
    """
    message = "Permission denied: Administrator role required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_admin_role


class IsEngineerRole(permissions.BasePermission):
    """
    Allows access only to Engineer users.
    """
    message = "Permission denied: Engineer role required to ask maintenance questions."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_engineer_role or request.user.is_admin_role


class IsSupervisorRole(permissions.BasePermission):
    """
    Allows access to Supervisor and Admin users (read-only supervisor dashboard).
    """
    message = "Permission denied: Supervisor role required."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_supervisor_role or request.user.is_admin_role
