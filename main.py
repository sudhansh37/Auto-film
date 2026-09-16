import os
import json
import re
import time
import asyncio
import yt_dlp
import os
import json
import re
import time
import asyncio
import yt_dlp
import edge_tts
from google import genai
from gradio_client import Client
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 1. Environment Secrets
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
HF_TOKEN = os.environ.get("HF_TOKEN")
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

# Target Shorts Channel
TARGET_CHANNEL_URL = "https://youtube.com/@stay4ever67/shorts"

# Helper to extract file path from Gradio response dictionary
def extract_file_path(val):
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for k in ["path", "video", "file", "url"]:
            if k in val:
                res = extract_file_path(val[k])
                if res:
                    return res
        for v in val.values():
            res = extract_file_path(v)
            if res:
                return res
    if isinstance(val, (list, tuple)):
        for item in val:
            res = extract_file_path(item)
            if res:
                return res
    return None

# 2. Fetch Latest Video URL
def get_latest_video_url(channel_url):
    ydl_opts = {'extract_flat': True, 'playlist_items': '1', 'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
        entry = info['entries'][0]
        url = entry.get('url')
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        return url

# 3. Gemini Analysis & Content Generation
def generate_script_and_prompts(video_url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
    Reference YouTube video link: {video_url}

    Analyze the style, suspense, and pacing of this video. Create an entirely NEW, original 35-45 second Hindi fact/story script on a similar viral theme (to avoid reused content policy).
    Also provide 4 detailed cinematic visual prompts in English for 3-4 second video scenes.

    Return ONLY a valid JSON object without any extra text or markdown formatting:
    {{
      "title": "Viral YouTube Shorts Title #shorts",
      "description": "Shorts description with hashtags #shorts #facts #viral",
      "script": "Hindi narration script yahan...",
      "prompts": [
        "cinematic wide shot of ancient mystical ruins in dark fog, dramatic lighting, 8k",
        "close up of golden glowing ancient artifact pulsing with energy"
      ]
    }}
    """

    models_to_try = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    last_error = None

    for model_name in models_to_try:
        for attempt in range(1, 4):
            try:
                print(f"Connecting to {model_name} (Attempt {attempt}/3)...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                raw_text = response.text.strip()
                match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if match:
                    raw_text = match.group(0)
                return json.loads(raw_text)
            except Exception as e:
                print(f"Warning: {model_name} attempt {attempt} failed: {e}")
                last_error = e
                time.sleep(6)

    raise RuntimeError(f"All Gemini models failed: {last_error}")

# 4. Generate Hindi Voiceover
async def make_audio(text, output_path="voice.mp3"):
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural")
    await communicate.save(output_path)

# 5. Generate AI Video Clips via Hugging Face
def generate_clips(prompts):
    client = Client("Lightricks/ltx-video-distilled", token=HF_TOKEN)
    clip_paths = []
    
    for i, p in enumerate(prompts):
        print(f"Generating video clip {i+1}/{len(prompts)}: {p[:50]}...")
        try:
            res = client.predict(
                p,                                                      # prompt
                "blurry, distorted, ugly, watermark, text, low quality", # negative_prompt
                None,                                                   # input_image
                None,                                                   # input_video
                512,                                                    # height
                704,                                                    # width
                "text-to-video",                                        # mode
                3.0,                                                    # duration (sec)
                9,                                                      # frames to use
                42,                                                     # seed
                True,                                                   # randomize_seed
                3.0,                                                    # guidance_scale
                True,                                                   # improve_texture
                api_name="/text_to_video"
            )
            
            # Dictionary ya tuple se sahi path extract karna
            video_path = extract_file_path(res)
            
            if video_path and os.path.exists(video_path):
                clip_paths.append(video_path)
                print(f"Clip {i+1} saved successfully at: {video_path}")
            else:
                print(f"Warning: Clip {i+1} path not found: {video_path}")
        except Exception as e:
            print(f"Clip {i+1} generation failed: {e}")
            
    return clip_paths

# 6. Merge Video Clips and Audio
def build_video(clip_paths, audio_path, output_path="final_shorts.mp4"):
    valid_clips = [VideoFileClip(p) for p in clip_paths if p and os.path.exists(p)]
    if not valid_clips:
        raise RuntimeError("No video clips were generated successfully.")
        
    full_video = concatenate_videoclips(valid_clips, method="compose")
    audio = AudioFileClip(audio_path)
    
    # Audio ke hisaab se clips loop karna agar audio lambi ho
    if full_video.duration < audio.duration:
        repeat_count = int(audio.duration // full_video.duration) + 1
        full_video = concatenate_videoclips([full_video] * repeat_count, method="compose")
    
    try:
        full_video = full_video.subclipped(0, audio.duration).with_audio(audio)
    except AttributeError:
        full_video = full_video.subclip(0, audio.duration).set_audio(audio)
    
    full_video.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac"
    )

# 7. Upload to YouTube
def upload_to_youtube(video_path, title, description):
    creds = Credentials(
        None,
        refresh_token=YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET
    )
    youtube = build("youtube", "v3", credentials=creds)
    
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "28"
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print("Video uploaded successfully! ID:", response.get("id"))

# Main Pipeline Runner
def main():
    print("Step 1: Fetching reference video...")
    ref_url = get_latest_video_url(TARGET_CHANNEL_URL)
    print(f"Reference URL: {ref_url}")
    
    print("Step 2: Analyzing with Gemini...")
    data = generate_script_and_prompts(ref_url)
    
    print("Step 3: Generating Hindi Audio...")
    asyncio.run(make_audio(data["script"], "audio.mp3"))
    
    print("Step 4: Generating Video Clips from Hugging Face...")
    clips = generate_clips(data["prompts"][:4])
    
    print("Step 5: Assembling final video...")
    build_video(clips, "audio.mp3", "shorts.mp4")
    
    print("Step 6: Uploading to YouTube...")
    upload_to_youtube("shorts.mp4", data["title"], data["description"])

if __name__ == "__main__":
    main()

from google import genai
from gradio_client import Client
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 1. Environment Secrets
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
HF_TOKEN = os.environ.get("HF_TOKEN")
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

# Target Shorts Channel
TARGET_CHANNEL_URL = "https://youtube.com/@stay4ever67/shorts"

# Helper to extract file path from Gradio response dictionary
def extract_file_path(val):
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for k in ["path", "video", "file", "url"]:
            if k in val:
                res = extract_file_path(val[k])
                if res:
                    return res
        for v in val.values():
            res = extract_file_path(v)
            if res:
                return res
    if isinstance(val, (list, tuple)):
        for item in val:
            res = extract_file_path(item)
            if res:
                return res
    return None

# 2. Fetch Latest Video URL
def get_latest_video_url(channel_url):
    ydl_opts = {'extract_flat': True, 'playlist_items': '1', 'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
        entry = info['entries'][0]
        url = entry.get('url')
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"
        return url

# 3. Gemini Analysis & Content Generation
def generate_script_and_prompts(video_url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
    Reference YouTube video link: {video_url}

    Analyze the style, suspense, and pacing of this video. Create an entirely NEW, original 35-45 second Hindi fact/story script on a similar viral theme (to avoid reused content policy).
    Also provide 4 detailed cinematic visual prompts in English for 3-4 second video scenes.

    Return ONLY a valid JSON object without any extra text or markdown formatting:
    {{
      "title": "Viral YouTube Shorts Title #shorts",
      "description": "Shorts description with hashtags #shorts #facts #viral",
      "script": "Hindi narration script yahan...",
      "prompts": [
        "cinematic wide shot of ancient mystical ruins in dark fog, dramatic lighting, 8k",
        "close up of golden glowing ancient artifact pulsing with energy"
      ]
    }}
    """

    models_to_try = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    last_error = None

    for model_name in models_to_try:
        for attempt in range(1, 4):
            try:
                print(f"Connecting to {model_name} (Attempt {attempt}/3)...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                raw_text = response.text.strip()
                match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if match:
                    raw_text = match.group(0)
                return json.loads(raw_text)
            except Exception as e:
                print(f"Warning: {model_name} attempt {attempt} failed: {e}")
                last_error = e
                time.sleep(6)

    raise RuntimeError(f"All Gemini models failed: {last_error}")

# 4. Generate Hindi Voiceover
async def make_audio(text, output_path="voice.mp3"):
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural")
    await communicate.save(output_path)

# 5. Generate AI Video Clips via Hugging Face
def generate_clips(prompts):
    client = Client("Lightricks/ltx-video-distilled", token=HF_TOKEN)
    clip_paths = []
    
    for i, p in enumerate(prompts):
        print(f"Generating video clip {i+1}/{len(prompts)}: {p[:50]}...")
        try:
