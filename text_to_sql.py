"""
Natural Language to SQL Query System (Text-to-SQL)
--------------------------------------------------
Translates natural-language questions into executable SQL queries.

Features:
  - LLM-based SQL generation from a natural-language question
  - Output sanitisation (handles markdown fences and reasoning-model <think> tags)
  - Self-correction: retries with the error message fed back to the model
  - Safety validation: read-only whitelist, blocks destructive statements
  - Evaluation suite based on execution accuracy

Model access is via the Groq API (OpenAI-compatible, free tier).
"""

import os
import re
import sqlite3

import pandas as pd
from dotenv import load_dotenv
from groq import Groq

# --- Configuration ---------------------------------------------------------

MODEL = "openai/gpt-oss-120b"

load_dotenv()  # reads GROQ_API_KEY from a local .env file
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# --- Database setup ---------------------------------------------------------

# In-memory SQLite database. Three tables are used to support multi-table joins.
conn = sqlite3.connect(":memory:")
conn.executescript("""
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS orders;

CREATE TABLE students (
    id INTEGER, name TEXT, age INTEGER, city TEXT, score INTEGER
);
INSERT INTO students VALUES
(1, 'Alice',   20, 'London',     85),
(2, 'Bob',     19, 'Manchester', 92),
(3, 'Charlie', 21, 'London',     78),
(4, 'Diana',   20, 'Bristol',    88),
(5, 'Ethan',   22, 'Manchester', 70);

CREATE TABLE customers (
    customer_id INTEGER, name TEXT, city TEXT
);
INSERT INTO customers VALUES
(1, 'Alice',   'London'),
(2, 'Bob',     'Manchester'),
(3, 'Charlie', 'Bristol');

CREATE TABLE orders (
    order_id INTEGER, customer_id INTEGER, product TEXT, amount INTEGER
);
INSERT INTO orders VALUES
(101, 1, 'Phone',    5000),
(102, 1, 'Earbuds',   800),
(103, 2, 'Laptop',   8000),
(104, 3, 'Keyboard',  300),
(105, 2, 'Mouse',     200);
""")
conn.commit()


def run_query(sql):
    """Execute a SQL query and return the result as a DataFrame."""
    return pd.read_sql_query(sql, conn)


# --- SQL generation ---------------------------------------------------------

def clean_sql(raw):
    """Strip reasoning tags and markdown fences, leaving only the SQL."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    cleaned = re.sub(r"```sql", "", cleaned)
    cleaned = re.sub(r"```", "", cleaned)
    return cleaned.strip()


def generate_sql(question, error_info=None):
    """Generate a SQL query for a question. If error_info is given, ask the
    model to correct its previous attempt (self-correction)."""
    prompt = f"""You are a SQL generation assistant. The database has these tables:

Table students:
- id, name, age, city, score

Table customers:
- customer_id, name, city

Table orders:
- order_id, customer_id (references customers), product, amount

Generate a single SQLite query for the user's question.
Use JOIN when the question requires data from more than one table.
Return only the SQL statement, with no explanation and no markdown.

User question: {question}
"""
    if error_info:
        prompt += f"""
Your previous SQL failed to execute.
Error: {error_info}
Analyse the cause and return a corrected query.
"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return clean_sql(response.choices[0].message.content)


# --- Safety validation ------------------------------------------------------

def is_safe(sql):
    """Allow read-only SELECT queries only; block destructive statements.
    Returns (is_safe, reason)."""
    sql_upper = sql.upper().strip()
    dangerous = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "CREATE"]

    if not sql_upper.startswith("SELECT"):
        return False, "Only read-only SELECT queries are allowed"
    for word in dangerous:
        if word in sql_upper:
            return False, f"Blocked destructive operation: {word}"
    return True, "safe"


# --- Main entry point -------------------------------------------------------

def ask(question, max_retries=2):
    """Answer a natural-language question: generate SQL, validate, execute,
    and retry on failure up to max_retries times."""
    error_info = None

    for attempt in range(max_retries + 1):
        sql = generate_sql(question, error_info)
        print(f"Attempt {attempt + 1}, generated SQL: {sql}")

        safe, reason = is_safe(sql)
        if not safe:
            print(f"Safety check failed: {reason}")
            return None

        try:
            result = run_query(sql)
            print("Executed successfully")
            return result
        except Exception as e:
            error_info = str(e)
            print(f"Execution failed: {error_info}")
            print("Retrying with error feedback...")

    print("Failed after multiple attempts")
    return None


# --- Evaluation -------------------------------------------------------------

# Each case is (question, gold_sql). The gold SQL is a trusted reference answer.
test_cases = [
    ("How many students are in London?",
     "SELECT COUNT(*) FROM students WHERE city = 'London'"),

    ("List all students in Manchester",
     "SELECT * FROM students WHERE city = 'Manchester'"),

    ("Who has the highest score?",
     "SELECT name FROM students ORDER BY score DESC LIMIT 1"),

    ("What is the average score of all students?",
     "SELECT AVG(score) FROM students"),

    ("Which city has the highest average score?",
     "SELECT city FROM students GROUP BY city ORDER BY AVG(score) DESC LIMIT 1"),

    ("Which students are older than 20?",
     "SELECT * FROM students WHERE age > 20"),

    ("How many students are in each city?",
     "SELECT city, COUNT(*) FROM students GROUP BY city"),

    ("The two students with the lowest scores",
     "SELECT * FROM students ORDER BY score LIMIT 2"),

    ("How much has each customer spent in total?",
     """SELECT customers.name, SUM(orders.amount)
        FROM customers JOIN orders
        ON customers.customer_id = orders.customer_id
        GROUP BY customers.name"""),

    ("Which customer has spent the most?",
     """SELECT customers.name, SUM(orders.amount) AS total
        FROM customers JOIN orders
        ON customers.customer_id = orders.customer_id
        GROUP BY customers.name
        ORDER BY total DESC LIMIT 1"""),
]


def normalize(df):
    """Reduce a result table to a sorted list of its cell values, so that
    differences in column names, column order and row order are ignored."""
    values = [str(v) for v in df.values.flatten().tolist()]
    return sorted(values)


def evaluate():
    """Run every test case and report execution accuracy.

    Note: automatic comparison can produce false negatives (e.g. when the model
    returns a correct answer with an extra column). Such cases are flagged for
    manual review rather than assumed wrong.
    """
    correct = 0
    total = len(test_cases)

    for question, gold_sql in test_cases:
        pred_sql = generate_sql(question)
        try:
            is_correct = normalize(run_query(pred_sql)) == normalize(run_query(gold_sql))
        except Exception:
            is_correct = False

        correct += is_correct
        print(f"{'PASS' if is_correct else 'FAIL'}  {question}")

    accuracy = correct / total * 100
    print("=" * 50)
    print(f"Accuracy: {correct}/{total} = {accuracy:.1f}%")
    return accuracy


if __name__ == "__main__":
    # Example usage
    print(ask("Which city has the highest average score?"))
    print()
    evaluate()
