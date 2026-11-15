"""
Live check of every section in the registry: network only, no database.

    python check_sections.py                     # every topic, source and section
    python check_sections.py --topic politics
    python check_sections.py --topic defense Maariv

For each section it reads page 1 (or the feed), counts the article links and
scrapes the first one. Exits 1 if any section lists no links or its first
article cannot be parsed, so it can guard a deploy.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.scraper import SITES, TOPICS, get_links, scrape_article  # noqa: E402


def check(topic, source):
    """[(section, links, title, chars, problem)] for one source."""
    site = SITES[topic][source]
    out = []
    for section in site["sections"]:
        one = {**site, "sections": [section]}
        try:
            # walk only this section, page 1
            SITES[topic][source] = one
            links = [u for u, _ in get_links(topic, source, known=None, max_pages=1)]
        except Exception as e:
            out.append((section["name"], 0, "", 0, f"{type(e).__name__}: {e}"[:120]))
            continue
        finally:
            SITES[topic][source] = site
        if not links:
            out.append((section["name"], 0, "", 0, "no links"))
            continue
        article = scrape_article(source, links[0])
        if not article:
            out.append((section["name"], len(links), "", 0, f"first article failed: {links[0]}"))
        else:
            out.append((section["name"], len(links), article["title"], len(article["content"]), ""))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*")
    ap.add_argument("--topic", choices=TOPICS)
    args = ap.parse_args()
    failed = 0
    for topic in [args.topic] if args.topic else TOPICS:
        for source in args.sources or list(SITES[topic]):
            if source not in SITES[topic]:
                continue
            for name, n, title, chars, problem in check(topic, source):
                mark = "FAIL" if problem else "ok  "
                failed += bool(problem)
                detail = problem or f"{chars:>6} chars | {title[:60]}"
                print(f"{mark} {topic:<8} {source:<13} {name:<10} {n:>3} links | {detail}", flush=True)
    print(f"\n{failed} section(s) failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
