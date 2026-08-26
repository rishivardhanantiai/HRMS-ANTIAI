import os
import httpx
from dotenv import load_dotenv

load_dotenv()
supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
supabase_key = os.getenv("SUPABASE_KEY")

headers = {
    "apikey": supabase_key,
    "Authorization": f"Bearer {supabase_key}",
    "Content-Type": "text/plain",
    "x-upsert": "false"
}

upload_url = f"{supabase_url}/storage/v1/object/nonexistentbucket123/test.txt"
r = httpx.post(upload_url, content=b"test", headers=headers)
print("Upload status:", r.status_code)
print("Upload response:", r.text)

upload_url2 = f"{supabase_url}/storage/v1/object/resumes/test2.txt"
r2 = httpx.post(upload_url2, content=b"test", headers=headers)
print("Upload resumes status:", r2.status_code)
print("Upload resumes response:", r2.text)

