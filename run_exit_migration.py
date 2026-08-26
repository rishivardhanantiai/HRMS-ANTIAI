import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def run_migration():
    if not DATABASE_URL:
        print("DATABASE_URL not found in .env")
        return
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        with open("schema_exit_management.sql", "r") as f:
            sql = f.read()
            
        cur.execute(sql)
        
        # Seed default templates if they don't exist
        
        # Experience Letter Template
        exp_template = """<p>[Date_of_issue]</p>
<p><strong>TO WHOMSOEVER IT MAY CONCERN</strong></p>
<p>This is to certify that <strong>[Employee_Name]</strong> (Emp ID: [Employee_ID]) was employed with <strong>[Company_Name]</strong> as <strong>[Employee_Designation]</strong> in the <strong>[Department]</strong> department from <strong>[Joining_Date]</strong> to <strong>[Last_Working_Date]</strong>.</p>
<p>During their tenure, we found them to be a dedicated and hardworking professional. We wish them success in all their future endeavors.</p>
<br><br>
<p>Sincerely,</p>
<p><strong>[HR_Name]</strong><br>Human Resources<br>[Company_Name]</p>"""

        # FNF Letter Template
        fnf_template = """<p>[Date_of_issue]</p>
<p><strong>Full & Final Settlement Statement</strong></p>
<p>Employee Name: [Employee_Name]<br>
Employee ID: [Employee_ID]<br>
Designation: [Employee_Designation]<br>
Department: [Department]<br>
Last Working Date: [Last_Working_Date]</p>
<hr>
<table border="1" cellpadding="5" cellspacing="0" style="width:100%; border-collapse: collapse;">
    <tr><th>Particulars</th><th>Amount (INR)</th></tr>
    <tr><td>Pending Salary</td><td>[Pending_Salary]</td></tr>
    <tr><td>Leave Encashment</td><td>[Leave_Encashment]</td></tr>
    <tr><td>Bonus / Incentives</td><td>[Bonus]</td></tr>
    <tr><td>Reimbursements</td><td>[Reimbursements]</td></tr>
    <tr><td><strong>Gross Payable</strong></td><td><strong>[Gross_Payable]</strong></td></tr>
    <tr><td>Deductions / Notice Recovery</td><td>[Deductions]</td></tr>
    <tr><td><strong>Net Settlement Amount</strong></td><td><strong>[FNF_Amount]</strong></td></tr>
</table>
<hr>
<p>Please find enclosed the Full & Final Settlement amount of INR [FNF_Amount]. This concludes all financial obligations between you and [Company_Name].</p>
<br><br>
<p>Sincerely,</p>
<p><strong>[HR_Name]</strong><br>Human Resources<br>[Company_Name]</p>"""

        # LOR Template
        lor_template = """<p>[Date_of_issue]</p>
<p><strong>Letter of Recommendation</strong></p>
<p>To Whom It May Concern,</p>
<p>I am writing to highly recommend <strong>[Employee_Name]</strong>, who worked with us as a <strong>[Employee_Designation]</strong> at <strong>[Company_Name]</strong> from <strong>[Joining_Date]</strong> to <strong>[Last_Working_Date]</strong>. During this time, they demonstrated excellent technical skills and played a critical role in our key projects.</p>
<p>[Employee_Name] is a fast learner with strong problem-solving abilities and consistently delivered quality work, meeting all deadlines. They were a great team player, able to communicate effectively and collaborate with both technical and non-technical team members.</p>
<p>I am confident they will make valuable contributions to any organization.</p>
<br><br>
<p>Sincerely,</p>
<p><strong>[Manager_Name]</strong><br>[Company_Name]</p>"""

        cur.execute("INSERT INTO letter_templates (template_name, template_content) VALUES (%s, %s) ON CONFLICT (template_name) DO NOTHING", ("Experience Letter", exp_template))
        cur.execute("INSERT INTO letter_templates (template_name, template_content) VALUES (%s, %s) ON CONFLICT (template_name) DO NOTHING", ("FNF Letter", fnf_template))
        cur.execute("INSERT INTO letter_templates (template_name, template_content) VALUES (%s, %s) ON CONFLICT (template_name) DO NOTHING", ("Letter of Recommendation", lor_template))
        
        # Seed company settings
        cur.execute("SELECT COUNT(*) FROM company_settings")
        if cur.fetchone()[0] == 0:
            cur.execute("""INSERT INTO company_settings 
                (company_name, company_address, company_contact, company_email, company_website) 
                VALUES ('Acme Corp', '123 Business Rd, City', '+1 234 567 8900', 'hr@acmecorp.com', 'www.acmecorp.com')""")

        conn.commit()
        print("Migration successful")
        
    except Exception as e:
        print("Migration failed:", e)
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    run_migration()
