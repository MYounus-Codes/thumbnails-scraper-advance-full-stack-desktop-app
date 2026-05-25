from pathlib import Path
from urllib.parse import quote_plus
from uuid import uuid4
import csv
import re

import requests
from playwright.sync_api import sync_playwright


DATA_DIR = Path("data")
THUMBNAIL_DIR = DATA_DIR / "thumbnails"
CSV_PATH = DATA_DIR / "video_data.csv"


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")
    return value.lower() or "thumbnail"


def get_user_input() -> tuple[str, int]:
    search_query = input("Enter the search query: ").strip() or "best ai tools"
    raw_count = input("Enter the number of results to collect: ").strip()
    try:
        result_count = max(1, int(raw_count))
    except ValueError:
        result_count = 20
    return search_query, result_count


def collect_results(page, target_count: int) -> list[dict[str, str]]:
    cards = page.locator("ytd-video-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer")
    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for index in range(cards.count()):
        card = cards.nth(index)
        title_link = card.locator("a#video-title").first
        thumbnail_link = card.locator("a#thumbnail").first
        image = card.locator("img").first

        title = ""
        href = ""
        thumbnail_url = ""

        try:
            title = (title_link.get_attribute("title") or title_link.inner_text() or "").strip()
        except Exception:
            title = ""

        try:
            href = (
                title_link.get_attribute("href")
                or thumbnail_link.get_attribute("href")
                or ""
            ).strip()
        except Exception:
            href = ""

        try:
            thumbnail_url = (
                image.get_attribute("src")
                or image.get_attribute("data-thumb")
                or image.get_attribute("data-thumb-url")
                or ""
            ).strip()
        except Exception:
            thumbnail_url = ""

        if thumbnail_url.startswith("//"):
            thumbnail_url = f"https:{thumbnail_url}"

        if not title and not href and not thumbnail_url:
            continue

        dedupe_key = href or f"{title}|{thumbnail_url}"
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        results.append(
            {
                "title": title,
                "video_url": href,
                "thumbnail_url": thumbnail_url,
            }
        )

        if len(results) >= target_count:
            break

    return results


def load_results(page, target_count: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    stagnant_rounds = 0
    max_rounds = max(10, target_count * 2)

    page.wait_for_selector("ytd-video-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer")

    for _ in range(max_rounds):
        results = collect_results(page, target_count)
        if len(results) >= target_count:
            return results[:target_count]

        previous_count = len(results)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1200)
        page.evaluate("window.scrollBy(0, window.innerHeight)")
        page.wait_for_timeout(1200)

        refreshed_results = collect_results(page, target_count)
        if len(refreshed_results) <= previous_count:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0

        results = refreshed_results
        if stagnant_rounds >= 3:
            break

    return results[:target_count]


def download_thumbnail(url: str, destination: Path) -> bool:
    if not url:
        return False

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return True


def download_thumbnails(results: list[dict[str, str]]) -> None:
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

    for index, result in enumerate(results, start=1):
        thumbnail_url = result.get("thumbnail_url", "")
        if not thumbnail_url:
            result["thumbnail_file"] = ""
            continue

        title_slug = slugify(result.get("title", "thumbnail"))
        extension = Path(thumbnail_url.split("?")[0]).suffix or ".jpg"
        filename = f"{index:03d}_{title_slug}_{uuid4().hex[:8]}{extension}"
        destination = THUMBNAIL_DIR / filename

        try:
            download_thumbnail(thumbnail_url, destination)
            result["thumbnail_file"] = str(destination.as_posix())
        except Exception as exc:
            result["thumbnail_file"] = ""
            print(f"Failed to download thumbnail {index}: {exc}")


def save_to_csv(search_query: str, result_count: int, results: list[dict[str, str]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with CSV_PATH.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Search Query", search_query])
        writer.writerow(["Requested Results", result_count])
        writer.writerow([])
        writer.writerow(["Result #", "Title", "Video URL", "Thumbnail URL", "Thumbnail File"])
        for index, result in enumerate(results, start=1):
            writer.writerow(
                [
                    index,
                    result.get("title", ""),
                    result.get("video_url", ""),
                    result.get("thumbnail_url", ""),
                    result.get("thumbnail_file", ""),
                ]
            )


def main() -> None:
    search_query, result_count = get_user_input()
    url = f"https://www.youtube.com/results?search_query={quote_plus(search_query)}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1400})
        page.goto(url, wait_until="domcontentloaded")

        results = load_results(page, result_count)
        browser.close()

    print(f"Collected {len(results)} results.")

    download_thumbnails(results)
    print(f"Downloaded thumbnails to {THUMBNAIL_DIR}.")

    save_to_csv(search_query, result_count, results)
    print(f"Data saved to {CSV_PATH}.")


if __name__ == "__main__":
    main()
