"""rawtoreel: raw clip in, finished reel out.

A fixed seven-step pipeline that turns a raw talking-head clip into a
finished video for YouTube, Instagram Reels, or TikTok.
"""

__version__ = "0.1.0"

STEPS = [
    "intake",
    "rough_cut",
    "graphics",
    "second_pass",
    "captions",
    "music",
    "export",
]
