"""
Channel 13 declares its articleBody in JSON-LD with HTML entities still encoded
(&quot;, &#039;, &nbsp;). JSON parsing leaves them as literal text, so they ended
up in stored content. parse_article must decode them.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.scraper import parse_article  # noqa: E402

BODY = ("הרמטכ&quot;ל אמר ש&#039;המבצע נמשך&#039; ו&amp;ציין&nbsp;כי " * 20).strip()


def page(body, headline="כותרת"):
    ld = {"@type": "NewsArticle", "headline": headline, "articleBody": body,
          "datePublished": "2026-11-08T10:00:00+02:00"}
    return ("<html><head><script type=\"application/ld+json\">"
            + json.dumps(ld, ensure_ascii=False) + "</script></head><body></body></html>")


class ParseArticleEntitiesTest(unittest.TestCase):
    def test_article_body_entities_are_decoded(self):
        content = parse_article(page(BODY))["content"]
        for entity in ("&quot;", "&#039;", "&amp;", "&nbsp;"):
            self.assertNotIn(entity, content)
        self.assertIn('הרמטכ"ל', content)
        self.assertIn("ש'המבצע", content)
        self.assertIn("ו&ציין כי", content, "&nbsp; should become a plain space")

    def test_headline_entities_are_decoded(self):
        title = parse_article(page(BODY, headline="צה&quot;ל תוקף"))["title"]
        self.assertEqual(title, 'צה"ל תוקף')

    def test_plain_text_is_unchanged(self):
        plain = "טקסט רגיל בלי קודים, עם מרכאות \"אמיתיות\" כבר. " * 10
        self.assertEqual(parse_article(page(plain))["content"], plain.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
