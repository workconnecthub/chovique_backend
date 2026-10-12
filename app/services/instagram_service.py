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


def download_reel_to_bucket(url: str, shortcode: str) -> Optional[str]:
    """
    Downloads the Instagram reel video via yt-dlp and uploads it to the Tigris S3 bucket.
    Returns the permanent public/proxy media URL.
    """
    import os
    import tempfile
    try:
        import yt_dlp
        from app.services.storage_service import storage_service

        with tempfile.TemporaryDirectory() as tmpdir:
            out_tmpl = os.path.join(tmpdir, f"{shortcode}.%(ext)s")
            ydl_opts = {
                "format": "best[ext=mp4]/best",
                "outtmpl": out_tmpl,
                "quiet": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if not os.path.exists(filename):
                    files = [f for f in os.listdir(tmpdir) if os.path.isfile(os.path.join(tmpdir, f))]
                    if files:
                        filename = os.path.join(tmpdir, files[0])

                if os.path.exists(filename) and os.path.getsize(filename) > 1000:
                    with open(filename, "rb") as f:
                        video_bytes = f.read()

                    s3_key = f"chocolate-world/reels/{shortcode}.mp4"
                    hosted_url = storage_service._upload_to_s3(
                        data=video_bytes,
                        key=s3_key,
                        content_type="video/mp4",
                    )
                    logger.info("Successfully downloaded & hosted reel %s in bucket: %s", shortcode, hosted_url)
                    return hosted_url
    except Exception as e:
        logger.warning("yt-dlp download/upload failed for reel %s: %s", shortcode, e)
    return None


def fetch_instagram_reel_details(url: str, upload_to_storage: bool = True) -> Dict[str, Any]:
    """
    Extracts the account handle and downloads the video directly to the storage bucket.
    Returns a safe dictionary with permanent bucket video URL.
    """
    shortcode = extract_instagram_shortcode(url)
    if not shortcode:
        clean_url = (url or "").strip()
        extracted = ""
        url_match = re.search(r"instagram\.com/([a-zA-Z0-9._]+)/(?:reel|p|tv)/", clean_url, re.IGNORECASE)
        if url_match and url_match.group(1).lower() not in {"reel", "p", "tv", "explore", "stories", "rsrc.php"}:
            extracted = f"@{url_match.group(1)}"
        return {
            "account_name": extracted,
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

    # 1. Extract Account Name / Handle (No hardcoded seeding)
    account_name = ""
    url_handle_match = re.search(r"instagram\.com/([a-zA-Z0-9._]+)/(?:reel|p|tv)/", url or "", re.IGNORECASE)
    if url_handle_match and url_handle_match.group(1).lower() not in {"reel", "p", "tv", "explore", "stories", "rsrc.php"}:
        account_name = f"@{url_handle_match.group(1)}"

    if not account_name and html:
        user_match = re.search(r"instagram\.com/([a-zA-Z0-9._]+)/\?utm_source=ig_embed", html)
        if user_match and user_match.group(1) and user_match.group(1).lower() not in {"reel", "p", "tv", "explore", "stories", "rsrc.php"}:
            account_name = f"@{user_match.group(1)}"
        else:
            author_match = re.search(r"class=[\"'][^\"']*UsernameText[^\"']*[\"'][^>]*>(.*?)<", html)
            if author_match and author_match.group(1):
                account_name = f"@{author_match.group(1).strip()}"

    # 2. Download and Host Reel Video in Bucket
    final_video_url = None
    if upload_to_storage:
        final_video_url = download_reel_to_bucket(canonical_instagram_url, shortcode)

    # 3. Fallback extraction of direct MP4 if bucket download was skipped or failed
    if not final_video_url and html:
        mp4_match = re.search(r'(https:[^"\']+\.mp4[^"\'\\]*)', html)
        if mp4_match:
            raw_mp4 = mp4_match.group(1)
            try:
                clean_mp4 = raw_mp4.encode("utf-8").decode("unicode_escape")
            except Exception:
                clean_mp4 = raw_mp4
            clean_mp4 = clean_mp4.replace(r"\/", "/").replace("\\", "").replace(r"\u0026", "&")
            if clean_mp4.startswith("http"):
                if upload_to_storage:
                    try:
                        from app.services.storage_service import storage_service
                        req = urllib.request.Request(clean_mp4, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=15) as resp:
                            video_bytes = resp.read()
                        if len(video_bytes) > 1000:
                            s3_key = f"chocolate-world/reels/{shortcode}.mp4"
                            final_video_url = storage_service._upload_to_s3(
                                data=video_bytes,
                                key=s3_key,
                                content_type="video/mp4",
                            )
                    except Exception as e:
                        logger.warning("Failed to download fallback mp4 to bucket: %s", e)
                if not final_video_url:
                    final_video_url = clean_mp4

    return {
        "account_name": account_name,
        "video_url": final_video_url,
        "instagram_url": canonical_instagram_url,
        "shortcode": shortcode,
    }
