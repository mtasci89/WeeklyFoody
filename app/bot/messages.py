from __future__ import annotations


def split_message(text: str, limit: int = 3500) -> list[str]:
    """Keep Telegram messages below its UTF-16 length limit, preferring line breaks."""
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        for offset in range(0, len(line), 1500):
            piece = line[offset:offset + 1500]
            if len((current + piece).encode('utf-16-le')) // 2 > limit:
                chunks.append(current.rstrip())
                current = ""
            current += piece
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or [" "]


async def reply(message, text: str, **kwargs):
    # Plain text keeps recipe names containing Markdown punctuation safe.
    kwargs.pop("parse_mode", None)
    parts = split_message(text)
    for index, part in enumerate(parts):
        options = dict(kwargs)
        if index != len(parts) - 1:
            options.pop("reply_markup", None)
        await message.reply_text(part, **options)
