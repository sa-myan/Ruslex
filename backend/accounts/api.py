"""Session authentication with ordinary Django CSRF protection."""
import json
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.middleware.csrf import get_token
from .models import SiteOptions


def has_review(user):
    return user.is_authenticated and user.has_perm("accounts.review_lexicon")


def has_edit(user):
    return user.is_authenticated and user.has_perm("accounts.edit_lexicon")


def response_user(request):
    user = request.user
    return {"authenticated": user.is_authenticated,
            "username": user.username if user.is_authenticated else None,
            "can_review": has_review(user), "can_edit": has_edit(user),
            "is_staff": bool(user.is_authenticated and user.is_staff),
            "registration_open": SiteOptions.current().registration_open,
            "csrf_token": get_token(request)}


def payload(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, json.JSONDecodeError):
        raise ValidationError("Expected a JSON object")


@ensure_csrf_cookie
@require_http_methods(["GET"])
def me(request):
    return JsonResponse(response_user(request))


@require_http_methods(["POST"])
def sign_in(request):
    try:
        data = payload(request)
        user = authenticate(request, username=data.get("username", ""), password=data.get("password", ""))
    except ValidationError:
        user = None
    if user is None or not user.is_active:
        return JsonResponse({"detail": "Invalid username or password"}, status=400)
    login(request, user)
    return JsonResponse(response_user(request))


@require_http_methods(["POST"])
def sign_out(request):
    logout(request)
    return JsonResponse({"ok": True})


@require_http_methods(["POST"])
def sign_up(request):
    if not SiteOptions.current().registration_open:
        return JsonResponse({"detail": "Registration is disabled"}, status=403)
    try:
        data = payload(request)
        username = str(data.get("username", "")).strip()
        email = str(data.get("email", "")).strip()
        password = str(data.get("password", ""))
        if not (3 <= len(username) <= 150) or not username.isascii() or not username.replace("_", "").isalnum():
            raise ValidationError("Username must be 3–150 ASCII letters, digits or underscores")
        if "@" not in email or len(email) > 254:
            raise ValidationError("A valid email address is required")
        user = User(username=username, email=email)
        validate_password(password, user)
        # New users have no staff status, groups, or editing permissions.
        User.objects.create_user(username=username, email=email, password=password)
    except (ValidationError, ValueError) as exc:
        messages = getattr(exc, "messages", [str(exc)])
        return JsonResponse({"detail": "; ".join(messages)}, status=400)
    except Exception as exc:
        from django.db import IntegrityError
        if isinstance(exc, IntegrityError):
            return JsonResponse({"detail": "Username already exists"}, status=409)
        raise
    return JsonResponse({"ok": True}, status=201)
