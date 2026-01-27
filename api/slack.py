import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import requests
import yaml

LOGGER = logging.getLogger("conf_deadlines_slack")
if not LOGGER.handlers:
    _level = os.getenv("LOG_LEVEL", "INFO").upper()
    LOGGER.setLevel(getattr(logging, _level, logging.INFO))
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    LOGGER.addHandler(_h)

MAX_BODY_BYTES = 4096
MAX_TEXT_CHARS = 128

AOE_TZ = ZoneInfo("Etc/GMT+12")

CONFERENCE_MAPPINGS = {
    "iclr": "ICLR",
    "nips": "NeurIPS",
    "neurips": "NeurIPS",
    "cvpr": "CVPR",
    "icml": "ICML",
    "aaai": "AAAI",
    "acl": "ACL",
    "emnlp": "EMNLP",
    "iccv": "ICCV",
    "eccv": "ECCV",
    "ijcai": "IJCAI",
    "kdd": "KDD",
    "www": "WWW",
    "recsys": "RecSys",
    "wacv": "WACV",
    "icassp": "ICASSP",
    "interspeech": "Interspeech",
}

ALLOWED_KEYS = set(CONFERENCE_MAPPINGS.keys())

DEADLINE_TYPE_ORDER = ["abstract", "paper", "supplementary", "review_release", "rebuttal_end", "notification", "camera_ready"]
DEADLINE_TYPE_LABELS = {
    "abstract": "Abstract",
    "paper": "Paper Submission",
    "submission": "Paper Submission",
    "supplementary": "Supplementary",
    "review_release": "Reviews Released",
    "rebuttal_end": "Rebuttal Due",
    "notification": "Notification",
    "camera_ready": "Camera Ready",
}
DEADLINE_TYPE_ALIASES = {"submission": "paper"}


def fetch_conference_data():
    """Fetch conference data from huggingface/ai-deadlines repo."""
    conferences = {}
    conference_files = list(ALLOWED_KEYS)
    for conf in conference_files:
        url = f"https://raw.githubusercontent.com/huggingface/ai-deadlines/main/src/data/conferences/{conf}.yml"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = yaml.safe_load(r.text)
            if data:
                conferences[conf] = data
    return conferences if conferences else None


def parse_deadline_datetime(date_str: str) -> datetime | None:
    """Parse a deadline string into a datetime object."""
    if not date_str:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def format_relative_time(dt: datetime, now: datetime) -> str:
    """Format time relative to now (e.g., 'in 3 days' or '2 days ago')."""
    diff = dt - now
    total_seconds = diff.total_seconds()
    
    if abs(total_seconds) < 60:
        return "now"
    
    is_future = total_seconds > 0
    abs_seconds = abs(total_seconds)
    
    if abs_seconds < 3600:
        minutes = int(abs_seconds / 60)
        unit = "minute" if minutes == 1 else "minutes"
        return f"in {minutes} {unit}" if is_future else f"{minutes} {unit} ago"
    elif abs_seconds < 86400:
        hours = int(abs_seconds / 3600)
        unit = "hour" if hours == 1 else "hours"
        return f"in {hours} {unit}" if is_future else f"{hours} {unit} ago"
    else:
        days = int(abs_seconds / 86400)
        unit = "day" if days == 1 else "days"
        return f"in {days} {unit}" if is_future else f"{days} {unit} ago"


def get_target_timezone(tz_str: str | None) -> ZoneInfo | None:
    """Get ZoneInfo from timezone string, with fallback to DEFAULT_TIMEZONE env var."""
    tz_name = tz_str or os.getenv("DEFAULT_TIMEZONE")
    if not tz_name:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return None


