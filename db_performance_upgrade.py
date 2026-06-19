import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

sql_commands = [
    """
    CREATE TABLE IF NOT EXISTS performance_evaluations (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES hrms_employees(id) ON DELETE CASCADE,
        evaluator_id INTEGER REFERENCES hrms_users(id) ON DELETE SET NULL,
        manager_id INTEGER REFERENCES hrms_users(id) ON DELETE SET NULL,
        evaluation_date DATE,
        evaluation_month INTEGER,
        evaluation_year INTEGER,
        evaluation_cycle INTEGER,
        evaluation_type VARCHAR(50),
        hr_score NUMERIC(5,2),
        manager_score NUMERIC(5,2),
        final_score NUMERIC(5,2),
        grade VARCHAR(50),
        strengths TEXT,
        improvements TEXT,
        hr_comments TEXT,
        manager_comments TEXT,
        goals TEXT,
        status VARCHAR(50) DEFAULT 'Pending',
        employee_acknowledged BOOLEAN DEFAULT FALSE,
        employee_comments TEXT,
        acknowledged_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS performance_ratings (
        id SERIAL PRIMARY KEY,
        evaluation_id INTEGER REFERENCES performance_evaluations(id) ON DELETE CASCADE,
        category_name VARCHAR(100),
        rating INTEGER,
        evaluator_type VARCHAR(50)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS performance_improvement_plans (
        id SERIAL PRIMARY KEY,
        evaluation_id INTEGER REFERENCES performance_evaluations(id) ON DELETE CASCADE,
        employee_id INTEGER REFERENCES hrms_employees(id) ON DELETE CASCADE,
        target_score NUMERIC(5,2),
        deadline DATE,
        action_items TEXT,
        status VARCHAR(50) DEFAULT 'Active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS performance_notifications (
        id SERIAL PRIMARY KEY,
        employee_id INTEGER REFERENCES hrms_employees(id) ON DELETE CASCADE,
        evaluation_date DATE,
        notification_type VARCHAR(50),
        status VARCHAR(50) DEFAULT 'Unread',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
]

def upgrade_db():
    print("Connecting to database...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        for idx, cmd in enumerate(sql_commands):
            try:
                cur.execute(cmd)
                conn.commit()
                print(f"Successfully executed command {idx+1}")
            except Exception as e:
                print(f"Error executing command {idx+1}: {e}")
                conn.rollback()
                
        cur.close()
        conn.close()
        print("Database upgrade completed successfully.")
    except Exception as e:
        print(f"Database connection failed: {e}")

if __name__ == "__main__":
    upgrade_db()
