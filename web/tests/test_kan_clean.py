"""
Kan's pages wrap the article text in its sign-in prompt (four times) and its
footer, and both were being stored as part of the article content.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import scraper  # noqa: E402

PROMPT = "התחברו וקבלו תוכן מותאם אישית"
FOOTER = "Website created by IdeoDigital האם אתה רוצה להתנתק?"
BODY = "סולטן אבו אלהיג'א, תושב טמרה בן 31, יואשם בעבירות ביטחון."


class StripBoilerplateTest(unittest.TestCase):
    def test_removes_the_repeated_prompt_and_the_footer(self):
        stored = " ".join([PROMPT] * 4) + " " + BODY + " " + FOOTER
        self.assertEqual(scraper.strip_boilerplate(stored), BODY)

    def test_text_without_boilerplate_is_unchanged(self):
        self.assertEqual(scraper.strip_boilerplate(BODY), BODY)

    def test_everything_after_the_footer_marker_goes(self):
        self.assertEqual(scraper.strip_boilerplate(BODY + " Website created by IdeoDigital extra"), BODY)

    def test_parse_article_applies_it(self):
        html = ("<html><body><h1>כותרת</h1>"
                f"<p>{PROMPT} {PROMPT}</p><p>{BODY} {BODY}</p><p>{FOOTER}</p></body></html>")
        article = scraper.parse_article(html)
        self.assertNotIn("התחברו", article["content"])
        self.assertNotIn("IdeoDigital", article["content"])
        self.assertIn(BODY, article["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
