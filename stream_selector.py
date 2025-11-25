import subprocess
import logging
import re
import math

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_audio_volume(url, start_time=300, duration=5):
    """
    Detects the mean volume of a segment of audio.
    start_time: offset in seconds (default 300s = 5min to skip intro silence)
    Returns: mean_volume in dB.
    """
    try:
        # ffmpeg command to seek to start_time and analyze duration
        # -ss positions the input, -t limits duration
        cmd = [
            'ffmpeg',
            '-headers', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n',
            '-ss', str(start_time),
            '-t', str(duration),
            '-i', url,
            '-af', 'volumedetect',
            '-f', 'null',
            '-'
        ]
        
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=30)
        
        match = re.search(r'mean_volume:\s+(-?[\d\.]+)\s+dB', result.stderr)
        if match:
            return float(match.group(1))
        return -99.9 
        
    except Exception as e:
        logger.warning(f"Volume detection at {start_time}s failed: {e}")
        return -99.9

def is_teacher_stream(url):
    """
    Determines if a URL is likely the teacher's stream.
    Strategy:
    1. Check URL keywords (cam vs vga).
    2. Check audio volume at multiple points to avoid intro silence.
    """
    
    # 1. Heuristics
    lower_url = url.lower()
    if 'vga' in lower_url or 'desktop' in lower_url or 'screen' in lower_url:
        # Strong signal it's screen, but let's verify with audio if unsure
        logger.info(f"URL heuristic: Likely Screen share -> {url}")
        return False 
    
    if 'cam' in lower_url or 'teacher' in lower_url or 'mobile' in lower_url:
        logger.info(f"URL heuristic: Likely Teacher camera -> {url}")
        return True

    # 2. Audio Analysis (Multi-point)
    # Check at 5 minutes, and if silent, try 15 minutes.
    check_points = [300, 900, 60] # 5min, 15min, 1min
    
    for point in check_points:
        logger.info(f"Checking audio volume at {point}s for: {url}...")
        volume = get_audio_volume(url, start_time=point)
        logger.info(f"Detected volume at {point}s: {volume} dB")
        
        # If we find good audio (> -60dB), it's likely the teacher
        if volume > -60.0:
            logger.info(f"Active audio detected at {point}s.")
            return True
            
    logger.info("Stream seems silent across checks. Likely screen.")
    return False

def select_best_stream(urls):
    """
    Fallback selector if API interception fails.
    """
    if not urls:
        return None
        
    logger.info("Running fallback stream selector (Audio Analysis)...")
    
    # Filter candidates
    candidates = [u for u in urls if '.mp4' in u or '.m3u8' in u]
    if not candidates:
        return None
        
    # Prioritize based on heuristic first to save time
    for url in candidates:
        if is_teacher_stream(url):
            return url
            
    # If no teacher stream confirmed, default to the first one that isn't explicitly 'vga'
    # or just the first one.
    return candidates[0]
