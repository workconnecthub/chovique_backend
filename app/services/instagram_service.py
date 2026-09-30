import re
import urllib.request
import io
import logging
from typing import Optional, Dict, Any

from app.core.cloudinary import configure_cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)

# Configure Cloudinary on import
try:
    configure_cloudinary()
except Exception as e:
    logger.warning("Cloudinary configuration warning in instagram_service: %s", e)


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
    match = re.search(r"/(?:reel|p|tv)/([a-zA-Z0-9_-]+)", url.strip())
    if match:
        return match.group(1)
    return None


def fetch_instagram_reel_details(url: str, upload_to_cloudinary: bool = True) -> Dict[str, Any]:
    """
    Extracts the account handle and direct video MP4 URL from an Instagram Reel or Post.
    Optionally uploads the MP4 directly to Cloudinary so it is permanent and streams fast.
    """
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        raise ValueError("Invalid Instagram URL. Expected format: https://www.instagram.com/reel/{code}/")

    canonical_instagram_url = f"https://www.instagram.com/reel/{shortcode}/"
    embed_url = f"https://www.instagram.com/reel/{shortcode}/embed/captioned/"

    # Instagram serves the complete embed page (with video source & author) to crawler user agents
    headers = {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        req = urllib.request.Request(embed_url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.error("Failed to fetch Instagram embed page for shortcode %s: %s", shortcode, e)
        # Fallback to defaults
        return {
            "account_name": "@chovique_chocolatier",
            "video_url": None,
            "instagram_url": canonical_instagram_url,
            "shortcode": shortcode,
        }

    # 1. Extract Account Name / Handle
    user_match = re.search(r"instagram\.com/([a-zA-Z0-9._]+)/\?utm_source=ig_embed", html)
    if user_match and user_match.group(1) and user_match.group(1).lower() not in {"reel", "p", "tv", "explore"}:
        account_name = f"@{user_match.group(1)}"
    else:
        # Fallback search for any author link
        author_match = re.search(r"class=[\"'][^\"']*UsernameText[^\"']*[\"'][^>]*>(.*?)<", html)
        if author_match and author_match.group(1):
            account_name = f"@{author_match.group(1).strip()}"
        else:
            account_name = "@chovique_chocolatier"

    # 2. Extract Direct MP4 Video URL
    direct_mp4 = None
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

    # 3. Permanently host on Cloudinary if requested and available
    if direct_mp4 and upload_to_cloudinary:
        try:
            logger.info("Downloading reel video (%s) for permanent Cloudinary hosting...", shortcode)
            v_req = urllib.request.Request(direct_mp4, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(v_req, timeout=20) as v_resp:
                video_bytes = v_resp.read()

            if video_bytes and len(video_bytes) > 1000:
                upload_res = cloudinary.uploader.upload(
                    io.BytesIO(video_bytes),
                    folder="chocolate-world/reels",
                    public_id=f"ig_{shortcode}",
                    resource_type="video",
                    overwrite=True,
                )
                cloudinary_url = upload_res.get("secure_url") or upload_res.get("url")
                if cloudinary_url:
                    final_video_url = cloudinary_url
                    logger.info("Reel %s successfully hosted on Cloudinary: %s", shortcode, final_video_url)
        except Exception as e:
            logger.warning("Cloudinary upload failed for reel %s, using direct MP4: %s", shortcode, e)
            final_video_url = direct_mp4

    return {
        "account_name": account_name,
        "video_url": final_video_url,
        "instagram_url": canonical_instagram_url,
        "shortcode": shortcode,
    }
