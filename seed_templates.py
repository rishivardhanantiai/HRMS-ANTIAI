import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
reqs = ['Experience Letter', 'FNF Letter', 'LOR']
for req in reqs:
    if req == 'Experience Letter':
        content = """<h3 style="text-align: center;">EXPERIENCE CERTIFICATE</h3>
<p>Date: [Date_of_issue]</p>
<p><strong>To Whomsoever It May Concern</strong></p>
<p>This is to certify that <strong>[Employee_Name]</strong> (Emp ID: [Employee_ID]) was employed with <strong>[Company_Name]</strong> as <strong>[Designation]</strong> in the <strong>[Department]</strong> department.</p>
<p>Their tenure with us was from <strong>[Joining_Date]</strong> to <strong>[Last_Working_Date]</strong>.</p>
<p>During their tenure, we found them to be professional, diligent, and hardworking. We wish them all the best in their future endeavors.</p>
<br><br>
<p>For <strong>[Company_Name]</strong></p>
<p><strong>[HR_Name]</strong><br>Human Resources</p>"""
    elif req == 'FNF Letter':
        content = """<h3 style="text-align: center;">FULL & FINAL SETTLEMENT</h3>
<p>Date: [Settlement_Date]</p>
<p><strong>Employee Name:</strong> [Employee_Name]<br>
<strong>Employee ID:</strong> [Employee_ID]</p>
<p>This document serves as the final settlement details for your tenure ending on <strong>[Last_Working_Date]</strong>.</p>
<table border="1" cellpadding="5" cellspacing="0" style="width: 100%; border-collapse: collapse;">
<tr><td>Pending Salary</td><td>Rs. [Pending_Salary]</td></tr>
<tr><td>Leave Encashment</td><td>Rs. [Leave_Encashment]</td></tr>
<tr><td>Bonus / Incentives</td><td>Rs. [Bonus]</td></tr>
<tr><td>Deductions</td><td>Rs. [Deductions]</td></tr>
<tr><th>Total FNF Amount</th><th>Rs. [FNF_Amount]</th></tr>
</table>
<p>This amount will be processed to your registered salary account within the next 3 working days.</p>
<p>For any queries, please reach out to HR.</p>"""
    else:
        content = """<h3 style="text-align: center;">LETTER OF RECOMMENDATION</h3>
<p>Date: [Date_of_issue]</p>
<p><strong>To Whom It May Concern</strong></p>
<p>It is my pleasure to recommend <strong>[Employee_Name]</strong>, who worked with us as a <strong>[Designation]</strong> in the <strong>[Department]</strong> department from <strong>[Joining_Date]</strong> to <strong>[Last_Working_Date]</strong>.</p>
<p>During their time here, they demonstrated excellent skills in <strong>[Key_Skills]</strong> and successfully contributed to <strong>[Projects]</strong>.</p>
<p>They are a fast learner, a great team player, and I am confident they will be a valuable addition to any organization.</p>
<br><br>
<p>Sincerely,</p>
<p><strong>[HR_Name]</strong><br>[Company_Name]</p>"""
    cur.execute('INSERT INTO letter_templates (template_name, template_content) VALUES (%s, %s)', (req, content))
conn.commit()
print('Templates seeded.')
