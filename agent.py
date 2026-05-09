"""
SW..LION Release Agent v3 (iTunes Search API)
==============================================
Uses Apple's free iTunes Search API as source of truth.
- No auth, no API keys, no rate limits.
- Matches against known releases by NAME (not ID), so it works
  smoothly with the existing releases.json that has Spotify IDs.

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

ARTIST_NAME = "SW..LION"
APPLE_ARTIST_ID = "1876097912"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"

ARTIST_SPOTIFY_URL = "https://open.spotify.com/artist/24zGJwyyCrVEqfvQKC8Act"
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


# --- iTunes API --------------------------------------------------------------

def normalize_name(raw: str) -> str:
    """Strip ' - Single', ' - EP', ' - Album' suffixes and lowercase."""
    name = re.sub(r'\s*[-–—]\s*(Single|EP|Album)\s*$', '', raw, flags=re.IGNORECASE)
    return name.strip()


def fetch_artist_albums() -> list[dict]:
    """Get all albums of the artist via iTunes Search API."""
    print(f"  fetching iTunes lookup for artist {APPLE_ARTIST_ID}")
    r = requests.get(
        ITUNES_LOOKUP_URL,
        params={
            "id": APPLE_ARTIST_ID,
            "entity": "album",
            "limit": 200,
        },
        timeout=15,
    )
    if not r.ok:
        print(f"  ! HTTP {r.status_code}: {r.text[:300]}")
    r.raise_for_status()
    data = r.json()
    albums = [it for it in data.get("results", []) if it.get("wrapperType") == "collection"]
    print(f"  found {len(albums)} albums on iTunes")
    return albums


def fetch_album_duration(collection_id: int) -> str:
    """Get duration of the first track via iTunes track lookup."""
    r = requests.get(
        ITUNES_LOOKUP_URL,
        params={"id": collection_id, "entity": "song", "limit": 50},
        timeout=15,
    )
    r.raise_for_status()
    tracks = [it for it in r.json().get("results", []) if it.get("wrapperType") == "track"]
    if not tracks:
        return "0:00"
    ms = tracks[0].get("trackTimeMillis", 0)
    return f"{ms // 60000}:{(ms % 60000) // 1000:02d}"


def normalize_release(album: dict, duration: str) -> dict:
    """Build our internal release dict from iTunes album object."""
    name = normalize_name(album["collectionName"])
    iso_date = album["releaseDate"][:10]  # "2026-05-07T07:00:00Z" → "2026-05-07"

    # Apple gives 100x100 by default; replace with high-res variants
    art100 = album.get("artworkUrl100", "")
    cover_large = art100.replace("100x100bb.jpg", "1000x1000bb.jpg")
    cover_small = art100.replace("100x100bb.jpg", "300x300bb.jpg")

    return {
        "id": str(album["collectionId"]),
        "name": name,
        "release_date": iso_date,
        "duration": duration,
        "cover_large": cover_large,
        "cover_small": cover_small,
        # For new releases we don't know the Spotify album ID, so link to artist profile
        "spotify_url": ARTIST_SPOTIFY_URL,
        "apple_url": album.get("collectionViewUrl", PROFILES["apple"]),
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

    apple_url = release.get("apple_url", PROFILES["apple"])
    spotify_url = release.get("spotify_url", PROFILES["spotify"])

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Spotify", "url": spotify_url},
                {"text": "Apple Music", "url": apple_url},
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
          <a class="pill" href="{release.get('spotify_url', PROFILES['spotify'])}">SP</a>
          <a class="pill" href="{release.get('apple_url', PROFILES['apple'])}">AM</a>
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
        <a class="pill" href="{release.get('spotify_url', PROFILES['spotify'])}">SP</a>
        <a class="pill" href="{release.get('apple_url', PROFILES['apple'])}">AM</a>
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
    print(f"[{now}] Checking SW..LION catalog (iTunes API mode)...")

    if RELEASES_FILE.exists():
        known = json.loads(RELEASES_FILE.read_text(encoding="utf-8"))
        # Match by NAME (case-insensitive, stripped) — works across Spotify/Apple/whatever IDs
        known_names = {r["name"].strip().lower() for r in known.get("releases", [])}
    else:
        known = {"releases": []}
        known_names = set()
    print(f"  known: {len(known_names)} releases")

    try:
        itunes_albums = fetch_artist_albums()
    except Exception as e:
        print(f"  ! iTunes fetch failed: {e}")
        return 1

    new_albums = [
        a for a in itunes_albums
        if normalize_name(a["collectionName"]).lower() not in known_names
    ]
    print(f"  new: {len(new_albums)}")

    if not new_albums:
        print("  nothing to do.")
        return 0

    new_releases = []
    for album in new_albums:
        try:
            duration = fetch_album_duration(album["collectionId"])
        except Exception as e:
            print(f"  ! duration fetch failed for {album['collectionName']}: {e}")
            duration = "0:00"

        release = normalize_release(album, duration)
        print(f"  + {release['name']} ({release['release_date']}, {release['duration']})")
        new_releases.append(release)

        try:
            post_to_telegram(release)
        except Exception as e:
            print(f"    ! Telegram post failed: {e}")

        time.sleep(1)  # polite gap between posts

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
