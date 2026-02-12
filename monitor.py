#!/usr/bin/env python3
"""
Auction Monitor — checks for new listings and sends notifications.

Usage:
    # One-shot check (run manually or via cron)
    python3 monitor.py

    # Continuous monitoring (checks every N minutes)
    python3 monitor.py --watch --interval 60

    # Dry run — show what would be notified without sending
    python3 monitor.py --dry-run

    # Email notifications (configure SMTP in .api_keys.json)
    python3 monitor.py --email you@gmail.com

    # macOS desktop notifications (no config needed)
    python3 monitor.py --desktop

Setup for automated runs:
    # Option 1: crontab (runs every 2 hours)
    crontab -e
    0 */2 * * * cd /Users/rodneydial/Downloads/propertymgr && python3 monitor.py --email you@gmail.com --desktop

    # Option 2: launchd (macOS, runs every 2 hours even on wake)
    python3 monitor.py --install-launchd --email you@gmail.com

Email config in .api_keys.json:
    {
        "smtp_server": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "you@gmail.com",
        "smtp_password": "your-app-password"
    }
    For Gmail: use an App Password (https://myaccount.google.com/apppasswords)
"""

import argparse
import json
import os
import platform
import smtplib
import subprocess
import sys
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).parent
SEEN_FILE = PROJECT_DIR / ".seen_listings.json"
API_KEYS_FILE = PROJECT_DIR / ".api_keys.json"
ANALYSIS_FILE = PROJECT_DIR / "property_analysis.json"
LOG_FILE = PROJECT_DIR / ".monitor.log"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def log(msg: str):
    """Log to file and stdout."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except IOError:
        pass


def load_seen() -> dict:
    """Load previously seen listing IDs/addresses."""
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {"listings": {}, "last_check": None}


def save_seen(seen: dict):
    """Save seen listings to disk."""
    seen["last_check"] = datetime.now().isoformat()
    SEEN_FILE.write_text(json.dumps(seen, indent=2))


def load_api_keys() -> dict:
    if API_KEYS_FILE.exists():
        try:
            return json.loads(API_KEYS_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def make_listing_key(prop: dict) -> str:
    """Create a unique key for a property listing."""
    addr = (prop.get("address") or "").upper().strip()
    city = (prop.get("city") or "").upper().strip()
    return f"{addr}|{city}"


# ---------------------------------------------------------------------------
# Run the scraper pipeline
# ---------------------------------------------------------------------------
def run_pipeline() -> list:
    """Run the auction pipeline and return the new property list."""
    log("Running auction pipeline...")
    try:
        result = subprocess.run(
            [sys.executable, "main.py", "--auction-com", "--count", "50", "--max-zips", "20"],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            log(f"Pipeline error: {result.stderr[:500]}")
            return []
        log("Pipeline completed successfully")
    except subprocess.TimeoutExpired:
        log("Pipeline timed out after 600s")
        return []
    except Exception as e:
        log(f"Pipeline failed: {e}")
        return []

    # Read the generated JSON
    try:
        data = json.loads(ANALYSIS_FILE.read_text())
        props = data.get("all_properties", [])
        log(f"Found {len(props)} properties in output")
        return props
    except (json.JSONDecodeError, IOError) as e:
        log(f"Failed to read analysis JSON: {e}")
        return []


# ---------------------------------------------------------------------------
# Diff: find new listings
# ---------------------------------------------------------------------------
def find_new_listings(properties: list, seen: dict) -> list:
    """Compare current properties against seen list, return new ones."""
    new_listings = []
    for prop in properties:
        key = make_listing_key(prop)
        if key not in seen.get("listings", {}):
            new_listings.append(prop)
    return new_listings


def mark_as_seen(properties: list, seen: dict) -> dict:
    """Mark all current properties as seen."""
    for prop in properties:
        key = make_listing_key(prop)
        seen.setdefault("listings", {})[key] = {
            "first_seen": datetime.now().isoformat(),
            "address": prop.get("address", ""),
            "city": prop.get("city", ""),
            "auction_date": prop.get("auction_date", ""),
            "auction_price": prop.get("auction_price", 0),
        }
    return seen


# ---------------------------------------------------------------------------
# Notifications: Desktop (macOS)
# ---------------------------------------------------------------------------
def send_desktop_notification(new_listings: list):
    """Send macOS desktop notifications via osascript."""
    if platform.system() != "Darwin":
        log("Desktop notifications only supported on macOS")
        return

    count = len(new_listings)
    title = f"🏠 {count} New Auction Listing{'s' if count != 1 else ''}!"

    # Summary notification
    lines = []
    for p in new_listings[:5]:
        addr = p.get("address", "Unknown")
        city = p.get("city", "")
        price = p.get("auction_price", 0)
        margin = p.get("profit_margin", 0)
        score = p.get("deal_score", 0)
        emoji = "🔥" if margin >= 40 else "⭐" if margin >= 35 else "✅" if margin >= 30 else "📊"
        lines.append(f"{emoji} {addr}, {city} — ${price:,.0f} ({margin:.0f}% margin, score {score:.0f})")

    if count > 5:
        lines.append(f"... and {count - 5} more")

    body = "\\n".join(lines)

    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{body}" with title "{title}" sound name "Glass"'],
            timeout=10,
        )
        log(f"Desktop notification sent ({count} listings)")
    except Exception as e:
        log(f"Desktop notification failed: {e}")


# ---------------------------------------------------------------------------
# Notifications: Email
# ---------------------------------------------------------------------------
def send_email_notification(new_listings: list, to_email: str):
    """Send email notification about new listings."""
    keys = load_api_keys()
    smtp_server = keys.get("smtp_server", "smtp.gmail.com")
    smtp_port = int(keys.get("smtp_port", 587))
    smtp_user = keys.get("smtp_user", "")
    smtp_password = keys.get("smtp_password", "")

    if not smtp_user or not smtp_password:
        log("Email not configured — add smtp_user and smtp_password to .api_keys.json")
        log("For Gmail, use an App Password: https://myaccount.google.com/apppasswords")
        return

    count = len(new_listings)
    subject = f"🏠 {count} New Auction Listing{'s' if count != 1 else ''} — Deschutes/Jackson County"

    # Build HTML email
    rows = []
    for p in sorted(new_listings, key=lambda x: -x.get("deal_score", 0)):
        addr = p.get("address", "Unknown")
        city = p.get("city", "")
        price = p.get("auction_price", 0)
        arv = p.get("estimated_arv", 0)
        margin = p.get("profit_margin", 0)
        score = p.get("deal_score", 0)
        date = p.get("auction_date", "TBD")
        url = p.get("property_url", "")

        badge = "🔥 HOT" if margin >= 40 else "⭐ EXCELLENT" if margin >= 35 else "✅ GOOD" if margin >= 30 else f"📊 {score:.0f}"

        link = f'<a href="{url}">{addr}</a>' if url else addr
        rows.append(f"""
        <tr style="border-bottom: 1px solid #eee;">
            <td style="padding:8px;">{link}<br><small>{city}</small></td>
            <td style="padding:8px;text-align:right;">${price:,.0f}</td>
            <td style="padding:8px;text-align:right;">${arv:,.0f}</td>
            <td style="padding:8px;text-align:center;">{margin:.1f}%</td>
            <td style="padding:8px;text-align:center;">{badge}</td>
            <td style="padding:8px;text-align:center;">{date}</td>
        </tr>
        """)

    html = f"""
    <html>
    <body style="font-family: -apple-system, Arial, sans-serif; max-width: 800px; margin: 0 auto;">
        <h2 style="color: #2c3e50;">🏠 {count} New Auction Listing{'s' if count != 1 else ''}</h2>
        <p>New properties found on Auction.com in Deschutes & Jackson County, Oregon.</p>
        <table style="width:100%; border-collapse:collapse; font-size:14px;">
            <tr style="background:#2c3e50; color:#fff;">
                <th style="padding:8px;text-align:left;">Property</th>
                <th style="padding:8px;text-align:right;">Price</th>
                <th style="padding:8px;text-align:right;">Est. ARV</th>
                <th style="padding:8px;text-align:center;">Margin</th>
                <th style="padding:8px;text-align:center;">Rating</th>
                <th style="padding:8px;text-align:center;">Auction Date</th>
            </tr>
            {''.join(rows)}
        </table>
        <p style="margin-top:20px; color:#666; font-size:12px;">
            Generated by Auction Property Analyzer<br>
            <a href="https://rodney-blip.github.io/propertymgr/index.html">View Dashboard</a>
        </p>
    </body>
    </html>
    """

    # Plain text fallback
    text_lines = [f"{count} New Auction Listings\n"]
    for p in new_listings:
        text_lines.append(
            f"  {p.get('address', '?')}, {p.get('city', '?')} — "
            f"${p.get('auction_price', 0):,.0f} — "
            f"{p.get('profit_margin', 0):.1f}% margin — "
            f"Score {p.get('deal_score', 0):.0f}"
        )
    text_lines.append(f"\nDashboard: https://rodney-blip.github.io/propertymgr/index.html")
    text = "\n".join(text_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        log(f"Email sent to {to_email} ({count} new listings)")
    except Exception as e:
        log(f"Email failed: {e}")


# ---------------------------------------------------------------------------
# launchd installer (macOS persistent scheduling)
# ---------------------------------------------------------------------------
PLIST_LABEL = "com.propertymgr.monitor"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def install_launchd(email: str = "", desktop: bool = True, interval: int = 7200):
    """Install a macOS launchd agent to run monitor every N seconds."""
    python = sys.executable
    script = str(PROJECT_DIR / "monitor.py")

    args = [python, script]
    if email:
        args.extend(["--email", email])
    if desktop:
        args.append("--desktop")

    args_xml = "\n        ".join(f"<string>{a}</string>" for a in args)

    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        {args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{PROJECT_DIR}</string>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{PROJECT_DIR}/.monitor.log</string>
    <key>StandardErrorPath</key>
    <string>{PROJECT_DIR}/.monitor.log</string>
</dict>
</plist>
"""

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist)

    # Unload if already running, then load
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)],
                    capture_output=True)
    result = subprocess.run(["launchctl", "load", str(PLIST_PATH)],
                            capture_output=True, text=True)
    if result.returncode == 0:
        log(f"launchd agent installed: {PLIST_PATH}")
        log(f"Will check every {interval // 60} minutes")
        log(f"Notifications: {'email=' + email if email else 'no email'}, {'desktop' if desktop else 'no desktop'}")
        log(f"To uninstall: launchctl unload {PLIST_PATH} && rm {PLIST_PATH}")
    else:
        log(f"launchd install failed: {result.stderr}")


