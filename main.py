import os
import json
import asyncio
import yt_dlp
import edge_tts
from google import genai
from gradio_client import Client
from moviepy import VideoFileClip, AudioFileClip, concatenate_videoclips
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 1. Credentials from Environment
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
HF_TOKEN = os.environ.get("HF_TOKEN")
YT_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YT_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

TARGET_CHANNEL_URL = "https://www.youtube.com/@YOUR_TARGET_CHANNEL/shorts"

# 2. Fetch Latest Video Link
def get_latest_video_url(channel_url):
    ydl_opts = {'extract_flat': True, 'playlist_items': '1'}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
        return info['entries'][0]['url']

# 3. Gemini Analysis & Prompt Creation
def generate_script_and_prompts(video_url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
    Analyze this reference YouTube video link: {video_url}
    
    Reverse-engineer its pacing, hook style, and suspense. Create an entirely NEW, original 40-50 second Hindi fact script on a similar trending/mysterious theme (to avoid copyright/reuse issues).
    Also write 8 sequential English AI video prompts (each representing a 4-5 second visual scene).

    Return ONLY a raw JSON object (no markdown code blocks, no backticks):
    {{
      "title": "Catchy YouTube Shorts Title with #shorts",
      "description": "Shorts description with tags",
      "script": "Poori Hindi narration script yahan...",
      "prompts": [
        "cinematic 8k shot of ancient jungle ruins, moody lighting",
        "close up of golden artifact glowing in dark cave"
      ]
    }}
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    raw_text = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(raw_text)

# 4. Generate Hindi Voiceover (Edge-TTS)
async def make_audio(text, output_path="voice.mp3"):
    communicate = edge_tts.Communicate(text, "hi-IN-MadhurNeural")
    await communicate.save(output_path)

# 5. Generate AI Video Clips (Hugging Face)
def generate_clips(prompts):
    client = Client("Lightricks/LTX-Video", hf_token=HF_TOKEN)
    clip_paths = []
    
    for i, p in enumerate(prompts):
        print(f"Generating clip {i+1}/{len(prompts)}...")
        try:
            res = client.predict(
                prompt=p,
                negative_prompt="blurry, distorted, ugly, watermark, text",
                api_name="/generate_video"
            )
            clip_paths.append(res)
        except Exception as e:
            print(f"Error on prompt {i+1}: {e}")
            
    return clip_paths

# 6. Assemble Video (MoviePy)
def build_video(clip_paths, audio_path, output_path="final_shorts.mp4"):
    clips = [VideoFileClip(p) for p in clip_paths if p and os.path.exists(p)]
    full_video = concatenate_videoclips(clips, method="compose")
    audio = AudioFileClip(audio_path)
    
    full_video = full_video.with_audio(audio)
    full_video = full_video.with_duration(audio.duration)
    
    full_video.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac"
    )

# 7. Upload to YouTube via Refresh Token
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
            "categoryId": "28"  # Science & Technology
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False
        }
    }
    
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    print("Video uploaded successfully! Video ID:", response.get("id"))

# Main Runner
def main():
    print("Step 1: Fetching reference video...")
    ref_url = get_latest_video_url("https://youtube.com/@stay4ever67?si=d7zngZj4wZ2zlrTO")
    
    print("Step 2: Analyzing with Gemini...")
    data = generate_script_and_prompts(ref_url)
    
    print("Step 3: Generating Hindi Audio...")
    asyncio.run(make_audio(data["script"], "audio.mp3"))
    
    print("Step 4: Generating Video Clips...")
    clips = generate_clips(data["prompts"][:8])
    
    print("Step 5: Stitching Final Video...")
    build_video(clips, "audio.mp3", "shorts.mp4")
    
    print("Step 6: Uploading to YouTube...")
    upload_to_youtube("shorts.mp4", data["title"], data["description"])

if __name__ == "__main__":
    main()

