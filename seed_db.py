import sys
import os
from datetime import datetime

# Add project directory to path so we can import utils.db
sys.path.append(r"c:\Users\HP\Desktop\hrms-main")

from utils.db import get_db, release_db

def seed():
    conn, cur = get_db()
    
    applicants = [
        {
            "job_id": 1, # Software Engineer
            "applicant_name": "Aarav Sharma",
            "email": "aarav.sharma@example.com",
            "phone": "+91 98765 43210",
            "resume_url": "https://bjbjrenpttgovfxpjbil.supabase.co/storage/v1/object/public/resumes/applications/aarav_resume.pdf",
            "cover_letter": "I am a Full Stack Developer with 4 years of experience specializing in React, Node.js, and PostgreSQL. I would love to join your engineering team and build scalable products.",
            "applied_at": datetime.now()
        },
        {
            "job_id": 2, # Product Manager
            "applicant_name": "Priya Patel",
            "email": "priya.patel@example.com",
            "phone": "+91 87654 32109",
            "resume_url": "https://bjbjrenpttgovfxpjbil.supabase.co/storage/v1/object/public/resumes/applications/priya_pm_resume.pdf",
            "cover_letter": "Highly motivated Product Manager with a track record of launching user-centric mobile applications. Experienced in agile methodologies and cross-functional leadership.",
            "applied_at": datetime.now()
        },
        {
            "job_id": 3, # UI/UX Designer
            "applicant_name": "Rohan Das",
            "email": "rohan.das@example.com",
            "phone": "+91 76543 21098",
            "resume_url": "https://bjbjrenpttgovfxpjbil.supabase.co/storage/v1/object/public/resumes/applications/rohan_design_resume.pdf",
            "cover_letter": "I design clean, accessible, and delightful digital interfaces. Fluent in Figma, design systems, and user testing. Excited to bring modern aesthetics to your HRMS platform.",
            "applied_at": datetime.now()
        },
        {
            "job_id": 1, # Software Engineer
            "applicant_name": "Vikram Singh",
            "email": "vikram.singh@example.com",
            "phone": "+91 95432 10987",
            "resume_url": "https://bjbjrenpttgovfxpjbil.supabase.co/storage/v1/object/public/resumes/applications/vikram_backend_resume.pdf",
            "cover_letter": "Backend-focused Software Engineer skilled in Python (Flask/Django), Go, and database optimization. Passionate about building robust APIs and microservices architectures.",
            "applied_at": datetime.now()
        },
        {
            "job_id": 1, # Software Engineer
            "applicant_name": "Ananya Iyer",
            "email": "ananya.iyer@example.com",
            "phone": "+91 91234 56789",
            "resume_url": "https://bjbjrenpttgovfxpjbil.supabase.co/storage/v1/object/public/resumes/applications/ananya_resume.pdf",
            "cover_letter": "Recent Computer Science graduate from IIT with strong fundamentals in algorithms, data structures, and machine learning. Eager to contribute to software development projects.",
            "applied_at": datetime.now()
        }
    ]
    
    print("Seeding applicants...")
    for app in applicants:
        cur.execute("""
            INSERT INTO applications (job_id, applicant_name, email, phone, resume_url, cover_letter, applied_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            app["job_id"],
            app["applicant_name"],
            app["email"],
            app["phone"],
            app["resume_url"],
            app["cover_letter"],
            app["applied_at"]
        ))
    
    conn.commit()
    release_db(conn, cur)
    print("Successfully seeded 5 mock applicants!")

if __name__ == "__main__":
    seed()