def uninstall_launchd():
    """Remove the launchd agent."""
    if PLIST_PATH.exists():
        subprocess.run(["launchctl", "unload", str(PLIST_PATH)], capture_output=True)
        PLIST_PATH.unlink()
        log(f"launchd agent removed: {PLIST_PATH}")
    else:
        log("No launchd agent found to remove")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def check_once(email: str = "", desktop: bool = False, dry_run: bool = False) -> list:
    """Run one check cycle. Returns list of new listings found."""
    seen = load_seen()
    last = seen.get("last_check")
    if last:
        log(f"Last check: {last}")
    else:
        log("First run — all listings will be marked as new")

    # Run the pipeline
    properties = run_pipeline()
    if not properties:
        log("No properties returned from pipeline")
        save_seen(seen)
        return []

    # Find new listings
    new_listings = find_new_listings(properties, seen)
    log(f"Results: {len(properties)} total, {len(new_listings)} new")

    if new_listings:
        log("New listings:")
        for p in sorted(new_listings, key=lambda x: -x.get("deal_score", 0)):
            emoji = "🔥" if p.get("profit_margin", 0) >= 40 else "⭐" if p.get("profit_margin", 0) >= 35 else "📊"
            log(f"  {emoji} {p.get('address', '?')}, {p.get('city', '?')} — "
                f"${p.get('auction_price', 0):,.0f} — "
                f"{p.get('profit_margin', 0):.1f}% margin — "
                f"Score {p.get('deal_score', 0):.0f}")

        if not dry_run:
            if desktop:
                send_desktop_notification(new_listings)
            if email:
                send_email_notification(new_listings, email)
        else:
            log("(Dry run — notifications skipped)")
    else:
        log("No new listings since last check")

    # Mark all current listings as seen
    if not dry_run:
        seen = mark_as_seen(properties, seen)
        save_seen(seen)

    return new_listings


