# Thumbnail Generator Model Data

Scrapes YouTube search results, collects thumbnail URLs, downloads the images, and saves the captured data to CSV.

## Requirements

- Python 3.12+
- Playwright installed with Chromium available

If you are setting this up for the first time, install the project dependencies and browser binaries:

```bash
pip install -e .
playwright install chromium
```

## Run

```bash
python main.py
```

The script will prompt for:

- the search query
- the number of results to collect

If you press Enter without typing a query, it uses `best ai tools`.
If you enter an invalid result count, it falls back to `20`.

## Output

The script writes files into `data/`:

- `data/video_data.csv` contains the collected rows
- `data/thumbnails/` contains the downloaded thumbnail images

Each CSV row includes:

- result number
- title
- video URL
- thumbnail URL
- downloaded thumbnail file path