def find_conference_deadlines(conference_key: str, conferences_data: dict) -> list[dict]:
    """Find all deadline info for a conference."""
    if not conferences_data:
        return []
    
    current_year = datetime.now().year
    results = []
    
    keys_to_check = [conference_key]
    if conference_key == "neurips":
        keys_to_check.append("nips")
    elif conference_key == "nips":
        keys_to_check.append("neurips")
    
    for key in keys_to_check:
        if key not in conferences_data:
            continue
        for conf in conferences_data[key]:
            if conf.get("year", 0) < current_year:
                continue
            
            deadlines = {}
            if "deadlines" in conf:
                for d in conf["deadlines"]:
                    dtype = d.get("type", "")
                    dtype = DEADLINE_TYPE_ALIASES.get(dtype, dtype)
                    if dtype in DEADLINE_TYPE_LABELS:
                        deadlines[dtype] = {
                            "date": d.get("date", ""),
                            "label": d.get("label", DEADLINE_TYPE_LABELS.get(dtype, dtype)),
                        }
            
            if not deadlines and conf.get("deadline"):
                deadlines["paper"] = {"date": conf.get("deadline", ""), "label": "Paper Submission"}
            if not deadlines.get("abstract") and conf.get("abstract_deadline"):
                deadlines["abstract"] = {"date": conf.get("abstract_deadline", ""), "label": "Abstract"}
            
            city = conf.get("city", "")
            country = conf.get("country", "")
            location = f"{city}, {country}".strip(", ") if city or country else ""
            
            info = {
                "title": conf.get("title", ""),
                "full_name": conf.get("full_name", ""),
                "year": conf.get("year", ""),
                "link": conf.get("link", ""),
                "location": location,
                "venue": conf.get("venue", ""),
                "conf_date": conf.get("date", ""),
                "deadlines": deadlines,
            }
            results.append(info)
    
    return results


def select_best_conference(deadlines: list[dict]) -> dict:
    """Select the most relevant conference entry (prefer ones with deadline info)."""
    now_aoe = datetime.now(timezone.utc).astimezone(AOE_TZ)
    
    def has_future_deadlines(conf: dict) -> bool:
        for dl in conf.get("deadlines", {}).values():
            dt = parse_deadline_datetime(dl.get("date", ""))
            if dt and dt.replace(tzinfo=AOE_TZ) > now_aoe:
                return True
        return False
    
    with_future = [c for c in deadlines if has_future_deadlines(c)]
    if with_future:
        return max(with_future, key=lambda d: d.get("year", 0))
    
    with_any_deadlines = [c for c in deadlines if c.get("deadlines")]
    if with_any_deadlines:
        return max(with_any_deadlines, key=lambda d: d.get("year", 0))
    
    return max(deadlines, key=lambda d: d.get("year", 0))


