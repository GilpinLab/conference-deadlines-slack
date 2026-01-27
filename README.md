# Deadlines Bot

Slack slash command to fetch ML conference deadlines from `huggingface/ai-deadlines`.

Deployed via Vercel. Endpoint: `/api/slack`

## Usage

```
/deadline <conference> [timezone]
```

**Examples:**
```
/deadline icml                      # Shows deadlines in AoE (Anywhere on Earth)
/deadline icml America/New_York     # Converts to Eastern Time
/deadline neurips Europe/London     # Converts to UK time
/deadline cvpr Asia/Tokyo           # Converts to Japan time
/deadline iclr US/Pacific           # Converts to Pacific Time
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