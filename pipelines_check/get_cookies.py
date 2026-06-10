from playwright.sync_api import sync_playwright


def get_human_clearance():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        print("Opening website... Please click the CAPTCHA manually!")
        page.goto("https://www.mako.co.il/news-military")

        # Gives you 45 seconds to solve the CAPTCHA and let the page load
        page.wait_for_timeout(45000)

        # Save your cookies and local storage to a file!
        context.storage_state(path="state.json")
        print("Clearance saved to state.json! You can close this now.")

        browser.close()


if __name__ == "__main__":
    get_human_clearance()