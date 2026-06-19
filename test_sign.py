import os
import httpx
from dotenv import load_dotenv

load_dotenv()
supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
supabase_key = os.getenv("SUPABASE_KEY")

headers = {
    "apikey": supabase_key,
    "Authorization": f"Bearer {supabase_key}",
    "Content-Type": "application/json"
}

url = f"{supabase_url}/storage/v1/object/sign/resumes/test2.txt"
r = httpx.post(url, headers=headers, json={"expiresIn": 3600})
print("Sign status:", r.status_code)
print("Sign response:", r.text)

