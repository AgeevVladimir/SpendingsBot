# SpendingsBot

Telegram bot to track shared trip spendings in EUR and settle up at the end (Splitwise-like flow).

## Features

- Create a trip
- Add members
- Add spendings (amount, date, description, payer, who shares)
- List spendings
- Close trip and calculate who owes whom
- Store all trip data in an **Excel-compatible CSV file** (`data/trip_<chatId>.csv`) — no database

## Run locally

```bash
npm install
BOT_TOKEN=<your_telegram_bot_token> npm start
```

Optional environment variables:

- `DATA_DIR` — folder for CSV files (default: `./data`)

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

## Render deployment notes

For Render, configure:

1. Environment variable `BOT_TOKEN`
2. Persistent disk mounted to a path (for example `/var/data`)
3. Environment variable `DATA_DIR=/var/data`

This keeps trip files persistent between deploys without using a database.