def format_deadline_response(deadlines: list[dict], conference_name: str, target_tz: ZoneInfo | None) -> dict:
    """Format deadline info for Slack response."""
    if not deadlines:
        return {
            "response_type": "ephemeral",
            "text": f"No upcoming deadlines found for '{conference_name}'.\nSupported: {', '.join(sorted(ALLOWED_KEYS))}",
        }

    conf = select_best_conference(deadlines)
    
    now_utc = datetime.now(timezone.utc)
    now_aoe = now_utc.astimezone(AOE_TZ)
    
    lines = []
    
    header = conf.get("title", conference_name)
    if conf.get("year"):
        header += f" {conf['year']}"
    if conf.get("full_name"):
        header += f"\n{conf['full_name']}"
    lines.append(header)
    lines.append("")
    
    conf_deadlines = conf.get("deadlines", {})
    if conf_deadlines:
        next_upcoming_type = None
        for dtype in DEADLINE_TYPE_ORDER:
            if dtype in conf_deadlines:
                dt = parse_deadline_datetime(conf_deadlines[dtype]["date"])
                if dt and dt.replace(tzinfo=AOE_TZ) > now_aoe:
                    next_upcoming_type = dtype
                    break
        
        for dtype in DEADLINE_TYPE_ORDER:
            if dtype not in conf_deadlines:
                continue
            
            dl = conf_deadlines[dtype]
            dt = parse_deadline_datetime(dl["date"])
            if not dt:
                continue
            
            dt_aoe = dt.replace(tzinfo=AOE_TZ)
            is_past = dt_aoe <= now_aoe
            is_next = dtype == next_upcoming_type
            
            if target_tz:
                dt_local = dt_aoe.astimezone(target_tz)
                date_str = dt_local.strftime("%Y-%m-%d %H:%M")
                tz_label = target_tz.key
            else:
                date_str = dt.strftime("%Y-%m-%d %H:%M")
                tz_label = "AoE"
            
            relative = format_relative_time(dt_aoe, now_aoe)
            label = DEADLINE_TYPE_LABELS.get(dtype, dtype)
            
            if is_past:
                line = f"  {label}: {date_str} ({tz_label}) - PASSED"
            elif is_next:
                line = f"> {label}: {date_str} ({tz_label}) [{relative}] <-- NEXT"
            else:
                line = f"  {label}: {date_str} ({tz_label}) [{relative}]"
            
            lines.append(line)
    else:
        lines.append("  No deadline information available")
    
    lines.append("")
    
    if conf.get("conf_date"):
        lines.append(f"Conference: {conf['conf_date']}")
    if conf.get("location"):
        lines.append(f"Location:   {conf['location']}")
    if conf.get("venue"):
        lines.append(f"Venue:      {conf['venue']}")
    if conf.get("link"):
        lines.append(f"Link:       {conf['link']}")
    
    lines.append("")
    tz_hint = f"Times shown in {target_tz.key}" if target_tz else "Tip: /deadline <conf> <timezone>  e.g. /deadline icml America/New_York"
    lines.append(tz_hint)
    
    code = "\n".join(lines)
    return {
        "response_type": "ephemeral",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"```{code}```"}}
        ],
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY_BYTES:
                self.send_response(413)
                self.end_headers()
                return
            body = self.rfile.read(length).decode("utf-8")
            LOGGER.info("headers=%s", dict(self.headers))
            LOGGER.info("raw_body=%s", body)

            # Slack signature verification
            signing_secret = os.getenv("SLACK_SIGNING_SECRET")
            if signing_secret:
                ts = self.headers.get("X-Slack-Request-Timestamp")
                sig = self.headers.get("X-Slack-Signature", "")
                if not ts or not sig:
                    self.send_response(401)
                    self.end_headers()
                    return
                try:
                    ts_int = int(ts)
                except Exception:
                    self.send_response(401)
                    self.end_headers()
                    return
                if abs(int(time.time()) - ts_int) > 300:
                    self.send_response(401)
                    self.end_headers()
                    return
                basestring = f"v0:{ts}:{body}".encode()
                digest = hmac.new(
                    signing_secret.encode(), basestring, hashlib.sha256
                ).hexdigest()
                expected = f"v0={digest}"
                if not hmac.compare_digest(expected, sig):
                    self.send_response(401)
                    self.end_headers()
                    return
            form = parse_qs(body)
            LOGGER.info("form=%s", dict(form))
            command = (form.get("command", [""])[0] or "").strip()
            raw_text = (form.get("text", [""])[0] or "").strip()
            if len(raw_text) > MAX_TEXT_CHARS:
                self.send_response(413)
                self.end_headers()
                return

            if command == "/deadline":
                if not raw_text:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    usage_text = (
                        "Usage: /deadline <conference> [timezone]\n"
                        "Examples:\n"
                        "  /deadline icml\n"
                        "  /deadline icml America/New_York\n"
                        "  /deadline neurips Europe/London\n\n"
                        f"Supported conferences: {', '.join(sorted(ALLOWED_KEYS))}"
                    )
                    self.wfile.write(
                        json.dumps(
                            {"response_type": "ephemeral", "text": usage_text}
                        ).encode()
                    )
                    return
                
                parts = raw_text.split()
                key = parts[0].lower()
                tz_arg = parts[1] if len(parts) > 1 else None
            else:
                key = command[1:].lower() if command.startswith("/") else ""
                tz_arg = None
            
            LOGGER.info("parsed command=%s raw_text=%s key=%s tz_arg=%s", command, raw_text, key, tz_arg)
            
            if key and key not in ALLOWED_KEYS:
                resp = {
                    "response_type": "ephemeral",
                    "text": f"Unknown conference '{key}'.\nSupported: {', '.join(sorted(ALLOWED_KEYS))}",
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode())
                return

            target_tz = get_target_timezone(tz_arg)
            if tz_arg and not target_tz:
                resp = {
                    "response_type": "ephemeral",
                    "text": f"Invalid timezone '{tz_arg}'.\nExamples: America/New_York, Europe/London, Asia/Tokyo, US/Pacific",
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode())
                return

            name = CONFERENCE_MAPPINGS.get(key, key)

            data = fetch_conference_data()
            resp = (
                {
                    "response_type": "ephemeral",
                    "text": "Sorry, I could not fetch conference data at the moment.",
                }
                if not data
                else format_deadline_response(
                    find_conference_deadlines(key, data), name, target_tz
                )
            )

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {"response_type": "ephemeral", "text": f"Error: {e}"}
                ).encode()
            )

    def do_GET(self):
        self.send_response(405)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Method not allowed"}).encode())
