# Thumbnail Scraper Studio

This project now ships as a desktop application with a premium dark UI built on Tkinter + CustomTkinter. It lets you enter a query, choose an output folder, view the live browser preview and results table, and stop the run while keeping partial results.

## Requirements

- Python 3.12+
- Playwright installed with Chromium available

Install the app dependencies and browser binaries:

```bash
pip install -e .
playwright install chromium
```

## Run the app

```bash
python main.py
```

The app includes:

- query input
- results count input
- output folder picker
- headless browser toggle
- live browser preview while scraping
- live progress, verification, and activity log
- results table that fills after the scrape finishes
- Stop button that saves partial data

The scraper uses backend defaults for timing, runs a verification pass before downloading to confirm the final count, and falls back to multiple thumbnail URL candidates to reduce download failures.

## Output

The app saves these items into the folder you choose:

- `video_data.csv`
- `thumbnails/`

Each CSV row includes:

- result number
- title
- video URL
- thumbnail URL
- downloaded thumbnail file path

## Make it a standalone Windows app

If you want an icon you can launch outside VS Code, package the app into an executable and create a desktop shortcut to it.

```bash
pip install pyinstaller
pyinstaller ThumbnailScraper.spec
```

The EXE will be in `dist/ThumbnailScraper.exe`. Create a desktop shortcut to that file and you can launch the app directly from the desktop without opening VS Code.
