"""Query-string checks shared by the dashboard APIs."""
from .scraper import SECTION_NAMES, TOPICS

POLITICS_SECTIONS = tuple(s for s in SECTION_NAMES if s != "defense")


def topic_and_section(query):
    """(topic, section) from a parsed query dict of single values.
    Returns (None, None) for an unknown topic, which the caller answers with 400.
    The section only applies to politics; anything unrecognised means all ("")."""
    topic = query.get("topic") or "defense"
    if topic not in TOPICS:
        return None, None
    section = query.get("section", "")
    if topic != "politics" or section not in POLITICS_SECTIONS:
        section = ""
    return topic, section
