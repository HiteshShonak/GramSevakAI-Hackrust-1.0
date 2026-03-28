"""Parse Meta WhatsApp webhook payload into structured message data."""

import logging

log = logging.getLogger(__name__)


def parse_webhook_payload(data: dict) -> dict | None:
    """
    Parse incoming Meta webhook payload.

    Returns:
        dict with {phone, message_type, content, media_id, message_id} or None if not a user message.
    """
    try:
        entry = data.get("entry", [])
        if not entry:
            return None

        changes = entry[0].get("changes", [])
        if not changes:
            return None

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None  # status update, not a user message

        msg = messages[0]
        phone = msg.get("from", "")
        message_id = msg.get("id", "")
        msg_type = msg.get("type", "")

        result = {
            "phone": phone,
            "message_type": msg_type,
            "content": "",
            "media_id": None,
            "message_id": message_id,
        }

        if msg_type == "text":
            result["content"] = msg.get("text", {}).get("body", "")

        elif msg_type in ("audio", "voice"):
            audio_data = msg.get("audio", {})
            result["media_id"] = audio_data.get("id", "")
            result["message_type"] = "audio"  # normalize voice → audio

        elif msg_type == "image":
            # ignore images for MVP — only text and voice
            return None

        else:
            # unsupported message type
            log.info(f"Unsupported message type: {msg_type} from {phone}")
            return None

        return result

    except (IndexError, KeyError, TypeError) as e:
        log.error(f"Failed to parse webhook payload: {e}")
        return None
