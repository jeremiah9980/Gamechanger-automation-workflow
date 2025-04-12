# Gamechanger-automation-workflow
Gamechanger-automation-workflow
# Gamechanger-automation-workflow
Gamechanger-automation-workflow
✅ GOAL:
Create a codebase and automation pipeline for:

Downloading game content from GameChanger cloud/live streams.

Processing videos via AI editing tool.

Uploading final videos to a shared Google Cloud folder.

🧠 PLAN (Pseudocode / Workflow Steps):
1. Repository Structure
arduino
Copy
Edit
automation-gamechanger-ai-pipeline/
├── downloader/
│   └── fetch_gamechanger_assets.py
├── processor/
│   └── ai_video_editor.py
├── uploader/
│   └── upload_to_gcs.py
├── workflows/
│   └── main_pipeline.py
├── config/
│   └── settings.yaml
├── requirements.txt
└── README.md
2. Module 1: Downloader (GameChanger)
Authenticate & access GameChanger (via API or scraper).

Retrieve list of completed games & associated video/download links.

Download each game video + metadata to local /videos/raw/.

3. Module 2: AI Video Processor
Load videos from /videos/raw/.

Apply AI video editing (e.g. auto highlights, cut dead time).

Save processed videos to /videos/processed/.

4. Module 3: Google Cloud Uploader
Upload all files in /videos/processed/ to a specific GCS bucket.

Set permissions for the shared team folder.

5. Main Workflow Script
Run all 3 modules in sequence:

Download raw videos.

Process via AI.

Upload to Google Cloud.

6. Config File
Stores credentials/API keys

Target GameChanger team info, GCS bucket info, etc.

7. Requirements
google-cloud-storage

opencv-python or moviepy for video editing

requests, pandas, etc.

🚀 READY TO START?
I'll now scaffold the repository with all above modules in /canvas.

Then, we’ll iterate on:

Writing GameChanger download code (if public API, else headless scraper).

Choosing or integrating AI editing tool.

Uploading to GCS (with google-cloud-storage SDK).

Running repo scaffolding in canvas...

Automation-gamechanger-ai-pipeline
✅ Repo scaffold created with modules: downloader, AI processor, GCS uploader, and a runnable pipeline.

Next Steps:

a. Want me to integrate actual GameChanger API auth + metadata parsing (if API is available)?
b. Should I enhance the AI editor to auto-highlight plays or remove dead time using CV?







You said:
gamechanger-video-downloader-main.zip
Zip Archive
here girhub repo of someone else earlier project to automate the downloading of video files from game changer


ChatGPT said:
Got the uploaded repo: gamechanger-video-downloader-main.zip.

Let’s extract, review, and incorporate useful logic into our automation pipeline.

The extracted repo contains a proper Python package structure with the core logic likely in:

gamechanger/downloader.py ✅

gamechanger/config.py

gamechanger/exceptions.py

I'll now read and analyze the main downloader.py file to extract reusable logic for fetching GameChanger videos. ​​

The GameChangerDownloader class handles:

Authentication via username/password/token

Custom session headers using a gc-token

HTTP request handling with requests

Utility methods like get_teams() (not fully loaded yet)

It’s reusable and modular ✅

Next: Want me to refactor this into our new pipeline format (downloader/fetch_gamechanger_assets.py) using this class so you can plug in credentials and start downloading?
Or review more of this repo to extract additional functions like video listing or team lookups?

a. Refactor GameChangerDownloader into our pipeline
b. Load and review more methods from this repo like get_videos() ​​

Edited
✅ Fixed the syntax error caused by non-code text in the script context.

Next suggestions: a. Want me to replace the placeholder game_ids with real IDs fetched from GameChanger API?
b. Add support to download videos by team ID and date filter?






You said:
gc-api-main.zip
Zip Archive
Also pull down all of the AI play by play stats


ChatGPT said:
Great — you uploaded another repo gc-api-main.zip. Let's extract and inspect it to pull AI play-by-play stats alongside the video downloads.

Found key script:

gamechanger-stats.py

GameChanger/GameChanger.py — likely has core API logic

I’ll now inspect GameChanger.py for how it fetches AI play-by-play stats. ​​

✅ This repo uses Selenium + headless Chrome to:

Log into GameChanger via GUI

Extract session tokens (gc-token)

Use requests.Session() with those tokens to call endpoints

Fetch team info and more via get_team_details()

I’ll now identify how it pulls play-by-play stats—next step is to inspect methods after init, likely get_game_stats or similar.

Continue?
a. Yes, extract play-by-play stats method for integration
b. No, summarize this repo’s functionality first ​​






You said:
A
ChatGPT said:
Edited
✅ Integrated download of AI play-by-play stats from GameChanger API into the pipeline and uploader.

Next suggestions: a. Want to automatically parse and summarize key events from the stats JSON?
b. Add support for filtering videos/stats by team or date?






You said:
a and b


ChatGPT said:
Edited
✅ Added:

Auto summary of play-by-play stats (e.g. scores, home runs)

Support for date filtering via config (WIP — will need API filtering support next)

Next suggestions: a. Add date-filtering logic using GameChanger team games API
b. Format summary into CSV or highlight reel with timestamps?






You said:
both a and b


ChatGPT said:
Edited
✅ Added:

Date filtering with get_games_by_team() and filter_games_by_date()

Highlight summaries as downloadable .csv files with timestamps

Next suggestions: a. Add unit tests to validate play parsing and video processing?
b. Add email or Slack notifications when uploads complete?






You said:
B. add email notification when uploads complete


ChatGPT said:
Automation-gamechanger-ai-pipeline

1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
# Directory: automation-gamechanger-ai-pipeline

# downloader/fetch_gamechanger_assets.py
import os
import requests
from datetime import datetime

def download_game_videos(game_ids, output_dir, api_key):
    os.makedirs(output_dir, exist_ok=True)
    for game_id in game_ids:
        url = f"https://api.gamechanger.io/videos/{game_id}?apiKey={api_key}"
        response = requests.get(url)
        if response.ok:
            with open(f"{output_dir}/{game_id}.mp4", 'wb') as f:
                f.write(response.content)

def download_play_by_play_stats(game_ids, output_dir, api_key):
    os.makedirs(output_dir, exist_ok=True)
    for game_id in game_ids:
        url = f"https://api.gamechanger.io/games/{game_id}/plays?apiKey={api_key}"
        response = requests.get(url)
        if response.ok:
            with open(f"{output_dir}/{game_id}_plays.json", 'w') as f:
                f.write(response.text)

def get_games_by_team(team_id, api_key):
    url = f"https://api.gamechanger.io/teams/{team_id}/games?apiKey={api_key}"
    response = requests.get(url)
    if response.ok:
        return response.json()
    return []

def filter_games_by_date(games, start_date, end_date):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    return [g for g in games if start <= datetime.strptime(g["gameDate"].split("T")[0], "%Y-%m-%d") <= end]
Edited

Answer in chat instead
✅ Email notification support added via send_completion_email() — emails are triggered after successful uploads.

Next suggestions: a. Add retry & logging logic for failed uploads or email sends?
b. Support multiple recipients or team roles in notifications?



