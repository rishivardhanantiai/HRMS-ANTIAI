import re

app_path = r"c:\Users\HP\Desktop\ANTIAI\HRMS-NEW-main\app.py"
with open(app_path, "r", encoding="utf-8") as f:
    app_content = f.read()

# Fix Conflict 1 in app.py
conflict1_pattern = r"<<<<<<< HEAD\n\s*if selected_job:.*?>>>>>>> user-repo/main"

replacement1 = """        cur.execute("SELECT id, title FROM jobs ORDER BY created_at DESC")
        jobs = cur.fetchall()

        if selected_job:
            cur.execute(\"\"\"
                SELECT
                    a.id,
                    j.title AS job_title,
                    a.applied_at,
                    a.applicant_name,
                    a.email,
                    a.phone,
                    a.resume_url,
                    a.cover_letter,
                    a.status
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE a.job_id = %s
                ORDER BY a.id DESC
            \"\"\", (selected_job,))
        else:
            cur.execute(\"\"\"
                SELECT
                    a.id,
                    j.title AS job_title,
                    a.applied_at,
                    a.applicant_name,
                    a.email,
                    a.phone,
                    a.resume_url,
                    a.cover_letter,
                    a.status
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                ORDER BY a.id DESC
            \"\"\")

        applications = cur.fetchall()
        release_db(conn, cur)
    except Exception:
        jobs = supabase_rest.get_rows(
            "jobs",
            {"select": "id,title", "order": "created_at.desc"},
        )
        selected_filter = {"select": "id,job_id,applicant_name,email,phone,resume_url,applied_at,cover_letter,status", "order": "created_at.desc"}
        if selected_job:
            selected_filter["job_id"] = f"eq.{selected_job}"
        app_rows = supabase_rest.get_rows("applications", selected_filter)
        job_lookup = {str(j.get("id")): j.get("title") for j in jobs}
        applications = [
            {
                "id": a.get("id"),
                "job_title": job_lookup.get(str(a.get("job_id")), "-"),
                "applicant_name": a.get("applicant_name"),
                "applied_at": a.get("applied_at"),
                "email": a.get("email"),
                "phone": a.get("phone"),
                "resume_url": a.get("resume_url"),
                "cover_letter": a.get("cover_letter"),
                "status": a.get("status")
            }
            for a in app_rows
        ]"""

app_content = re.sub(conflict1_pattern, replacement1, app_content, flags=re.DOTALL)

# Fix Conflict 2 in app.py
conflict2_pattern = r"<<<<<<< HEAD\n\s*base_query = \"\"\".*?>>>>>>> user-repo/main"
replacement2 = """        base_query = \"\"\"
            SELECT
                j.title AS Job,
                a.applied_at AS Applied_At,
                a.applicant_name AS Applicant,
                a.email AS Email,
                a.phone AS Phone,
                a.resume_url AS Resume_URL,
                a.cover_letter AS Cover_Letter,
                a.status AS Status
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
        \"\"\""""

app_content = re.sub(conflict2_pattern, replacement2, app_content, flags=re.DOTALL)

with open(app_path, "w", encoding="utf-8") as f:
    f.write(app_content)

# Now fix templates/applications.html
html_path = r"c:\Users\HP\Desktop\ANTIAI\HRMS-NEW-main\templates\applications.html"
with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

# Fix Conflict 1 in HTML (CSS)
html_conflict1 = r"<<<<<<< HEAD\n\s*.status-select \{.*?=======\n(.*?)\n>>>>>>> user-repo/main"
def repl1(m):
    # keep both! we just extract the HEAD part and the user-repo/main part
    # Actually wait, m.group(0) is the full match. Let's just remove the markers.
    text = m.group(0)
    text = text.replace("<<<<<<< HEAD\n", "")
    text = text.replace("=======\n", "")
    text = text.replace(">>>>>>> user-repo/main\n", "")
    text = text.replace(">>>>>>> user-repo/main", "")
    return text

html_content = re.sub(r"<<<<<<< HEAD\n(.*?)\n=======\n(.*?)\n>>>>>>> user-repo/main", 
                      lambda m: m.group(1) + "\n" + m.group(2), html_content, flags=re.DOTALL)

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print("Conflicts resolved programmatically!")
