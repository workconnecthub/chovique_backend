import re
import urllib.request
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def extract_instagram_shortcode(url: str) -> Optional[str]:
    """
    Extracts the reel/post shortcode from various Instagram URL formats:
    - https://www.instagram.com/reel/DdQYj55v0dr/
    - https://www.instagram.com/p/DdQYj55v0dr/
    - https://www.instagram.com/tv/DdQYj55v0dr/
    - https://instagr.am/reel/DdQYj55v0dr/
    """
    if not url:
        return None
    clean = url.strip()
    match = re.search(r"/(?:reel|p|tv)/([a-zA-Z0-9_-]+)", clean)
    if match:
        return match.group(1)
    return None


def fetch_instagram_reel_details(url: str, upload_to_storage: bool = False) -> Dict[str, Any]:
    """
    Extracts the account handle and direct video MP4 URL from an Instagram Reel or Post.
    Never throws unhandled exceptions — always returns a safe dictionary response.
    """
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        clean_url = (url or "").strip()
        return {
            "account_name": "@choviqueofficial",
            "video_url": None,
            "instagram_url": clean_url,
            "shortcode": "",
        }

    canonical_instagram_url = f"https://www.instagram.com/reel/{shortcode}/"
    embed_url = f"https://www.instagram.com/reel/{shortcode}/embed/captioned/"

    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    html = ""
    try:
        req = urllib.request.Request(embed_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning("Could not fetch Instagram embed page for %s: %s", shortcode, e)

    # 1. Extract Account Name / Handle
    account_name = "@choviqueofficial"
    if html:
        user_match = re.search(r"instagram\.com/([a-zA-Z0-9._]+)/\?utm_source=ig_embed", html)
        if user_match and user_match.group(1) and user_match.group(1).lower() not in {"reel", "p", "tv", "explore", "rsrc.php"}:
            account_name = f"@{user_match.group(1)}"
        else:
            author_match = re.search(r"class=[\"'][^\"']*UsernameText[^\"']*[\"'][^>]*>(.*?)<", html)
            if author_match and author_match.group(1):
                account_name = f"@{author_match.group(1).strip()}"

    # 2. Extract Direct MP4 Video URL if exposed
    direct_mp4 = None
    if html:
        mp4_match = re.search(r'(https:[^"\']+\.mp4[^"\'\\]*)', html)
        if mp4_match:
            raw_mp4 = mp4_match.group(1)
            try:
                clean_mp4 = raw_mp4.encode("utf-8").decode("unicode_escape")
            except Exception:
                clean_mp4 = raw_mp4
            clean_mp4 = clean_mp4.replace(r"\/", "/").replace("\\", "").replace(r"\u0026", "&")
            if clean_mp4.startswith("http"):
                direct_mp4 = clean_mp4

    final_video_url = direct_mp4

    # 3. Optionally upload to S3/Tigris storage if requested and available
    if direct_mp4 and upload_to_storage:
        try:
            from app.services.storage_service import storage_service
            logger.info("Downloading reel video (%s) for permanent storage hosting...", shortcode)
            v_req = urllib.request.Request(direct_mp4, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(v_req, timeout=15) as v_resp:
                video_bytes = v_resp.read()

            if video_bytes and len(video_bytes) > 1000:
                s3_key = f"chocolate-world/reels/{shortcode}.mp4"
                final_video_url = storage_service._upload_bytes(
                    data=video_bytes,
                    key=s3_key,
                    content_type="video/mp4",
                )
                logger.info("Reel %s successfully hosted: %s", shortcode, final_video_url)
        except Exception as e:
            logger.warning("Permanent storage upload skipped for reel %s: %s", shortcode, e)
            final_video_url = direct_mp4

    return {
        "account_name": account_name,
        "video_url": final_video_url,
        "instagram_url": canonical_instagram_url,
        "shortcode": shortcode,
    }