def main():
    parser = argparse.ArgumentParser(
        description="Monitor Auction.com for new listings and send notifications",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 monitor.py --dry-run              # See what would be notified
  python3 monitor.py --desktop              # macOS notification
  python3 monitor.py --email you@gmail.com  # Email alert
  python3 monitor.py --watch --interval 60  # Check every 60 min
  python3 monitor.py --install-launchd      # Auto-run every 2 hours
        """,
    )
    parser.add_argument("--email", help="Email address for notifications")
    parser.add_argument("--desktop", action="store_true", help="Send macOS desktop notifications")
    parser.add_argument("--dry-run", action="store_true", help="Show results without sending notifications")
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring mode")
    parser.add_argument("--interval", type=int, default=120, help="Minutes between checks in watch mode (default: 120)")
    parser.add_argument("--install-launchd", action="store_true", help="Install macOS launchd agent for automated runs")
    parser.add_argument("--uninstall-launchd", action="store_true", help="Remove launchd agent")
    parser.add_argument("--reset", action="store_true", help="Clear seen listings (next run treats all as new)")

    args = parser.parse_args()

    if args.uninstall_launchd:
        uninstall_launchd()
        return

    if args.reset:
        if SEEN_FILE.exists():
            SEEN_FILE.unlink()
        log("Seen listings cleared — next run will treat all as new")
        return

    if args.install_launchd:
        install_launchd(
            email=args.email or "",
            desktop=args.desktop or True,
            interval=args.interval * 60,
        )
        return

    if not args.email and not args.desktop and not args.dry_run:
        # Default to desktop notifications on macOS
        if platform.system() == "Darwin":
            args.desktop = True
            log("No notification method specified — defaulting to macOS desktop notifications")
        else:
            args.dry_run = True
            log("No notification method specified — running in dry-run mode")

    log("=" * 60)
    log("Auction Monitor starting")
    log("=" * 60)

    if args.watch:
        log(f"Watch mode: checking every {args.interval} minutes")
        while True:
            try:
                check_once(email=args.email, desktop=args.desktop, dry_run=args.dry_run)
            except Exception as e:
                log(f"Error during check: {e}")
            log(f"Next check in {args.interval} minutes...")
            time.sleep(args.interval * 60)
    else:
        check_once(email=args.email, desktop=args.desktop, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
