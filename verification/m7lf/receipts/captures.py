"""M7LF: capture the saved Jobs details after the counted walks, without another model call."""

from playwright.sync_api import sync_playwright
from walk import ROOT, api, jobs_module

with sync_playwright() as play:
    browser = play.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1600, "height": 1500})
    snapshot = api("/v1/jobs")
    for run in ("1", "2", "3", "g1", "g2", "g3"):
        if run.startswith("g"):
            name = f"run-{run}-declared"
            filename = "FL-209-detail.png"
        else:
            receipt = next(
                j
                for j in snapshot["jobs"]
                if j["definition"]["name"].startswith(f"forecast-lf-{run}-")
                and any(
                    r["job_id"] == j["job_id"] and r["state"] == "completed"
                    for r in snapshot["runs"]
                )
            )
            name = receipt["definition"]["name"]
            filename = "FL-185-detail.png"
        jobs = jobs_module(page)
        jobs.get_by_role("button", name=name, exact=True).click()
        jobs.locator("aside").scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        page.locator('[data-testid="rack-plugin-frame-jobs"]').screenshot(
            path=str(ROOT / f"run-{run}" / filename),
        )
    browser.close()
