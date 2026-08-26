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

file_path = "documents/emp_1_1781283597_daily_report_2.pdf"
bucket_name = "resumes"
sign_url = f"{supabase_url}/storage/v1/object/sign/{bucket_name}/{file_path}"
r = httpx.post(sign_url, headers=headers, json={"expiresIn": 3600})
print("Sign status:", r.status_code)
print("Sign response:", r.text)

