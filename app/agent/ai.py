"""Hangi yapay zekâ arka ucu kullanılacak: tek yerden karar.

Varsayılan Groq (+ Tavily araması). Gemini yalnızca GOOGLE_ENABLED=true ve
AGENT_PROVIDER=gemini ise kullanılır (kullanıcı Google'ı istemiyor).
"""
from __future__ import annotations


def uses_groq(settings) -> bool:
    return settings.agent_provider == "groq" or not getattr(settings, "google_enabled", False)


def uses_gemini(settings) -> bool:
    return settings.agent_provider == "gemini" and getattr(settings, "google_enabled", False) and bool(settings.gemini_api_key)


def ai_available(settings) -> bool:
    """Yapılandırılmış istek (tarif doldurma, kalori, araştırma) yapılabilir mi."""
    if settings.agent_provider == "anthropic":
        return False
    if uses_groq(settings):
        return bool(settings.groq_api_key)
    return uses_gemini(settings)


def make_backend(settings, client=None):
    """GeminiBackend ile aynı yüzeyi sunan arka uç (Groq ya da Gemini)."""
    if uses_groq(settings) and settings.agent_provider != "anthropic":
        from app.agent.groq_backend import GroqBackend

        return GroqBackend(settings)
    from app.agent.gemini_backend import GeminiBackend

    return GeminiBackend(settings, client=client)
