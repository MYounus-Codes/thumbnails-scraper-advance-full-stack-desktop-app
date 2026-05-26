from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, urlparse
from uuid import uuid4
import csv
import os
import re
import tempfile

import requests
from playwright.sync_api import sync_playwright


def _playwright_cache_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local")
    return Path(local_app_data) / "ms-playwright"


os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_playwright_cache_dir())


ProgressCallback = Callable[[str, dict[str, Any]], None]
LogCallback = Callable[[str], None]


DATA_CSV_NAME = "video_data.csv"
THUMBNAIL_DIR_NAME = "thumbnails"
DEFAULT_RESULT_COUNT = 50
DEFAULT_VERIFICATION_ROUNDS = 8


@dataclass(slots=True)
class ScrapeConfig:
    query: str
    output_dir: Path
    result_count: int = DEFAULT_RESULT_COUNT
    headless: bool = True
    scroll_wait_ms: int = 2200
    initial_wait_ms: int = 2500
    max_idle_rounds: int = 6
    viewport_width: int = 1400
    viewport_height: int = 1400


@dataclass(slots=True)
class ScrapeOutcome:
    query: str
    requested: int
    collected: int
    downloaded: int
    failed: int
    verified: bool
    stopped_early: bool
    output_dir: Path
    csv_path: Path
    thumbnail_dir: Path
    results: list[dict[str, str]]


@dataclass(slots=True)
class ScraperState:
    results: list[dict[str, str]]
    seen: set[str]
    collected: int = 0
    stagnant_rounds: int = 0
    scroll_round: int = 0
    stopped_early: bool = False


