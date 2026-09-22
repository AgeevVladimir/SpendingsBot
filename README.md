# SpendingsBot

Telegram bot to track shared trip spendings in EUR and settle up at the end (Splitwise-like flow).

This repository uses Python and Google Sheets. The old JavaScript implementation has been removed.

## Features

- Create a trip
- Add members
- Add spendings (amount, date, description, payer, who shares)
- List spendings
- Close trip and calculate who owes whom
- Persist trip data in Google Sheets worksheets keyed by Telegram `chat_id`

## Python implementation layout

- [main.py](main.py) — app entrypoint
- [spendingsbot/bot.py](spendingsbot/bot.py) — Telegram command handlers
- [spendingsbot/repository.py](spendingsbot/repository.py) — trip storage API and in-memory test workbook
- [spendingsbot/google_sheets.py](spendingsbot/google_sheets.py) — Google Sheets adapter
- [spendingsbot/parsers.py](spendingsbot/parsers.py) — command parsing helpers
- [spendingsbot/settlement.py](spendingsbot/settlement.py) — settlement algorithm

## Google Sheets setup

1. Open Google Cloud Console and create a project.
2. Go to **APIs & Services** → **Library**.
3. Enable **Google Sheets API**.
4. Go to **IAM & Admin** → **Service Accounts**.
5. Create a service account for the bot.
6. Open that service account and create a JSON key.
7. Download the JSON file.
8. Create a Google Sheet for the bot data.
9. Copy the spreadsheet ID from the URL:

	`https://docs.google.com/spreadsheets/d/<SPREADSHEET_ID>/edit`

10. Share the sheet with the service account email address. It usually looks like:

	`<name>@<project-id>.iam.gserviceaccount.com`

Without that share step, the bot will authenticate successfully but still fail to open the spreadsheet.

The app creates or updates these worksheets automatically:

- `trips`
- `members`
- `spendings`

## Environment variables

Copy [.env.example](.env.example) into `.env` and fill it in.

Required:

- `BOT_TOKEN`
- `GOOGLE_SHEETS_SPREADSHEET_ID`
- one of:
	- `GOOGLE_SERVICE_ACCOUNT_FILE`
	- `GOOGLE_SERVICE_ACCOUNT_JSON`

Recommended usage:

- Local machine: set `GOOGLE_SERVICE_ACCOUNT_FILE` to the downloaded JSON file path.
- Render: set `GOOGLE_SERVICE_ACCOUNT_JSON` to the full JSON content as a secret env var.

Optional:

- `GOOGLE_SHEETS_TRIPS_WORKSHEET`
- `GOOGLE_SHEETS_MEMBERS_WORKSHEET`
- `GOOGLE_SHEETS_SPENDINGS_WORKSHEET`

## Run locally

1. Copy [.env.example](.env.example) to `.env`.
2. Fill in:
	- `BOT_TOKEN`
	- `GOOGLE_SHEETS_SPREADSHEET_ID`
	- `GOOGLE_SERVICE_ACCOUNT_FILE` or `GOOGLE_SERVICE_ACCOUNT_JSON`
3. Make sure the spreadsheet is shared with the service account email.
4. Create a Python environment, install dependencies, and start the bot:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

When the process keeps running without errors, open Telegram and test:

```text
/start
/newtrip Weekend in Berlin
/addmember Alice
/addmember Bob
/addspending 10; 2026-09-20; Taxi; Alice; Alice,Bob
/spendings
/closetrip
```

If Google credentials or spreadsheet sharing are wrong, the bot will fail on startup or on its first sheet access.

## Run tests

```bash
python -m pytest
```

## Run in Docker locally

Build and run the container:

```bash
docker build -t spendingsbot .
docker run --rm --env-file .env spendingsbot
```

If you use `GOOGLE_SERVICE_ACCOUNT_FILE`, mount the credentials file into the container and point the env var at that in-container path instead.

## Commands

- `/newtrip <trip name>`
- `/addmember <name>`
- `/members`
- `/addspending <amount>; <date YYYY-MM-DD>; <description>; <payer>; <shared1,shared2>`
- `/spendings`
- `/closetrip`

Notes:

- Use quotes for member names that contain commas, e.g. `"Alice, A",Bob`
- `;` is reserved as command separator in `/addspending`
- The implementation preserves the legacy `sharedWith` parser behavior used by the previous JavaScript version

## Testing strategy

Python tests cover:

- command parsing parity
- settlement math parity
- repository lifecycle behavior
- support for legacy pipe-delimited `sharedWith` values

## Deploy later to Render with Docker

This repository already includes:

- [Dockerfile](Dockerfile)
- [.dockerignore](.dockerignore)
- [render.yaml](render.yaml)

Recommended Render setup:

- deploy as a **Worker**, not a Web Service
- use `GOOGLE_SERVICE_ACCOUNT_JSON` instead of a credentials file
- keep `BOT_TOKEN` and spreadsheet values as secret env vars

Typical Render flow:

1. Push this repository to GitHub.
2. Create a new Render service from the repo.
3. Use the included [render.yaml](render.yaml), or create a Worker manually.
4. Set secret env vars:
	- `BOT_TOKEN`
	- `GOOGLE_SHEETS_SPREADSHEET_ID`
	- `GOOGLE_SERVICE_ACCOUNT_JSON`
5. Deploy.

Because the bot uses polling, no HTTP port or persistent disk is required.
