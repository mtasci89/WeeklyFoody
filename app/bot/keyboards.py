from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def approval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Menüyü Onayla", callback_data="approve")],
            [InlineKeyboardButton("🔄 Yeniden Oluştur", callback_data="regenerate")],
            [InlineKeyboardButton("✏️ Değişiklik İste", callback_data="change_help")],
        ]
    )

