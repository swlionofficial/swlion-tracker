"""
SW..LION Release Agent v2 (HTML scraping)
==========================================
Scrapes open.spotify.com directly instead of using the Web API.
- No Spotify Developer App needed (no Client ID / Secret).
- More resilient to API changes.
- Same logic as v1: detect new albums, post to Telegram, update PWA.

Required GitHub secret:
    TELEGRAM_BOT_TOKEN
"""

import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

# --- Configuration -----------------------------------------------------------

ARTIST_ID = "24zGJwyyCrVEqfvQKC8Act"
ARTIST_URL = f"https://open.spotify.com/artist/{ARTIST_ID}"
ALBUM_URL_PREFIX = "https://open.spotify.com/album/"
TELEGRAM_CHAT = "@swlionofficial"

REPO_ROOT = Path(__file__).parent
RELEASES_FILE = REPO_ROOT / "releases.json"
INDEX_FILE = REPO_ROOT / "index.html"

PROFILES = {
    "spotify": "https://open.spotify.com/artist/24zGJwyyCrVEqfvQKC8Act",
    "apple": "https://music.apple.com/us/artist/sw-lion/1876097912",
    "youtube": "https://music.youtube.com/channel/UC4dRl3sUa19Ajrx6g-1Ca_Q",
    "deezer": "https://www.deezer.com/en/artist/372829941",
    "tidal": "https://tidal.com/artist/74357183/u",
    "yandex": "https://music.yandex.ru/artist/25564087",
    "vk": "https://vk.ru/artist/6937135904079804585",
}

# Spotify rejects requests without a real-looking User-Agent
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


# --- Spotify scraping --------------------------------------------------------

