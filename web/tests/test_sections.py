"""
The site registry is keyed by topic (defense / politics) and every source can
list several sections (e.g. Channel 13 politics: domestic + diplomatic).
get_links walks them all and tags each link with the section it came from.
No network: fetch is patched with fake pages.
"""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from lib import scraper  # noqa: E402
from curl_cffi.requests.exceptions import HTTPError  # noqa: E402
from test_scraper_events import Recorder  # noqa: E402

TWO_SECTIONS = {
    "base": "https://ex.co.il",
    "sections": [
        {"name": "domestic", "category_url": "https://ex.co.il/politics/",
         "link_pattern": r"/politics/item/\d+"},
        {"name": "diplomatic", "category_url": "https://ex.co.il/diplomacy/",
         "link_pattern": r"/(?:diplomacy|politics)/item/\d+"},
    ],
}


def page(*paths):
    return "<html><body>" + "".join(f'<a href="{p}">x</a>' for p in paths) + "</body></html>"


class Base(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(scraper.time, "sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)
        reg = mock.patch.dict(scraper.SITES["politics"], {"Example": TWO_SECTIONS})
        reg.start()
        self.addCleanup(reg.stop)
        self.log = Recorder()

    def links(self, pages, topic="politics", source="Example", **kw):
        def fetch(url, timeout=20):
            body = pages.get(url, "<html></html>")
            if isinstance(body, Exception):
                raise body
            return body
        with mock.patch.object(scraper, "fetch", fetch):
            return scraper.get_links(topic, source, log=self.log, **kw)


class RegistryTest(unittest.TestCase):
    def test_topics(self):
        self.assertEqual(scraper.TOPICS, ("defense", "politics"))
        self.assertEqual(set(scraper.SITES), set(scraper.TOPICS))

    def test_every_source_has_sections_with_known_names(self):
        for topic, sites in scraper.SITES.items():
            for source, site in sites.items():
                self.assertTrue(site["sections"], f"{topic}/{source} has no sections")
                for s in site["sections"]:
                    self.assertIn(s["name"], scraper.SECTION_NAMES, f"{topic}/{source}")
                    self.assertTrue(s.get("category_url") or s.get("rss_url"), f"{topic}/{source}")

    def test_the_six_original_defense_outlets_are_unchanged(self):
        d = scraper.SITES["defense"]
        self.assertEqual(d["Ynet"]["sections"][0]["category_url"], "https://www.ynet.co.il/news/category/344")
        self.assertEqual(d["Channel 13"]["sections"][0]["page_url"],
                         "https://13tv.co.il/news/politics/security/page/{n}/")
        self.assertTrue(d["Kan News"]["server_blocked"])
        self.assertIn("sitemap_url", d["Kan News"])

    def test_sources_and_server_sources(self):
        self.assertIn("Kan News", scraper.sources("defense"))
        self.assertNotIn("Kan News", scraper.server_sources("defense"))
        self.assertNotIn("Kan News", scraper.server_sources("politics"))
        with self.assertRaises(ValueError):
            scraper.sources("sports")


class MultiSectionTest(Base):
    def test_links_are_tagged_with_their_section_and_deduplicated(self):
        got = self.links({
            "https://ex.co.il/politics/": page("/politics/item/1", "/politics/item/2"),
            "https://ex.co.il/diplomacy/": page("/diplomacy/item/9", "/politics/item/2"),
        })
        self.assertEqual(got, [
            ("https://ex.co.il/politics/item/1", "domestic"),
            ("https://ex.co.il/politics/item/2", "domestic"),
            ("https://ex.co.il/diplomacy/item/9", "diplomatic"),
        ])

    def test_one_failing_section_keeps_the_others(self):
        got = self.links({
            "https://ex.co.il/politics/": HTTPError("403"),
            "https://ex.co.il/diplomacy/": page("/diplomacy/item/9"),
        })
        self.assertEqual(got, [("https://ex.co.il/diplomacy/item/9", "diplomatic")])
        warn = [e for e in self.log.events if e["level"] == "warn"]
        self.assertTrue(any("domestic" in e["message"] for e in warn), self.log.text())

    def test_all_sections_failing_raises(self):
        with self.assertRaises(HTTPError):
            self.links({"https://ex.co.il/politics/": HTTPError("403"),
                        "https://ex.co.il/diplomacy/": HTTPError("403")})

    def test_messages_name_the_section_when_there_are_several(self):
        self.links({"https://ex.co.il/politics/": page("/politics/item/1"),
                    "https://ex.co.il/diplomacy/": page("/diplomacy/item/9")})
        self.assertTrue(any(e["message"].startswith("[diplomatic] ") for e in self.log.events), self.log.text())

    def test_unknown_source_raises(self):
        with self.assertRaises(KeyError):
            self.links({}, source="Nope")


class RssTest(Base):
    def test_ynet_politics_reads_article_links_from_its_feed(self):
        feed = """<rss><channel><title>ynet</title>
          <link><![CDATA[https://www.ynet.co.il/news/category/185]]></link>
          <item><title>a</title><link><![CDATA[https://www.ynet.co.il/news/article/byceoyvafe]]></link></item>
          <item><title>b</title><link>https://www.ynet.co.il/news/article/s1nfj1drzl</link>
                <guid>https://www.ynet.co.il/news/article/s1nfj1drzl</guid></item>
          <item><title>c</title><link>https://www.ynetnews.com/article/xyz</link></item>
        </channel></rss>"""
        got = self.links({"https://www.ynet.co.il/Integration/StoryRss185.xml": feed}, source="Ynet")
        self.assertEqual(got, [("https://www.ynet.co.il/news/article/byceoyvafe", "combined"),
                               ("https://www.ynet.co.il/news/article/s1nfj1drzl", "combined")])
        self.assertIn("Feed: 2 links", self.log.text())


# One real-shaped article link per section (from the live probe on 2026-11-15)
# and a link from a neighbouring section that must not be picked up.
EXAMPLES = {
    ("defense", "Maariv", "defense"): ("/news/military/article-1388506", "/news/politics/article-1388528"),
    ("defense", "Israel Hayom", "defense"): ("/news/defense/article/21852439", "/news/politics/article/21852749"),
    ("defense", "JDN", "defense"): ("https://www.jdn.co.il/news/2765329/", "https://www.jdn.co.il/category/news/1/"),
    ("defense", "Zman Israel", "defense"): ("https://www.zman.co.il/742318/", "https://www.zman.co.il/newsletter/2026-11-12/"),
    ("defense", "Davar", "defense"): ("https://www.davar1.co.il/706675/", "https://www.davar1.co.il/topic/x/"),
    ("politics", "Kan News", "combined"): ("/content/kan-news/politic/1119201/", "/content/kan-news/defense/1119265/"),
    ("politics", "Channel 13", "domestic"): ("/item/news/politics/politics/o8gxd-905461350/",
                                              "/item/news/politics/security/abc-1/"),
    ("politics", "Channel 13", "diplomatic"): ("/item/news/politics/state-policy/goffman-905460300/",
                                                "/item/news/politics/security/abc-1/"),
    ("politics", "Channel 14", "combined"): ("/article/1788327", "/archive/64850"),
    ("politics", "I24 NEWS", "combined"): ("/he/news/news/politics/artc-85da5b7c", "/he/news/news/defense-news/artc-85da5b7d"),
    ("politics", "Channel 12", "domestic"): ("/news-politics/2026_q4/Article-cd307e6b8dcd1a1027.htm",
                                             "/news-military/2026_q4/Article-aaaa.htm"),
    ("politics", "Channel 12", "diplomatic"): ("/news-diplomatic/2026_q4/Article-24c5367a0f4d1a1027.htm",
                                               "/news-military/2026_q4/Article-aaaa.htm"),
    ("politics", "Maariv", "combined"): ("/news/politics/article-1388528", "/news/military/article-1388506"),
    ("politics", "Israel Hayom", "domestic"): ("/news/politics/article/21852749", "/news/defense/article/21852439"),
    ("politics", "Israel Hayom", "diplomatic"): ("/news/geopolitics/article/21850000", "/news/defense/article/21852439"),
    ("politics", "JDN", "domestic"): ("https://www.jdn.co.il/news/2765578/", "https://www.jdn.co.il/category/news/1/"),
    ("politics", "JDN", "diplomatic"): ("https://www.jdn.co.il/news/2765579/", "https://www.jdn.co.il/category/news/1/"),
    ("politics", "Zman Israel", "combined"): ("https://www.zman.co.il/741685/", "https://www.zman.co.il/feed/609/"),
}


class EverySectionTest(unittest.TestCase):
    def test_every_html_section_has_an_example(self):
        have = {(t, s, sec["name"]) for t, sites in scraper.SITES.items() for s, site in sites.items()
                for sec in site["sections"] if not sec.get("rss_url")}
        originals = {("defense", s, "defense") for s in
                     ("Ynet", "Kan News", "Channel 13", "Channel 14", "I24 NEWS", "Channel 12")}
        self.assertEqual(have - originals - set(EXAMPLES), set())

    def test_each_section_pattern_picks_its_own_article_and_skips_the_neighbour(self):
        for (topic, source, name), (good, bad) in EXAMPLES.items():
            with self.subTest(topic=topic, source=source, section=name):
                site = scraper.SITES[topic][source]
                section = next(s for s in site["sections"] if s["name"] == name)
                html = f'<html><body><a href="{bad}">n</a><a href="{good}">a</a></body></html>'
                got = scraper._links_on_page({**section, "base": site["base"]}, html)
                expected = good if good.startswith("http") else site["base"] + good
                self.assertEqual(got, [expected])


class SitemapTest(Base):
    def test_entries_carry_their_section_and_skip_other_topics(self):
        kan = scraper.SITES["politics"]["Kan News"]
        xml = """<urlset>
          <url><loc>https://www.kan.org.il/content/kan-news/politic/1119201/</loc>
               <news:title>Politics item</news:title>
               <news:publication_date>2026-11-15T07:13:12+02:00</news:publication_date></url>
          <url><loc>https://www.kan.org.il/content/kan-news/defense/1119265/</loc>
               <news:title>Defense item</news:title></url>
        </urlset>"""
        with mock.patch.object(scraper, "fetch", lambda url, timeout=20: xml):
            entries = scraper.get_sitemap_entries("politics", "Kan News")
        self.assertEqual(list(entries), ["https://www.kan.org.il/content/kan-news/politic/1119201/"])
        e = entries["https://www.kan.org.il/content/kan-news/politic/1119201/"]
        self.assertEqual(e["title"], "Politics item")
        self.assertEqual(e["section"], kan["sections"][0]["name"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
