import os
import httpx
from dotenv import load_dotenv

load_dotenv()
supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
supabase_key = os.getenv("SUPABASE_KEY")

headers = {
    "apikey": supabase_key,
    "Authorization": f"Bearer {supabase_key}",
}

r = httpx.get(f"{supabase_url}/storage/v1/bucket/resumes", headers=headers)
print("Resumes bucket:", r.status_code, r.text)

r2 = httpx.get(f"{supabase_url}/storage/v1/bucket/RESUMES", headers=headers)
print("RESUMES bucket:", r2.status_code, r2.text)