def fetch_artist_album_ids() -> set[str]:
    """Scrape the public artist page and extract all album IDs."""
    print(f"  fetching {ARTIST_URL}")
    r = requests.get(ARTIST_URL, headers=HEADERS, timeout=15)
    if not r.ok:
        print(f"  ! HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    # Spotify album IDs are 22-char base62 strings
    ids = set(re.findall(r'/album/([a-zA-Z0-9]{22})', r.text))
    print(f"  found {len(ids)} albums on artist page")
    return ids


def fetch_album_details(album_id: str) -> dict:
    """Scrape album page for title, date, duration, cover."""
    url = ALBUM_URL_PREFIX + album_id
    r = requests.get(url, headers=HEADERS, timeout=15)
    if not r.ok:
        print(f"  ! album {album_id}: HTTP {r.status_code}")
    r.raise_for_status()
    html = r.text

    # og:title looks like: "The lost - Single by SW..LION | Spotify"
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html)
    full_title = m.group(1) if m else f"Unknown ({album_id})"
    title = re.sub(
        r'\s*[-–—]\s*(Single|EP|Album)\s+by\s+.+$',
        '',
        full_title,
    ).strip()

    # og:image is the large 640px cover
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](https://i\.scdn\.co/image/[a-z0-9]+)["\']', html)
    cover_large = m.group(1) if m else ""
    # Spotify cover URL pattern: ab67616d0000b273<hash> (640) → ab67616d00001e02<hash> (300)
    cover_small = cover_large.replace("ab67616d0000b273", "ab67616d00001e02")

    # release_date as ISO YYYY-MM-DD
    m = re.search(r'<meta[^>]+(?:name|property)=["\']music:release_date["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})["\']', html)
    release_date = m.group(1) if m else None

    # Duration: look for "X min Y sec" anywhere in HTML
    m = re.search(r'(\d+)\s*min\s*(\d+)\s*sec', html)
    if m:
        duration = f"{int(m.group(1))}:{int(m.group(2)):02d}"
    else:
        duration = "0:00"

    return {
        "id": album_id,
        "name": title,
        "release_date": release_date or "0000-00-00",
        "duration": duration,
        "cover_large": cover_large,
        "cover_small": cover_small,
        "spotify_url": url,
    }


# --- Telegram ----------------------------------------------------------------

def post_to_telegram(release: dict) -> None:
    """Post release announcement with cover photo and platform buttons."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    parsed = datetime.strptime(release["release_date"], "%Y-%m-%d").date()
    date_str = parsed.strftime("%-d %B %Y") if sys.platform != "win32" else parsed.strftime("%d %B %Y")

    caption = (
        f"🦁 <b>NEW RELEASE</b>\n\n"
        f"<b>{escape_html(release['name'])}</b>\n"
        f"<i>SW..LION · Single · {release['duration']}</i>\n"
        f"<i>{date_str}</i>"
    )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Spotify", "url": release["spotify_url"]},
                {"text": "Apple Music", "url": PROFILES["apple"]},
                {"text": "YouTube Music", "url": PROFILES["youtube"]},
            ],
            [
                {"text": "Deezer", "url": PROFILES["deezer"]},
                {"text": "Tidal", "url": PROFILES["tidal"]},
            ],
            [
                {"text": "Yandex Music", "url": PROFILES["yandex"]},
                {"text": "VK Music", "url": PROFILES["vk"]},
            ],
        ]
    }

    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        json={
            "chat_id": TELEGRAM_CHAT,
            "photo": release["cover_large"],
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        },
        timeout=20,
    )
    if not r.ok:
        print(f"  ! Telegram {r.status_code}: {r.text}")
        r.raise_for_status()
    print(f"  → posted to {TELEGRAM_CHAT}")


def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- PWA HTML generation -----------------------------------------------------

def render_release_card(release: dict, is_debut: bool) -> str:
    parsed = datetime.strptime(release["release_date"], "%Y-%m-%d").date()
    short_date = parsed.strftime("%b %-d") if sys.platform != "win32" else parsed.strftime("%b %d")
    debut_marker = " · Debut" if is_debut else ""

    return f"""
    <div class="release">
      <img class="release-cover" src="{release['cover_small']}" alt="">
      <div class="release-info">
        <div class="release-title">{escape_html(release['name'])}</div>
        <div class="release-meta">{short_date} · {release['duration']}{debut_marker}</div>
        <div class="platforms">
          <a class="pill" href="{release['spotify_url']}">SP</a>
          <a class="pill" href="{PROFILES['apple']}">AM</a>
          <a class="pill" href="{PROFILES['youtube']}">YT</a>
          <a class="pill" href="{PROFILES['deezer']}">DZ</a>
          <a class="pill" href="{PROFILES['tidal']}">TD</a>
          <a class="pill" href="{PROFILES['yandex']}">YA</a>
          <a class="pill" href="{PROFILES['vk']}">VK</a>
        </div>
      </div>
    </div>"""


def render_hero(release: dict) -> str:
    parsed = datetime.strptime(release["release_date"], "%Y-%m-%d").date()
    badge = parsed.strftime("%b %-d · %Y · NEW") if sys.platform != "win32" else parsed.strftime("%b %d · %Y · NEW")

    return f"""  <div class="section-label">Latest Release</div>
  <article class="latest">
    <img class="latest-cover" src="{release['cover_large']}" alt="">
    <div class="latest-info">
      <div class="latest-badge">{badge}</div>
      <h2 class="latest-title">{escape_html(release['name'])}</h2>
      <div class="latest-meta">Single · {release['duration']}</div>
      <div class="platforms">
        <a class="pill" href="{release['spotify_url']}">SP</a>
        <a class="pill" href="{PROFILES['apple']}">AM</a>
        <a class="pill" href="{PROFILES['youtube']}">YT</a>
        <a class="pill" href="{PROFILES['deezer']}">DZ</a>
        <a class="pill" href="{PROFILES['tidal']}">TD</a>
        <a class="pill" href="{PROFILES['yandex']}">YA</a>
        <a class="pill" href="{PROFILES['vk']}">VK</a>
      </div>
    </div>
  </article>"""


def update_pwa_html(releases: list[dict]) -> None:
    if not INDEX_FILE.exists():
        print("  ! index.html not found, skipping PWA update")
        return

    html = INDEX_FILE.read_text(encoding="utf-8")

    html = re.sub(
        r"<span><strong>\d+</strong> Singles</span>",
        f"<span><strong>{len(releases)}</strong> Singles</span>",
        html,
    )

    hero_html = render_hero(releases[0])
    list_html = "\n".join(
        render_release_card(r, i == len(releases) - 2)
        for i, r in enumerate(releases[1:])
    )

    new_block = f"""<!--RELEASES_START-->
{hero_html}

  <div class="section-label">All Releases</div>
  <div class="releases">
{list_html}

  </div>
  <!--RELEASES_END-->"""

    html = re.sub(
        r"<!--RELEASES_START-->.*?<!--RELEASES_END-->",
        new_block,
        html,
        flags=re.DOTALL,
    )

    today_str = date.today().strftime("%-d %b %Y") if sys.platform != "win32" else date.today().strftime("%d %b %Y")
    html = re.sub(
        r"<strong>Snapshot</strong>\s*·\s*[^<]+",
        f"<strong>Snapshot</strong> · {today_str} · auto",
        html,
    )

    INDEX_FILE.write_text(html, encoding="utf-8")
    print(f"  → updated index.html ({len(releases)} releases)")


# --- Main --------------------------------------------------------------------

def main() -> int:
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Checking SW..LION catalog (HTML scraping mode)...")

    if RELEASES_FILE.exists():
        known = json.loads(RELEASES_FILE.read_text(encoding="utf-8"))
        known_ids = {r["id"] for r in known.get("releases", [])}
    else:
        known = {"releases": []}
        known_ids = set()
    print(f"  known: {len(known_ids)} releases")

    try:
        spotify_ids = fetch_artist_album_ids()
    except Exception as e:
        print(f"  ! scrape failed: {e}")
        return 1

    new_ids = spotify_ids - known_ids
    print(f"  new: {len(new_ids)}")

    if not new_ids:
        print("  nothing to do.")
        return 0

    new_releases = []
    for album_id in new_ids:
        try:
            details = fetch_album_details(album_id)
        except Exception as e:
            print(f"  ! failed details for {album_id}: {e}")
            continue
        print(f"  + {details['name']} ({details['release_date']})")
        new_releases.append(details)
        try:
            post_to_telegram(details)
        except Exception as e:
            print(f"    ! Telegram post failed: {e}")
        time.sleep(1)  # be polite to Telegram + Spotify

    if not new_releases:
        print("  nothing posted, skipping state update.")
        return 0

    all_releases = known.get("releases", []) + new_releases
    all_releases.sort(key=lambda r: r["release_date"], reverse=True)

    state = {
        "updated_at": now,
        "releases": all_releases,
    }
    RELEASES_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  → wrote releases.json ({len(all_releases)} releases)")

    update_pwa_html(all_releases)
    return 0


if __name__ == "__main__":
    sys.exit(main())
