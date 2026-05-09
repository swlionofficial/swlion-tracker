"""
SW..LION Release Agent
======================
Runs on GitHub Actions every hour.
1. Fetches SW..LION's full catalog from Spotify Web API.
2. Compares with releases.json (last known state).
3. For any new release: posts to Telegram channel + updates index.html.
4. Commits changes back to the repo so Netlify auto-redeploys.

Environment variables required (set as GitHub Secrets):
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET
    TELEGRAM_BOT_TOKEN
"""

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests

# --- Configuration -----------------------------------------------------------

ARTIST_ID = "24zGJwyyCrVEqfvQKC8Act"  # SW..LION on Spotify
TELEGRAM_CHAT = "@swlionofficial"

REPO_ROOT = Path(__file__).parent
RELEASES_FILE = REPO_ROOT / "releases.json"
INDEX_FILE = REPO_ROOT / "index.html"

# Profile links — used in every Telegram post and as fallbacks in PWA
PROFILES = {
    "spotify": "https://open.spotify.com/artist/24zGJwyyCrVEqfvQKC8Act",
    "apple": "https://music.apple.com/us/artist/sw-lion/1876097912",
    "youtube": "https://music.youtube.com/channel/UC4dRl3sUa19Ajrx6g-1Ca_Q",
    "deezer": "https://www.deezer.com/en/artist/372829941",
    "tidal": "https://tidal.com/artist/74357183/u",
    "yandex": "https://music.yandex.ru/artist/25564087",
    "vk": "https://vk.ru/artist/6937135904079804585",
}


# --- Spotify API -------------------------------------------------------------