def _latest_existing_path(patterns: list[str]) -> Path | None:
    cache_dir = _playwright_cache_dir()
    matches: list[Path] = []

    for pattern in patterns:
        matches.extend(path for path in cache_dir.glob(pattern) if path.exists())

    if not matches:
        return None

    return sorted(matches, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def _candidate_browser_paths() -> list[Path]:
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    cache_dir = _playwright_cache_dir()

    cached_browser_candidates = [
        _latest_existing_path([
            "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
            "chromium_headless_shell-*/chrome-headless-shell/chrome-headless-shell.exe",
        ]),
        _latest_existing_path([
            "chromium-*/chrome-win64/chrome.exe",
            "chromium-*/chrome-win/chrome.exe",
        ]),
    ]

    candidates = [
        *[path for path in cached_browser_candidates if path is not None],
        Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    return [candidate for candidate in candidates if candidate.exists()]


def _launch_browser(playwright, headless: bool):
    browser_paths = _candidate_browser_paths()
    if browser_paths:
        return playwright.chromium.launch(headless=headless, executable_path=str(browser_paths[0]))

    try:
        return playwright.chromium.launch(headless=headless, channel="msedge")
    except Exception:
        pass

    try:
        return playwright.chromium.launch(headless=headless, channel="chrome")
    except Exception:
        pass

    raise RuntimeError(
        "No usable Chromium browser was found. Install Playwright Chromium with `playwright install chromium` "
        "or install Microsoft Edge / Google Chrome."
    )


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")
    return value.lower() or "thumbnail"


def _extract_video_id(video_url: str) -> str:
    if not video_url:
        return ""

    if video_url.startswith("/watch"):
        parsed = urlparse(f"https://www.youtube.com{video_url}")
    else:
        parsed = urlparse(video_url)

    if parsed.hostname in {"youtu.be"}:
        return parsed.path.strip("/")

    query_id = parse_qs(parsed.query).get("v", [""])[0]
    if query_id:
        return query_id

    match = re.search(r"(?:v=|/shorts/|/embed/|/watch\?v=)([A-Za-z0-9_-]{6,})", video_url)
    return match.group(1) if match else ""


def _thumbnail_candidates(video_url: str, thumbnail_url: str) -> list[str]:
    candidates: list[str] = []

    if thumbnail_url:
        candidates.append(thumbnail_url)

    video_id = _extract_video_id(video_url)
    if not video_id:
        return candidates

    for size in ("maxresdefault", "sddefault", "hqdefault", "mqdefault", "default"):
        candidates.append(f"https://i.ytimg.com/vi/{video_id}/{size}.jpg")

    return list(dict.fromkeys(candidates))


def _emit(progress_cb: ProgressCallback | None, stage: str, **metrics: object) -> None:
    if progress_cb is not None:
        progress_cb(stage, metrics)


def _capture_preview(page, preview_path: Path, progress_cb: ProgressCallback | None, label: str) -> None:
    try:
        page.screenshot(path=str(preview_path), full_page=False)
        _emit(progress_cb, "Preview", preview_path=str(preview_path), preview_label=label)
    except Exception:
        pass


def _log(log_cb: LogCallback | None, message: str) -> None:
    if log_cb is not None:
        log_cb(message)


def _build_search_url(query: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"


def collect_results(page, state: ScraperState, progress_cb: ProgressCallback | None = None) -> list[dict[str, str]]:
    cards = page.locator("ytd-video-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer")
    new_results: list[dict[str, str]] = []
    cards_count = cards.count()

    for index in range(cards_count):
        card = cards.nth(index)
        title_link = card.locator("a#video-title").first
        thumbnail_link = card.locator("a#thumbnail").first
        image = card.locator("img").first

        title = ""
        video_url = ""
        thumbnail_url = ""

        try:
            title = (title_link.get_attribute("title") or title_link.inner_text() or "").strip()
        except Exception:
            title = ""

        try:
            video_url = (
                title_link.get_attribute("href")
                or thumbnail_link.get_attribute("href")
                or ""
            ).strip()
        except Exception:
            video_url = ""

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

        if not thumbnail_url and video_url:
            candidates = _thumbnail_candidates(video_url, thumbnail_url)
            thumbnail_url = candidates[0] if candidates else ""

        if not title and not video_url and not thumbnail_url:
            continue

        dedupe_key = video_url or f"{title}|{thumbnail_url}"
        if dedupe_key in state.seen:
            continue

        state.seen.add(dedupe_key)
        new_results.append(
            {
                "title": title,
                "video_url": video_url,
                "thumbnail_url": thumbnail_url,
                "thumbnail_candidates": "|".join(_thumbnail_candidates(video_url, thumbnail_url)),
            }
        )

    state.results.extend(new_results)
    state.collected = len(state.results)
    _emit(progress_cb, "Scraping", cards=cards_count, new=len(new_results), unique=state.collected)
    return new_results


def load_results(
    page,
    config: ScrapeConfig,
    state: ScraperState,
    progress_cb: ProgressCallback | None = None,
    stop_event: Event | None = None,
    preview_path: Path | None = None,
) -> list[dict[str, str]]:
    page.wait_for_selector("ytd-video-renderer, ytd-grid-video-renderer, ytd-compact-video-renderer")
    page.wait_for_timeout(config.initial_wait_ms)

    collect_results(page, state, progress_cb)
    if preview_path is not None:
        _capture_preview(page, preview_path, progress_cb, "Initial results")

    while state.collected < config.result_count:
        if stop_event is not None and stop_event.is_set():
            state.stopped_early = True
            break

        state.scroll_round += 1
        _emit(
            progress_cb,
            "Scrolling",
            round=state.scroll_round,
            unique=state.collected,
            target=config.result_count,
            stagnant_rounds=state.stagnant_rounds,
        )

        before_count = state.collected
        page.mouse.wheel(0, 7000)
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(config.scroll_wait_ms)

        new_results = collect_results(page, state, progress_cb)
        if preview_path is not None:
            _capture_preview(page, preview_path, progress_cb, f"Scroll {state.scroll_round}")
        if new_results:
            state.stagnant_rounds = 0
            _emit(progress_cb, "Progress", collected=state.collected, target=config.result_count)
        else:
            state.stagnant_rounds += 1

        if state.collected >= config.result_count:
            break

        if state.collected == before_count and state.stagnant_rounds >= config.max_idle_rounds:
            state.stopped_early = True
            break

    return state.results[: config.result_count]


def verify_results(
    page,
    config: ScrapeConfig,
    state: ScraperState,
    progress_cb: ProgressCallback | None = None,
    stop_event: Event | None = None,
    preview_path: Path | None = None,
) -> bool:
    verification_rounds = 0
    idle_rounds = 0
    max_verification_rounds = max(DEFAULT_VERIFICATION_ROUNDS, config.max_idle_rounds * 2)

    while state.collected < config.result_count and verification_rounds < max_verification_rounds:
        if stop_event is not None and stop_event.is_set():
            state.stopped_early = True
            break

        verification_rounds += 1
        _emit(
            progress_cb,
            "Verifying",
            round=verification_rounds,
            unique=state.collected,
            target=config.result_count,
            stagnant_rounds=idle_rounds,
        )

        before_count = state.collected
        page.mouse.wheel(0, 7000)
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(max(config.scroll_wait_ms, 2000))

        new_results = collect_results(page, state, progress_cb)
        if preview_path is not None:
            _capture_preview(page, preview_path, progress_cb, f"Verify {verification_rounds}")
        if new_results:
            idle_rounds = 0
            _emit(progress_cb, "Progress", collected=state.collected, target=config.result_count)
        else:
            idle_rounds += 1

        if state.collected >= config.result_count:
            break

        if state.collected == before_count and idle_rounds >= max_verification_rounds:
            break

    verified = state.collected >= config.result_count
    _emit(progress_cb, "Verified", verified=verified, collected=state.collected, target=config.result_count)
    return verified


def download_thumbnail(url: str, destination: Path) -> bool:
    if not url:
        return False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }

    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30, headers=headers)
            response.raise_for_status()
            destination.write_bytes(response.content)
            return True
        except Exception:
            if attempt == 2:
                return False

    return False


def download_thumbnails(
    results: list[dict[str, str]],
    thumbnail_dir: Path,
    progress_cb: ProgressCallback | None = None,
    stop_event: Event | None = None,
) -> tuple[list[dict[str, str]], int, int]:
    thumbnail_dir.mkdir(parents=True, exist_ok=True)

    total = len(results)
    downloaded = 0
    failed = 0

    for index, result in enumerate(results, start=1):
        if stop_event is not None and stop_event.is_set():
            break

        candidate_urls = [
            candidate.strip()
            for candidate in str(result.get("thumbnail_candidates", "")).split("|")
            if candidate.strip()
        ]
        if not candidate_urls and result.get("thumbnail_url", ""):
            candidate_urls = [result.get("thumbnail_url", "")]

        if not candidate_urls:
            result["thumbnail_file"] = ""
            failed += 1
            _emit(progress_cb, "Downloading", downloaded=downloaded, failed=failed, total=total, current=index)
            continue

        title_slug = slugify(result.get("title", "thumbnail"))
        extension = Path(candidate_urls[0].split("?")[0]).suffix or ".jpg"
        filename = f"{index:03d}_{title_slug}_{uuid4().hex[:8]}{extension}"
        destination = thumbnail_dir / filename

        success = False
        for thumbnail_url in candidate_urls:
            if download_thumbnail(thumbnail_url, destination):
                success = True
                break

        if success:
            result["thumbnail_file"] = str(destination.as_posix())
            downloaded += 1
        else:
            result["thumbnail_file"] = ""
            failed += 1

        _emit(progress_cb, "Downloading", downloaded=downloaded, failed=failed, total=total, current=index)

    return results, downloaded, failed


def save_to_csv(search_query: str, result_count: int, results: list[dict[str, str]], csv_path: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8") as csvfile:
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


def run_scrape(
    config: ScrapeConfig,
    progress_cb: ProgressCallback | None = None,
    log_cb: LogCallback | None = None,
    stop_event: Event | None = None,
) -> ScrapeOutcome:
    output_dir = config.output_dir.expanduser().resolve()
    thumbnail_dir = output_dir / THUMBNAIL_DIR_NAME
    csv_path = output_dir / DATA_CSV_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    _emit(progress_cb, "Starting", query=config.query, target=config.result_count, output_dir=str(output_dir))
    _log(log_cb, f"Opening YouTube search for: {config.query}")

    state = ScraperState(results=[], seen=set())
    search_url = _build_search_url(config.query)
    preview_path = Path(tempfile.gettempdir()) / f"thumbnail_scraper_preview_{uuid4().hex}.png"

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, config.headless)
        page = browser.new_page(viewport={"width": config.viewport_width, "height": config.viewport_height})
        page.goto(search_url, wait_until="domcontentloaded")
        load_results(page, config, state, progress_cb=progress_cb, stop_event=stop_event, preview_path=preview_path)
        verified = verify_results(page, config, state, progress_cb=progress_cb, stop_event=stop_event, preview_path=preview_path)
        results = state.results[: config.result_count]
        browser.close()

    _log(log_cb, f"Collected {len(results)} unique results.")
    _emit(progress_cb, "Downloading", downloaded=0, failed=0, total=len(results), current=0)

    results, downloaded, failed = download_thumbnails(results, thumbnail_dir, progress_cb=progress_cb, stop_event=stop_event)
    save_to_csv(config.query, config.result_count, results, csv_path)

    _emit(progress_cb, "Saving", csv_path=str(csv_path), thumbnail_dir=str(thumbnail_dir))
    _log(log_cb, f"Saved CSV to {csv_path}")

    return ScrapeOutcome(
        query=config.query,
        requested=config.result_count,
        collected=len(results),
        downloaded=downloaded,
        failed=failed,
        verified=verified,
        stopped_early=(bool(stop_event.is_set()) if stop_event is not None else False) or len(results) < config.result_count,
        output_dir=output_dir,
        csv_path=csv_path,
        thumbnail_dir=thumbnail_dir,
        results=results,
    )
