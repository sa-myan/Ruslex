"""Django session authentication and registration endpoints.

Permissions always come from Django Groups, not from frontend visibility.
Never log credentials, tokens, or complete authentication request bodies.
"""

import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import SiteOptions


def has_review(user) -> bool:
    return user.is_authenticated and user.has_perm("accounts.review_lexicon")


def has_edit(user) -> bool:
    return user.is_authenticated and user.has_perm("accounts.edit_lexicon")


def response_user(request) -> dict:
    user = request.user
    return {
        "authenticated": user.is_authenticated,
        "username": user.username if user.is_authenticated else None,
        "can_review": has_review(user),
        "can_edit": has_edit(user),
        "is_staff": bool(user.is_authenticated and user.is_staff),
        "registration_open": SiteOptions.current().registration_open,
        "csrf_token": get_token(request),
    }


def payload(request) -> dict:
    """Reject malformed JSON and non-object request bodies."""
    try:
        value = json.loads(request.body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("Expected a JSON object") from exc
    if not isinstance(value, dict):
        raise ValidationError("Expected a JSON object")
    return value


def _login_credentials(data: dict) -> tuple[str, str]:
    username = data.get("username", "")
    password = data.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValidationError("Invalid username or password")
    return username, password


def _registration_details(data: dict) -> tuple[str, str, str]:
    """Validate the existing registration rules before touching User tables."""
    username = data.get("username", "")
    email = data.get("email", "")
    password = data.get("password", "")
    if not all(isinstance(value, str) for value in (username, email, password)):
        raise ValidationError("Expected string registration fields")

    username = username.strip()
    email = email.strip()
    if (
        not 3 <= len(username) <= 150
        or not username.isascii()
        or not username.replace("_", "").isalnum()
    ):
        raise ValidationError("Username must be 3–150 ASCII letters, digits or underscores")
    if "@" not in email or len(email) > 254:
        raise ValidationError("A valid email address is required")

    proposed_user = User(username=username, email=email)
    validate_password(password, proposed_user)
    return username, email, password


@ensure_csrf_cookie
@require_http_methods(["GET"])
def me(request):
    return JsonResponse(response_user(request))


@require_http_methods(["POST"])
def sign_in(request):
    try:
        username, password = _login_credentials(payload(request))
        user = authenticate(request, username=username, password=password)
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
        username, email, password = _registration_details(payload(request))
        # Newly registered accounts have no staff status, groups, or editing rights.
        User.objects.create_user(username=username, email=email, password=password)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    except IntegrityError:
        return JsonResponse({"detail": "Username already exists"}, status=409)

    return JsonResponse({"ok": True}, status=201)