def get_spotify_token() -> str:
    """Get an app-level access token via Client Credentials flow."""
    client_id = os.environ["SPOTIFY_CLIENT_ID"]
    client_secret = os.environ["SPOTIFY_CLIENT_SECRET"]

    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def fetch_artist_catalog(token: str) -> list[dict]:
    """Return all singles & albums of the artist, sorted newest first."""
    headers = {"Authorization": f"Bearer {token}"}
    items: list[dict] = []
    url = (
        f"https://api.spotify.com/v1/artists/{ARTIST_ID}/albums"
        "?include_groups=single,album&limit=50"
    )
    while url:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        items.extend(data["items"])
        url = data.get("next")

    # Deduplicate by name (Spotify sometimes returns same album for multiple markets)
    seen = set()
    unique: list[dict] = []
    for item in items:
        key = item["name"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    # Sort by release_date descending (newest first)
    unique.sort(key=lambda x: x["release_date"], reverse=True)
    return unique


def fetch_album_details(token: str, album_id: str) -> dict:
    """Get track listing — needed for duration."""
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"https://api.spotify.com/v1/albums/{album_id}",
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# --- Data normalization ------------------------------------------------------

def normalize_release(album: dict, full_album: dict) -> dict:
    """Convert Spotify API response to our internal release format."""
    # Pick the largest cover available
    images = album.get("images", [])
    cover_large = images[0]["url"] if images else ""
    # Spotify returns 640/300/64. We want the 300 version for the PWA list:
    cover_small = cover_large.replace("ab67616d0000b273", "ab67616d00001e02")

    # Duration of first track (all SW..LION releases are singles so far)
    tracks = full_album.get("tracks", {}).get("items", [])
    duration_ms = tracks[0]["duration_ms"] if tracks else 0
    minutes = duration_ms // 60000
    seconds = (duration_ms % 60000) // 1000
    duration_str = f"{minutes}:{seconds:02d}"

    return {
        "id": album["id"],
        "name": album["name"],
        "release_date": album["release_date"],  # "YYYY-MM-DD"
        "duration": duration_str,
        "cover_large": cover_large,
        "cover_small": cover_small,
        "spotify_url": album["external_urls"]["spotify"],
    }


# --- Telegram ---------------------------------------------------------------

def post_to_telegram(release: dict) -> None:
    """Post new release announcement with cover photo and platform buttons."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    # Format date nicely
    iso = release["release_date"]
    parsed = datetime.strptime(iso, "%Y-%m-%d").date()
    date_str = parsed.strftime("%-d %B %Y") if sys.platform != "win32" else parsed.strftime("%d %B %Y")

    # HTML caption — Telegram doesn't allow Markdown buttons in captions, so we
    # use inline keyboard for platform links.
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
        timeout=15,
    )
    if not r.ok:
        print(f"Telegram error: {r.status_code} {r.text}")
        r.raise_for_status()
    print(f"  → posted to {TELEGRAM_CHAT}")


def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- PWA HTML generation -----------------------------------------------------

def render_release_card(release: dict, is_first: bool) -> str:
    """Generate one .release card for the All Releases list."""
    iso = release["release_date"]
    parsed = datetime.strptime(iso, "%Y-%m-%d").date()
    short_date = parsed.strftime("%b %-d") if sys.platform != "win32" else parsed.strftime("%b %d")

    debut_marker = " · Debut" if is_first else ""

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
    """Generate the Latest Release hero card."""
    iso = release["release_date"]
    parsed = datetime.strptime(iso, "%Y-%m-%d").date()
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
    """Rewrite index.html with the current release list."""
    if not INDEX_FILE.exists():
        print("  ! index.html not found, skipping PWA update")
        return

    html = INDEX_FILE.read_text(encoding="utf-8")

    # Update singles count in stats
    html = re.sub(
        r"<span><strong>\d+</strong> Singles</span>",
        f"<span><strong>{len(releases)}</strong> Singles</span>",
        html,
    )

    # Replace hero + releases list (everything between <!--RELEASES_START--> and <!--RELEASES_END-->)
    hero_html = render_hero(releases[0])
    list_html = "\n".join(render_release_card(r, i == len(releases) - 2) for i, r in enumerate(releases[1:]))

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

    # Bump snapshot date
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
    print(f"[{datetime.utcnow().isoformat()}Z] Checking SW..LION catalog...")

    # 1. Load known state
    if RELEASES_FILE.exists():
        known = json.loads(RELEASES_FILE.read_text(encoding="utf-8"))
        known_ids = {r["id"] for r in known.get("releases", [])}
    else:
        known = {"releases": []}
        known_ids = set()
    print(f"  known: {len(known_ids)} releases")

    # 2. Fetch current Spotify state
    try:
        token = get_spotify_token()
        catalog = fetch_artist_catalog(token)
    except Exception as e:
        print(f"  ! Spotify API error: {e}")
        return 1
    print(f"  spotify: {len(catalog)} releases")

    # 3. Find new releases
    new_albums = [a for a in catalog if a["id"] not in known_ids]
    print(f"  new: {len(new_albums)}")

    if not new_albums:
        print("  nothing to do.")
        return 0

    # 4. For each new release: enrich + post to Telegram
    new_releases = []
    for album in new_albums:
        print(f"  + {album['name']} ({album['release_date']})")
        details = fetch_album_details(token, album["id"])
        release = normalize_release(album, details)
        new_releases.append(release)
        try:
            post_to_telegram(release)
        except Exception as e:
            print(f"    ! Telegram post failed: {e}")
            # Don't bail — still save state so we don't double-post next run
            continue

    # 5. Build the updated full catalog (newest first), persist it
    all_releases = []
    for album in catalog:
        if album["id"] in known_ids:
            existing = next(r for r in known["releases"] if r["id"] == album["id"])
            all_releases.append(existing)
        else:
            details = fetch_album_details(token, album["id"])
            all_releases.append(normalize_release(album, details))

    state = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "releases": all_releases,
    }
    RELEASES_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → wrote releases.json")

    # 6. Regenerate index.html from full catalog
    update_pwa_html(all_releases)

    return 0


if __name__ == "__main__":
    sys.exit(main())
