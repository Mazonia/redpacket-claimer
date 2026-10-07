import re
from typing import List, Dict, Any

# Standalone 8-character code pattern
RED_PACKET_PATTERNS = [
    r'[🎁\U0001f381]\s*([A-Za-z0-9]{8})\b',  # Emoji followed by 8-char code: 🎁 I8C23DTN
    r'\b(BP[A-Za-z0-9]{6,8})\b',             # Binance Pay prefix code: BP...
    r'\b([A-Za-z0-9]{8})\b',                 # Generic 8-character code
]

# Binance Square Post URLs (e.g. https://app.binance.com/uni-qr/cpos/371921171275162 or https://www.binance.com/en/square/post/371921171275162)
BINANCE_SQUARE_URL_PATTERN = r'https?://[^\s\)\>]*binance\.com/(?:[^\s\)\>]*/)?(?:square/post|uni-qr/cpos)/[^\s\)\>]+'

# Direct Red Packet shortlinks (e.g. https://s.binance.com/abcdef)
BINANCE_RED_PACKET_URL_PATTERN = r'https?://s\.binance\.com/[a-zA-Z0-9]+'

# Generic URL pattern for stripping
ANY_URL_PATTERN = r'https?://\S+'

IGNORED_WORDS = {
    "BINANCE", "FEBRUARY", "DECEMBER", "NOVEMBER", "REWARDS", "TELEGRAM",
    "FEEDBACK", "REGISTER", "DOWNLOAD", "QUESTION", "SOLUTIONS", "ACTIVITY"
}

def extract_red_packet_codes(text: str) -> List[str]:
    """
    Extract 8-character Binance Crypto Box / Red Packet codes.
    Strips URLs first to prevent URL parameters (like ?r=YNGX16JK) from being treated as codes.
    """
    # 1. First check explicit gift emoji codes
    emoji_matches = re.findall(r'[🎁\U0001f381]\s*([A-Za-z0-9]{8})\b', text)
    if emoji_matches:
        return [m.strip().upper() for m in emoji_matches]

    # 2. Strip URLs to avoid false positives from URL query parameters
    cleaned_text = re.sub(ANY_URL_PATTERN, '', text)

    codes = set()
    for pattern in RED_PACKET_PATTERNS:
        matches = re.findall(pattern, cleaned_text)
        for match in matches:
            if isinstance(match, tuple):
                match = match[0]
            code = match.upper().strip()
            if code in IGNORED_WORDS:
                continue
            # Ensure code has letters/digits mix or starts with BP
            if (any(c.isdigit() for c in code) and any(c.isalpha() for c in code)) or code.startswith("BP"):
                codes.add(code)

    return list(codes)

def extract_urls_from_entities(text: str = "", entities: Any = None) -> List[str]:
    """
    Extract URLs embedded in Telegram message entities (such as hidden hyperlinks behind anchor text).
    """
    urls = []
    if not entities:
        return urls

    for ent in entities:
        # 1. Telethon MessageEntityTextUrl (hidden hyperlink behind anchor text)
        url = getattr(ent, 'url', None)
        if url and isinstance(url, str):
            urls.append(url.strip())
            continue

        # 2. Dict format if serialized JSON
        if isinstance(ent, dict):
            dict_url = ent.get('url')
            if dict_url and isinstance(dict_url, str):
                urls.append(dict_url.strip())
                continue

        # 3. MessageEntityUrl (plaintext URL offset/length in text)
        if hasattr(ent, 'offset') and hasattr(ent, 'length') and text:
            type_name = type(ent).__name__
            if 'Url' in type_name and not getattr(ent, 'url', None):
                try:
                    raw_sub = text[ent.offset:ent.offset + ent.length].strip()
                    if raw_sub.startswith("http://") or raw_sub.startswith("https://"):
                        urls.append(raw_sub)
                except Exception:
                    pass

    return urls

def extract_square_urls(text: str, entities: Any = None) -> List[str]:
    """Extract Binance Square post links from text and Telegram message entities."""
    raw_urls = re.findall(BINANCE_SQUARE_URL_PATTERN, text, re.IGNORECASE)
    if entities:
        for u in extract_urls_from_entities(text, entities):
            if re.search(BINANCE_SQUARE_URL_PATTERN, u, re.IGNORECASE):
                raw_urls.append(u)
    return list(dict.fromkeys(raw_urls))

def extract_red_packet_urls(text: str, entities: Any = None) -> List[str]:
    """Extract direct s.binance.com red packet claim links from text and Telegram message entities."""
    raw_urls = re.findall(BINANCE_RED_PACKET_URL_PATTERN, text, re.IGNORECASE)
    if entities:
        for u in extract_urls_from_entities(text, entities):
            if re.search(BINANCE_RED_PACKET_URL_PATTERN, u, re.IGNORECASE):
                raw_urls.append(u)
    return list(dict.fromkeys(raw_urls))

def extract_quiz_answers(text: str) -> List[str]:
    """
    Extract answers wrapped in exclamation marks (e.g. ❕20.8k❕ or !20.8k!)
    or following 'Answer:' prefixes.
    """
    answers = []
    
    # 1. Match answer inside ❕...❕ or !...!
    exclamation_matches = re.findall(r'[❕!]\s*([^❕!\n\r]+?)\s*[❕!]', text)
    for match in exclamation_matches:
        ans = match.strip()
        if ans and ans not in answers:
            answers.append(ans)

    # 2. Match Answer : <value>
    prefix_matches = re.findall(r'(?:ans|answer|solution|option)\s*[:=\-]\s*([^\n\r]+)', text, re.IGNORECASE)
    for match in prefix_matches:
        ans = re.sub(r'[❕!]', '', match).strip()
        if ans and ans not in answers:
            answers.append(ans)

    return answers

def parse_telegram_message(message_or_text: Any, entities: Any = None) -> Dict[str, Any]:
    """
    Parse a full Telegram message and extract all actionable reward items.
    Accepts raw text, a Telethon Message object, or (text, entities).
    """
    if hasattr(message_or_text, 'raw_text'):
        text = message_or_text.raw_text or ""
        if entities is None and hasattr(message_or_text, 'entities'):
            entities = message_or_text.entities
    else:
        text = str(message_or_text or "")

    codes = extract_red_packet_codes(text)
    square_urls = extract_square_urls(text, entities=entities)
    red_packet_urls = extract_red_packet_urls(text, entities=entities)
    answers = extract_quiz_answers(text)

    # Format Binance Square URLs to canonical web form:
    # https://app.binance.com/uni-qr/cpos/POST_ID -> https://www.binance.com/en/square/post/POST_ID
    formatted_square_urls = []
    for url in square_urls:
        cpos_match = re.search(r'cpos/(\d+)', url)
        if cpos_match:
            post_id = cpos_match.group(1)
            formatted_square_urls.append(f"https://www.binance.com/en/square/post/{post_id}")
        else:
            base_url = re.sub(r'\?.*$', '', url)
            formatted_square_urls.append(base_url)

    return {
        "codes": list(dict.fromkeys(codes)),
        "square_urls": list(dict.fromkeys(formatted_square_urls)),
        "red_packet_urls": list(dict.fromkeys(red_packet_urls)),
        "answers": answers,
        "raw_text": text
    }
