import calendar
from datetime import date, datetime
from utils.db import get_db, release_db
from constants import PAYROLL_STATUS
import utils.supabase_rest as supabase_rest


class PayrollEngine:

    def __init__(self):
        pass

    # ================= SALARY BREAKUP =================
    def get_monthly_salary_breakup(self, employee_id, month, year):

        conn, cur = get_db(True)

        try:
            if not conn:
                raise Exception("No DB connection")

            cur.execute("""
                SELECT structure_id, monthly_salary
                FROM employee_salary
                WHERE employee_id = %s
                AND effective_from <= %s
                ORDER BY effective_from DESC
                LIMIT 1
            """, (employee_id, date(year, month, 1)))

            row = cur.fetchone()

            if not row:
                return None

            monthly_salary = row.get("monthly_salary")
            structure_id = row.get("structure_id")

            # CASE 1 — Manual salary assigned
            if monthly_salary:

                gross = float(monthly_salary)

                return {
                    "earnings": {"Manual Salary": gross},
                    "deductions": {},
                    "gross": gross,
                    "basic": gross
                }

            # CASE 2 — Structure-based salary
            if structure_id:

                cur.execute("""
                    SELECT sc.name, sc.type, ssc.amount
                    FROM salary_structure_components ssc
                    JOIN salary_components sc
                    ON ssc.component_id = sc.id
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

            return None

        except Exception as e:
            salaries = supabase_rest.get_rows("employee_salary", {"employee_id": f"eq.{employee_id}"})
            valid_salaries = [s for s in salaries if str(s.get("effective_from", "")) <= str(date(year, month, 1))]
            if not valid_salaries:
                valid_salaries = salaries
            if not valid_salaries:
                return None
            valid_salaries.sort(key=lambda x: str(x.get("effective_from", "")), reverse=True)
            s_row = valid_salaries[0]
            monthly_salary = s_row.get("monthly_salary")
            structure_id = s_row.get("structure_id")

            if monthly_salary:
                gross = float(monthly_salary)
                return {
                    "earnings": {"Manual Salary": gross},
                    "deductions": {},
                    "gross": gross,
                    "basic": gross
                }

            if structure_id:
                sscs = supabase_rest.get_rows("salary_structure_components", {"structure_id": f"eq.{structure_id}"})
                scs = supabase_rest.get_rows("salary_components")
                sc_map = {sc["id"]: sc for sc in scs}
                earnings, deductions, gross, basic = {}, {}, 0, 0
                for ssc in sscs:
                    sc_info = sc_map.get(ssc.get("component_id"), {})
                    name = sc_info.get("name", "Component")
                    comp_type = sc_info.get("type", "earning")
                    amount = float(ssc.get("amount") or 0)
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
            return None

        finally:
            if conn:
                release_db(conn, cur)

    # ================= ATTENDANCE =================
    def get_attendance_summary(self, employee_id, month, year):

        conn, cur = get_db(True)

        try:
            if not conn:
                raise Exception("No DB connection")

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

        except Exception as e:
            records = supabase_rest.get_rows("hrms_attendance", {"employee_id": f"eq.{employee_id}"})
            filtered_records = []
            for r in records:
                ad = str(r.get("attendance_date", ""))
                if ad:
                    try:
                        dt = datetime.strptime(ad[:10], "%Y-%m-%d")
                        if dt.month == month and dt.year == year:
                            filtered_records.append(r)
                    except Exception:
                        pass
            total_days = calendar.monthrange(year, month)[1]
            working_days = sum(
                1 for day in range(1, total_days + 1)
                if date(year, month, day).weekday() != 6
            )
            stats = {"working_days": working_days, "present": 0, "paid_leave": 0, "unpaid_leave": 0, "absent": 0}
            for r in filtered_records:
                st = r.get("status")
                if st == "Present":
                    stats["present"] += 1
                elif st in ["PL", "Paid Leave"]:
                    stats["paid_leave"] += 1
                elif st in ["UL", "Unpaid Leave"]:
                    stats["unpaid_leave"] += 1
                elif st == "Absent":
                    stats["absent"] += 1
            return {
                "working_days": working_days,
                "present_days": stats["present"],
                "paid_leave_days": stats["paid_leave"],
                "unpaid_leave_days": stats["unpaid_leave"],
                "absent_days": stats["absent"]
            }

        finally:
            if conn:
                release_db(conn, cur)

    # ================= CALCULATIONS =================
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

    # ================= BONUS =================
    def get_bonus(self, employee_id, month, year):

        conn, cur = get_db(True)

        try:
            if not conn:
                raise Exception("No DB connection")

            cur.execute("""
                SELECT COALESCE(SUM(amount),0) as total
                FROM employee_bonus
                WHERE employee_id=%s
                AND month=%s
                AND year=%s
            """, (employee_id, month, year))

            row = cur.fetchone()

            return float(row["total"]) if row else 0

        except Exception as e:
            rows = supabase_rest.get_rows("employee_bonus", {
                "employee_id": f"eq.{employee_id}",
                "month": f"eq.{month}",
                "year": f"eq.{year}"
            })
            total = sum(float(r.get("amount") or 0) for r in rows)
            return float(total)

        finally:
            if conn:
                release_db(conn, cur)

    # ================= VARIABLE PAY =================
    def get_variable_pay(self, employee_id, month, year):

        conn, cur = get_db(True)

        try:
            if not conn:
                raise Exception("No DB connection")

            cur.execute("""
                SELECT
                    COALESCE(SUM(bonus),0) +
                    COALESCE(SUM(incentive),0) +
                    COALESCE(SUM(commission),0) +
                    COALESCE(SUM(esop_value),0) AS total
                FROM employee_variable_pay
                WHERE employee_id=%s
                AND month=%s
                AND year=%s
            """, (employee_id, month, year))

            row = cur.fetchone()

            return float(row["total"]) if row and row["total"] else 0

        except Exception as e:
            rows = supabase_rest.get_rows("employee_variable_pay", {
                "employee_id": f"eq.{employee_id}",
                "month": f"eq.{month}",
                "year": f"eq.{year}"
            })
            total = sum(
                float(r.get("bonus") or 0) +
                float(r.get("incentive") or 0) +
                float(r.get("commission") or 0) +
                float(r.get("esop_value") or 0)
                for r in rows
            )
            return float(total)

        finally:
            if conn:
                release_db(conn, cur)

    # ================= REIMBURSEMENTS =================
    def get_reimbursements(self, employee_id, month, year):

        conn, cur = get_db(True)

        try:
            if not conn:
                raise Exception("No DB connection")

            cur.execute("""
                SELECT COALESCE(SUM(amount),0) as total
                FROM reimbursement_requests
                WHERE employee_id=%s
                AND status='Approved'
                AND EXTRACT(MONTH FROM created_at)=%s
                AND EXTRACT(YEAR FROM created_at)=%s
            """, (employee_id, month, year))

            row = cur.fetchone()

            return float(row["total"]) if row else 0

        except Exception as e:
            rows = supabase_rest.get_rows("reimbursement_requests", {
                "employee_id": f"eq.{employee_id}",
                "status": "eq.Approved"
            })
            total = 0.0
            for r in rows:
                ca = str(r.get("created_at", ""))
                if ca:
                    try:
                        dt = datetime.strptime(ca[:10], "%Y-%m-%d")
                        if dt.month == month and dt.year == year:
                            total += float(r.get("amount") or 0)
                    except Exception:
                        pass
            return float(total)

        finally:
            if conn:
                release_db(conn, cur)

    # ================= GENERATE PAYROLL =================
    def generate_payroll(self, employee_id, month, year, generated_by):

        financial_year = f"{year}-{year+1}" if month >= 4 else f"{year-1}-{year}"

        conn, cur = get_db(True)

        try:
            if not conn:
                raise Exception("No DB connection")

            cur.execute("""
                SELECT id, status
                FROM payroll_runs
                WHERE employee_id=%s
                AND month=%s
                AND year=%s
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
                salary_data["gross"],
                attendance
            )

            pf = self.calculate_pf(salary_data["basic"])

            variable_pay = self.get_variable_pay(employee_id, month, year)
            reimbursements = self.get_reimbursements(employee_id, month, year)
            bonus = self.get_bonus(employee_id, month, year)

            net_salary = (
                salary_data["gross"]
                - attendance_deduction
                - pf
                + variable_pay
                + reimbursements
                + bonus
            )

            net_salary = round(net_salary, 2)

            cur.execute("""
                INSERT INTO payroll_runs (
                    employee_id, month, year,
                    gross_salary, attendance_deduction,
                    pf, variable_pay, bonus,
                    reimbursements, net_salary,
                    status, generated_at, generated_by, financial_year
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                employee_id, month, year,
                salary_data["gross"], attendance_deduction,
                pf, variable_pay, bonus,
                reimbursements, net_salary,
                PAYROLL_STATUS["DRAFT"],
                datetime.now(),
                generated_by,
                financial_year
            ))

            conn.commit()

            return {
                "success": True,
                "net_salary": net_salary
            }

        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass

            # Supabase REST Fallback for generate_payroll
            try:
                existing = supabase_rest.get_rows("payroll_runs", {
                    "employee_id": f"eq.{employee_id}",
                    "month": f"eq.{month}",
                    "year": f"eq.{year}"
                })
                if existing:
                    if existing[0].get("status") == PAYROLL_STATUS["LOCKED"]:
                        return {"error": "Payroll already locked."}
                    return {"error": "Payroll already generated."}

                salary_data = self.get_monthly_salary_breakup(employee_id, month, year)
                if not salary_data:
                    return {"error": "Salary structure not found."}

                attendance = self.get_attendance_summary(employee_id, month, year)
                attendance_deduction = self.calculate_attendance_deduction(salary_data["gross"], attendance)
                pf = self.calculate_pf(salary_data["basic"])
                variable_pay = self.get_variable_pay(employee_id, month, year)
                reimbursements = self.get_reimbursements(employee_id, month, year)
                bonus = self.get_bonus(employee_id, month, year)

                net_salary = round(
                    salary_data["gross"] - attendance_deduction - pf + variable_pay + reimbursements + bonus, 2
                )

                supabase_rest.insert_row("payroll_runs", {
                    "employee_id": employee_id,
                    "month": month,
                    "year": year,
                    "gross_salary": salary_data["gross"],
                    "attendance_deduction": attendance_deduction,
                    "pf": pf,
                    "variable_pay": variable_pay,
                    "bonus": bonus,
                    "reimbursements": reimbursements,
                    "net_salary": net_salary,
                    "status": PAYROLL_STATUS["DRAFT"],
                    "generated_at": datetime.now().isoformat(),
                    "generated_by": generated_by,
                    "financial_year": financial_year
                })
                return {"success": True, "net_salary": net_salary}
            except Exception as fb_err:
                return {"error": str(fb_err)}

        finally:
            if conn:
                release_db(conn, cur)


# ================= PUBLIC FUNCTION =================
def generate_payroll(employee_id, month, year, generated_by):

    engine = PayrollEngine()

    return engine.generate_payroll(
        employee_id,
        month,
        year,
        generated_by
    )