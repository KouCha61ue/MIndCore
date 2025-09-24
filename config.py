from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI = os.getenv("GEMINI_KEY")


def _parse_channel_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()

    channel_ids: set[int] = set()
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        try:
            channel_ids.add(int(token))
        except ValueError as exc:
            raise ValueError(
                f"Invalid channel id in ALLOWED_CHANNEL_IDS: {token!r}"
            ) from exc
    return channel_ids


ALLOWED_CHANNEL_IDS = _parse_channel_ids(os.getenv("ALLOWED_CHANNEL_IDS"))
