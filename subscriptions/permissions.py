from rest_framework.permissions import BasePermission

# Free Trial: 2 handpicked topics/quizzes (see the plan screen).
FREE_TRIAL_QUIZ_LIMIT = 2


class IsPremium(BasePermission):
    message = "A premium subscription is required to access this content."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        sub = getattr(user, "subscription", None)
        return bool(sub and sub.is_premium)