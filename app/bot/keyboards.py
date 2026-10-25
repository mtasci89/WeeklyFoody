from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup


def home_keyboard():
    return ReplyKeyboardMarkup([["🍽 Menü", "🛒 Alışveriş"], ["📚 Tarifler", "🧪 Aday tarifler"], ["⚙️ Tercihler", "❓ Yardım"]], resize_keyboard=True, input_field_placeholder="Örn: Salı balık yerine Kuru Fasulye koy")


def approval_keyboard(session=None) -> InlineKeyboardMarkup:
    def data(action):
        return f"{action}:{session.id}:{session.draft_version}" if session else action
    published = session and session.state.value == "PUBLISHED"
    rows = [[InlineKeyboardButton("✏️ Menüyü değiştir", callback_data=data("change_help"))]]
    if not published:
        label = "✅ Onayla ve gönder" if not session or session.state.value != "APPROVED" else "📤 Gönderimi tamamla"
        rows.insert(0, [InlineKeyboardButton(label, callback_data=data("approve"))])
    rows.append([InlineKeyboardButton("🔄 Baştan hazırla", callback_data=data("regenerate"))])
    return InlineKeyboardMarkup(rows)
