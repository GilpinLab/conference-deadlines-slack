# Deadlines Bot

Slack slash command to fetch ML conference deadlines from `huggingface/ai-deadlines`.

Deployed via Vercel. Endpoint: `/api/slack`

## Usage

```
/deadline <conference> [timezone]   Show deadlines for a conference
/deadline list                      List all supported conferences
/deadline help                      Show help message
```

**Examples:**
```
/deadline icml                      # Shows deadlines in AoE (Anywhere on Earth)
/deadline icml America/Chicago      # Converts to Central Time
/deadline neurips US/Pacific        # Converts to Pacific Time
/deadline list                      # Shows all available conferences
```

## Features

- Shows all deadline types: abstract, paper submission, supplementary, reviews, rebuttal, notification, camera-ready
- Marks passed deadlines and highlights the next upcoming one
- Displays relative time (e.g., "in 5 days")
- Optional timezone conversion from AoE to your local time

## Supported Conferences

```
aaai, acl, cvpr, eccv, emnlp, icassp, iccv, iclr, icml,
ijcai, interspeech, kdd, neurips (or nips), recsys, wacv, www
```

## Configuration

**Optional environment variables (set in Vercel dashboard):**
- `DEFAULT_TIMEZONE`: Default timezone for all queries (e.g., `America/New_York`)
- `SLACK_SIGNING_SECRET`: Slack signing secret for request verification
- `LOG_LEVEL`: Logging level (default: `INFO`)