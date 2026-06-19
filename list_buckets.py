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

r = httpx.get(f"{supabase_url}/storage/v1/bucket", headers=headers)
print("Status:", r.status_code)
for b in r.json():
    print(b["id"], b["name"])
