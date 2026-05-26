# Thumbnail Scraper Studio

Thumbnail Scraper Studio is a Windows desktop app for collecting YouTube video thumbnails with a live browser preview, live progress tracking, and partial-result recovery when a run is stopped early.

## Overview

The app is built with Tkinter and CustomTkinter and is designed for a focused scraping workflow:

- search a YouTube query
- choose how many results to collect
- choose an output folder
- watch the browser preview while scraping runs
- monitor download, verification, and failure status in real time
- stop the run without losing the data already collected

## Screenshot

The current UI uses a dark desktop layout with a settings panel on the left and a live progress panel on the right.

## Requirements

- Python 3.12 or newer
- Playwright with Chromium installed
- Windows 10 or Windows 11

## Install

Create and activate a virtual environment, then install the project dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
playwright install chromium
```

## Run the app

Start the desktop app from the project root:

```bash
python main.py
```

If you prefer, you can also launch the app through `app.py` because `main.py` simply imports and runs the application entry point.

## What the app does

- accepts a YouTube search query
- collects the selected number of results
- writes output to the folder you choose
- shows a live browser preview during scraping
- displays live progress, verification state, and failure count
- renders the scraped results in a table
- keeps partial data when the stop button is used

## Output files

The selected output folder will contain:

- `video_data.csv`
- `thumbnails/`

Each CSV row includes:

- result number
- title
- video URL
- thumbnail URL
- downloaded thumbnail path

## Build a Windows executable

To package the app as a standalone desktop executable, use the project spec file:

```bash
pip install pyinstaller
pyinstaller ThumbnailScraper.spec
```

The packaged app will be created in `dist/ThumbnailScraper.exe`. The spec file uses the Playwright runtime hook so the frozen app can find the browser cache correctly on Windows.

## Notes

- The scraper uses built-in backend defaults for timing and result targeting.
- A verification pass runs before downloading to confirm the final count.
- The download logic retries multiple thumbnail URL candidates to reduce failures.
- Playwright browsers are expected in the local Windows cache under `%LOCALAPPDATA%\ms-playwright`.

## Project Structure

- `main.py` - desktop entry point
- `app.py` - CustomTkinter UI
- `scraper.py` - scraping and download logic
- `playwright_runtime_hook.py` - runtime support for packaged builds
- `ThumbnailScraper.spec` - PyInstaller spec for Windows packaging
