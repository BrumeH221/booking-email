# backend/text_cleaner.py
#
# Step 2 of the NLP pipeline: remove HTML, signatures, quoted replies.

import html
import re


SIGNATURE_PATTERNS = [
    r"\n--\s*\n.*",                          # standard "-- " signature
    r"\nSent from my .+",                    # "Sent from my iPhone"
    r"\nGet Outlook for .+",                 # Outlook footers
    r"\nKind regards.*",
    r"\nBest regards.*",
    r"\nRegards.*",
    r"\nThanks.*",
    r"\nThank you.*",
    r"\nCheers.*",
]

QUOTED_REPLY_PATTERNS = [
    r"\nOn .+ wrote:.*",                     # "On <date>, <name> wrote:"
    r"\n>+ ?.*",                             # ">"-quoted lines
    r"\n_{5,}.*",                            # "_______" separator
    r"\nFrom: .+\nSent: .+\nTo: .+",         # Outlook reply header
]


def strip_html(text: str) -> str:
    """Remove HTML tags, decode entities."""
    if "<" not in text:
        return text
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return text


def strip_signature(text: str) -> str:
    for pat in SIGNATURE_PATTERNS:
        text = re.sub(pat, "", text, flags=re.DOTALL | re.IGNORECASE)
    return text


def strip_quoted_reply(text: str) -> str:
    for pat in QUOTED_REPLY_PATTERNS:
        text = re.sub(pat, "", text, flags=re.DOTALL | re.IGNORECASE)
    return text


def collapse_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_email_text(raw: str) -> str:
    """Run the full cleaning pipeline."""
    if not raw:
        return ""
    text = strip_html(raw)
    text = strip_quoted_reply(text)
    text = strip_signature(text)
    text = collapse_whitespace(text)
    return text


if __name__ == "__main__":
    sample = """
    <p>Hi team,</p>
    <p>I'd like to book an appointment <b>next Wednesday at 3pm</b>.</p>
    <br>
    Thanks,
    John

    --
    Sent from my iPhone

    On Mon, May 18, 2026 at 8:00 AM, support@biz.com wrote:
    > Previous reply content here
    """
    print(clean_email_text(sample))
