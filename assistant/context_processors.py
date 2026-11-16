def user_role_context(request):
    if not request.user.is_authenticated:
        return {'is_admin_user': False, 'is_engineer_user': False, 'is_supervisor_user': False, 'user_role': None}
    
    role = getattr(request.user, 'role', 'engineer')
    return {
        'is_admin_user': request.user.is_admin_role,
        'is_engineer_user': request.user.is_engineer_role,
        'is_supervisor_user': request.user.is_supervisor_role,
        'user_role': role,
    }
