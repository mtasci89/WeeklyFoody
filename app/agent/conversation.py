from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    role: str
    text: str


class ConversationStore:
    """Sohbet gecmisini sohbet basina tutar.

    Simdilik bellekte; yeniden baslatmada sifirlanir. Kalici hale getirmek
    icin bu sinifin arkasini veritabanina almak yeterli (WF-04).

    Arac cagrilari ve sonuclari gecmise yazilmaz, yalnizca kullanici ve
    asistan metinleri tutulur: baglami ucuz tutar ve "onu degil, digerini"
    gibi referanslarin calismasi icin yeterlidir.
    """

    def __init__(self, max_turns: int = 12, max_chats: int = 64):
        self.max_turns = max(2, max_turns)
        self.max_chats = max(1, max_chats)
        self._chats: OrderedDict[int, deque[Turn]] = OrderedDict()

    def _bucket(self, chat_id: int) -> deque[Turn]:
        if chat_id in self._chats:
            self._chats.move_to_end(chat_id)
        else:
            self._chats[chat_id] = deque(maxlen=self.max_turns)
            while len(self._chats) > self.max_chats:
                self._chats.popitem(last=False)
        return self._chats[chat_id]

    def history(self, chat_id: int) -> list[dict]:
        return [{"role": turn.role, "content": turn.text} for turn in self._bucket(chat_id)]

    def record(self, chat_id: int, role: str, text: str) -> None:
        if text.strip():
            self._bucket(chat_id).append(Turn(role=role, text=text.strip()))

    def reset(self, chat_id: int) -> None:
        self._chats.pop(chat_id, None)
