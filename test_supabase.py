import os
from dotenv import load_dotenv
import httpx

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
supabase_key = os.getenv("SUPABASE_KEY")

headers = {
    "apikey": supabase_key,
    "Authorization": f"Bearer {supabase_key}",
    "Content-Type": "application/json"
}

bucket_data = {
    "id": "resumes",
    "name": "resumes",
    "public": True
}

r = httpx.post(f"{supabase_url}/storage/v1/bucket", headers=headers, json=bucket_data)
print("Create Bucket HTTP status:", r.status_code)
print("Response:", r.text)

# Also create 'documents' bucket just in case
bucket_data_docs = {
    "id": "documents",
    "name": "documents",
    "public": True
}

r2 = httpx.post(f"{supabase_url}/storage/v1/bucket", headers=headers, json=bucket_data_docs)
print("Create Documents Bucket HTTP status:", r2.status_code)
print("Response:", r2.text)

