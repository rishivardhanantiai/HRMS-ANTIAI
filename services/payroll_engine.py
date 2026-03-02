import calendar
from datetime import date, datetime
from utils.db import get_db, release_db
from constants import PAYROLL_STATUS


class PayrollEngine:
    def __init__(self):
        pass

    # =====================================================
    # SALARY BREAKUP
    # =====================================================
    def get_monthly_salary_breakup(self, employee_id, month, year):
        conn, cur = get_db(True)
        try:
            cur.execute("""
                SELECT structure_id
                FROM employee_salary
                WHERE employee_id = %s
                AND effective_from <= %s
                ORDER BY effective_from DESC
                LIMIT 1
            """, (employee_id, date(year, month, 1)))

            row = cur.fetchone()
            if not row:
                return None

            structure_id = row["structure_id"]

            cur.execute("""
                SELECT sc.name, sc.type, ssc.amount
                FROM salary_structure_components ssc
                JOIN salary_components sc ON ssc.component_id = sc.id
                WHERE ssc.structure_id = %s
            """, (structure_id,))

            components = cur.fetchall()

            earnings = {}
            deductions = {}
            gross = 0
            basic = 0

            for comp in components:
                name = comp["name"]
                comp_type = comp["type"]
                amount = float(comp["amount"])

                if comp_type == "earning":
                    earnings[name] = amount
                    gross += amount
                    if name.lower() == "basic":
                        basic = amount
                else:
                    deductions[name] = amount

            return {
                "earnings": earnings,
                "deductions": deductions,
                "gross": gross,
                "basic": basic
            }
        finally:
            release_db(conn, cur)

    # =====================================================
    # ATTENDANCE
    # =====================================================
    def get_attendance_summary(self, employee_id, month, year):
        conn, cur = get_db(True)
        try:
            cur.execute("""
                SELECT status
                FROM hrms_attendance
                WHERE employee_id = %s
                AND EXTRACT(MONTH FROM attendance_date) = %s
                AND EXTRACT(YEAR FROM attendance_date) = %s
            """, (employee_id, month, year))

            records = cur.fetchall()

            total_days = calendar.monthrange(year, month)[1]

            working_days = sum(
                1 for day in range(1, total_days + 1)
                if date(year, month, day).weekday() != 6
            )

            stats = {
                "working_days": working_days,
                "present": 0,
                "paid_leave": 0,
                "unpaid_leave": 0,
                "absent": 0
            }

            for r in records:
                status = r["status"]
                if status == "Present":
                    stats["present"] += 1
                elif status in ["PL", "Paid Leave"]:
                    stats["paid_leave"] += 1
                elif status in ["UL", "Unpaid Leave"]:
                    stats["unpaid_leave"] += 1
                elif status == "Absent":
                    stats["absent"] += 1

            return {
                "working_days": working_days,
                "present_days": stats["present"],
                "paid_leave_days": stats["paid_leave"],
                "unpaid_leave_days": stats["unpaid_leave"],
                "absent_days": stats["absent"]
            }
        finally:
            release_db(conn, cur)

    # =====================================================
    # CALCULATIONS
    # =====================================================
    def calculate_attendance_deduction(self, gross_salary, attendance_summary):
        working_days = attendance_summary["working_days"]
        if working_days == 0:
            return 0

        daily_salary = gross_salary / working_days
        deduction_days = (
            attendance_summary["unpaid_leave_days"]
            + attendance_summary["absent_days"]
        )
        return round(daily_salary * deduction_days, 2)

    def calculate_pf(self, basic_salary):
        return round(basic_salary * 0.12, 2)

    # =====================================================
    # INDIAN TAX ENGINE
    # =====================================================
    def calculate_indian_tax(self, gross_salary, employee_id, financial_year):
        conn, cur = get_db(True)
        try:
            cur.execute("""
                SELECT regime, section_80c, section_80d,
                       housing_loan_interest, other_deductions
                FROM employee_tax_declarations
                WHERE employee_id=%s AND financial_year=%s
                ORDER BY created_at DESC
                LIMIT 1
            """, (employee_id, financial_year))

            decl = cur.fetchone()
            annual_income = gross_salary * 12

            if not decl:
                return 0

            regime = decl["regime"]

            if regime == "NEW":
                if annual_income <= 300000:
                    annual_tax = 0
                elif annual_income <= 600000:
                    annual_tax = (annual_income - 300000) * 0.05
                elif annual_income <= 900000:
                    annual_tax = 15000 + (annual_income - 600000) * 0.10
                elif annual_income <= 1200000:
                    annual_tax = 45000 + (annual_income - 900000) * 0.15
                else:
                    annual_tax = 90000 + (annual_income - 1200000) * 0.20
            else:
                deductions = (
                    min(decl["section_80c"], 150000)
                    + decl["section_80d"]
                    + decl["housing_loan_interest"]
                    + decl["other_deductions"]
                )

                taxable_income = max(0, annual_income - deductions)

                if taxable_income <= 250000:
                    annual_tax = 0
                elif taxable_income <= 500000:
                    annual_tax = (taxable_income - 250000) * 0.05
                elif taxable_income <= 1000000:
                    annual_tax = 12500 + (taxable_income - 500000) * 0.20
                else:
                    annual_tax = 112500 + (taxable_income - 1000000) * 0.30

            return round(annual_tax / 12, 2)

        finally:
            release_db(conn, cur)

    # =====================================================
    # BONUS
    # =====================================================
    def get_bonus(self, employee_id, month, year):
        conn, cur = get_db(True)
        try:
            cur.execute("""
                SELECT COALESCE(SUM(amount),0) as total
                FROM employee_bonus
                WHERE employee_id=%s AND month=%s AND year=%s
            """, (employee_id, month, year))

            row = cur.fetchone()
            return float(row["total"]) if row else 0
        finally:
            release_db(conn, cur)

    # =====================================================
    # VARIABLE & REIMBURSEMENT
    # =====================================================
    def get_variable_pay(self, employee_id, month, year):
        conn, cur = get_db(True)
        try:
            cur.execute("""
                SELECT COALESCE(SUM(amount),0) as total
                FROM employee_variable_pay
                WHERE employee_id=%s AND month=%s AND year=%s
            """, (employee_id, month, year))
            row = cur.fetchone()
            return float(row["total"]) if row else 0
        finally:
            release_db(conn, cur)

    def get_reimbursements(self, employee_id, month, year):
        conn, cur = get_db(True)
        try:
            cur.execute("""
                SELECT COALESCE(SUM(amount),0) as total
                FROM reimbursement_requests
                WHERE employee_id=%s AND status='Approved'
                AND month=%s AND year=%s
            """, (employee_id, month, year))
            row = cur.fetchone()
            return float(row["total"]) if row else 0
        finally:
            release_db(conn, cur)

    # =====================================================
    # GRATUITY (For Exit Use)
    # =====================================================
    def calculate_gratuity(self, employee_id, basic_salary):
        conn, cur = get_db(True)
        try:
            cur.execute("""
                SELECT joining_date
                FROM hrms_employees
                WHERE id=%s
            """, (employee_id,))
            row = cur.fetchone()

            if not row or not row["joining_date"]:
                return 0

            years = (date.today() - row["joining_date"]).days / 365
            if years < 5:
                return 0

            gratuity = (basic_salary * 15/26) * int(years)
            return round(gratuity, 2)
        finally:
            release_db(conn, cur)

    # =====================================================
    # GENERATE PAYROLL
    # =====================================================
    def generate_payroll(self, employee_id, month, year, generated_by):

        financial_year = f"{year}-{year+1}" if month >= 4 else f"{year-1}-{year}"

        conn, cur = get_db(True)
        try:
            cur.execute("""
                SELECT id, status
                FROM payroll_runs
                WHERE employee_id=%s AND month=%s AND year=%s
            """, (employee_id, month, year))
            existing = cur.fetchone()

            if existing:
                if existing["status"] == PAYROLL_STATUS["LOCKED"]:
                    return {"error": "Payroll already locked."}
                return {"error": "Payroll already generated."}

            salary_data = self.get_monthly_salary_breakup(employee_id, month, year)
            if not salary_data:
                return {"error": "Salary structure not found."}

            attendance = self.get_attendance_summary(employee_id, month, year)

            attendance_deduction = self.calculate_attendance_deduction(
                salary_data["gross"], attendance
            )

            pf = self.calculate_pf(salary_data["basic"])

            tax = self.calculate_indian_tax(
                salary_data["gross"],
                employee_id,
                financial_year
            )

            variable_pay = self.get_variable_pay(employee_id, month, year)
            reimbursements = self.get_reimbursements(employee_id, month, year)
            bonus = self.get_bonus(employee_id, month, year)

            net_salary = (
                salary_data["gross"]
                - attendance_deduction
                - pf
                - tax
                + variable_pay
                + reimbursements
                + bonus
            )

            net_salary = round(net_salary, 2)

            cur.execute("""
                INSERT INTO payroll_runs (
                    employee_id, month, year,
                    gross_salary, attendance_deduction,
                    pf, tax, variable_pay, bonus,
                    reimbursements, net_salary,
                    status, generated_at, generated_by, financial_year
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                employee_id, month, year,
                salary_data["gross"], attendance_deduction,
                pf, tax, variable_pay, bonus,
                reimbursements, net_salary,
                PAYROLL_STATUS["DRAFT"],
                datetime.now(),
                generated_by,
                financial_year
            ))

            conn.commit()
            return {"success": True, "net_salary": net_salary}

        except Exception as e:
            conn.rollback()
            return {"error": str(e)}
        finally:
            release_db(conn, cur)


def generate_payroll(employee_id, month, year, generated_by):
    engine = PayrollEngine()
    return engine.generate_payroll(employee_id, month, year, generated_by)