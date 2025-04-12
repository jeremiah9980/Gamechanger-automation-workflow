
# GameChanger Automation Pipeline

This project automates the downloading of video files and play-by-play statistics from GameChanger, processes the videos using AI editing tools, and uploads final results to Google Cloud Storage (GCS). Optionally, it can also notify users via email upon successful processing.

## 📁 Project Structure

```
automation-gamechanger-ai-pipeline/
├── downloader/
│   ├── fetch_gamechanger_assets.py      # Fetch games and assets from GameChanger API
│   └── playbyplay_scraper.py            # Scrape full play-by-play stats using Selenium
├── processor/
│   └── ai_video_editor.py               # Runs AI video editing + highlight extraction
├── uploader/
│   └── upload_to_gcs.py                 # Uploads results to Google Cloud Storage
├── notifier/
│   └── email_notify.py                  # Sends completion emails
├── workflows/
│   └── main_pipeline.py                 # Orchestrates the full pipeline
├── config/
│   └── settings.yaml                    # Config: team ID, date range, emails
├── requirements.txt                     # Python package dependencies
├── .gitignore
└── README.md
```

## 🚀 Features

- ✅ Automatically downloads game videos from GameChanger
- ✅ Pulls AI play-by-play stats (with optional CSV summaries)
- ✅ Processes raw video using AI tools (e.g. highlight clipping)
- ✅ Uploads to a shared GCS bucket
- ✅ Sends completion email to team members

## 🔧 Requirements

- Python 3.8+
- ChromeDriver + Google Chrome (for Selenium)
- Google Cloud SDK & credentials
- Gmail credentials for sending email (optional)

## 🛠️ Setup

1. Clone this repo:
    ```bash
    git clone https://github.com/jeremiah9980/Gamechanger-automation-workflow.git
    cd Gamechanger-automation-workflow
    ```

2. Install dependencies:
    ```bash
    pip install -r requirements.txt
    ```

3. Configure settings in `config/settings.yaml`

4. Run the pipeline:
    ```bash
    python workflows/main_pipeline.py
    ```

## 📬 Notifications

Configure `email_notify.py` and credentials in `.env` to enable SMTP email on job completion.

## 📦 License

MIT License.
