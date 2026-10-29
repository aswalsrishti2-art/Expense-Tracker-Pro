from flask import Flask, render_template, request, redirect, url_for, flash, Response
import sqlite3
import csv
import io
from datetime import date, datetime

app = Flask(__name__)
app.secret_key = "change-this-secret-key"
DB_PATH = "expenses.db"
CATEGORIES = ["Food", "Travel", "Shopping", "Education", "Bills", "Entertainment", "Health", "Other"]
PAYMENT_METHODS = ["Cash", "UPI", "Card", "Net Banking"]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                amount REAL NOT NULL CHECK(amount > 0),
                category TEXT NOT NULL,
                expense_date TEXT NOT NULL,
                payment TEXT NOT NULL,
                notes TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('monthly_budget', '10000')"
        )

def get_budget(conn):
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'monthly_budget'"
    ).fetchone()
    try:
        return float(row["value"]) if row else 10000.0
    except (ValueError, TypeError):
        return 10000.0

@app.route("/")
def index():
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    month_end = today.isoformat()
    search = request.args.get("search", "").strip()
    category_filter = request.args.get("category", "").strip()
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    query = "SELECT * FROM expenses WHERE 1=1"
    params = []
    if search:
        query += " AND (title LIKE ? OR notes LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    if category_filter in CATEGORIES:
        query += " AND category = ?"
        params.append(category_filter)
    if start_date:
        query += " AND expense_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND expense_date <= ?"
        params.append(end_date)
    query += " ORDER BY expense_date DESC, id DESC"

    with get_db() as conn:
        expenses = conn.execute(query, params).fetchall()
        all_month_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE expense_date >= ? AND expense_date <= ?",
            (month_start, month_end)
        ).fetchone()["total"]
        all_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses"
        ).fetchone()["total"]
        count = conn.execute("SELECT COUNT(*) AS count FROM expenses").fetchone()["count"]
        budget = get_budget(conn)
        category_rows = conn.execute(
            "SELECT category, SUM(amount) AS total FROM expenses WHERE expense_date >= ? AND expense_date <= ? GROUP BY category ORDER BY total DESC",
            (month_start, month_end)
        ).fetchall()
        monthly_rows = conn.execute("""
            SELECT substr(expense_date, 1, 7) AS month, SUM(amount) AS total
            FROM expenses
            WHERE expense_date >= date('now', '-5 months', 'start of month')
            GROUP BY substr(expense_date, 1, 7)
            ORDER BY month
        """).fetchall()

    remaining = budget - all_month_total
    budget_percent = min((all_month_total / budget * 100) if budget > 0 else 0, 100)
    return render_template(
        "index.html",
        expenses=expenses,
        categories=CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        today=today.isoformat(),
        search=search,
        category_filter=category_filter,
        start_date=start_date,
        end_date=end_date,
        month_total=all_month_total,
        all_total=all_total,
        count=count,
        budget=budget,
        remaining=remaining,
        budget_percent=budget_percent,
        category_labels=[r["category"] for r in category_rows],
        category_values=[round(r["total"], 2) for r in category_rows],
        monthly_labels=[r["month"] for r in monthly_rows],
        monthly_values=[round(r["total"], 2) for r in monthly_rows],
    )

@app.route("/add", methods=["POST"])
def add_expense():
    title = request.form.get("title", "").strip()
    amount_text = request.form.get("amount", "").strip()
    category = request.form.get("category", "")
    expense_date = request.form.get("expense_date", "")
    payment = request.form.get("payment", "")
    notes = request.form.get("notes", "").strip()

    try:
        amount = float(amount_text)
        if amount <= 0 or amount != amount or amount == float("inf"):
            raise ValueError
        datetime.strptime(expense_date, "%Y-%m-%d")
        if not title or category not in CATEGORIES or payment not in PAYMENT_METHODS:
            raise ValueError
    except (ValueError, TypeError):
        flash("Please enter valid expense details. Amount must be greater than zero.", "error")
        return redirect(url_for("index"))

    with get_db() as conn:
        conn.execute(
            "INSERT INTO expenses (title, amount, category, expense_date, payment, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (title, amount, category, expense_date, payment, notes)
        )
    flash("Expense added successfully!", "success")
    return redirect(url_for("index"))

@app.route("/edit/<int:expense_id>", methods=["POST"])
def edit_expense(expense_id):
    title = request.form.get("title", "").strip()
    amount_text = request.form.get("amount", "").strip()
    category = request.form.get("category", "")
    expense_date = request.form.get("expense_date", "")
    payment = request.form.get("payment", "")
    notes = request.form.get("notes", "").strip()
    try:
        amount = float(amount_text)
        if amount <= 0 or amount != amount or amount == float("inf"):
            raise ValueError
        datetime.strptime(expense_date, "%Y-%m-%d")
        if not title or category not in CATEGORIES or payment not in PAYMENT_METHODS:
            raise ValueError
    except (ValueError, TypeError):
        flash("Please enter valid details before updating.", "error")
        return redirect(url_for("index"))

    with get_db() as conn:
        conn.execute(
            """UPDATE expenses SET title=?, amount=?, category=?, expense_date=?, payment=?, notes=?
               WHERE id=?""",
            (title, amount, category, expense_date, payment, notes, expense_id)
        )
    flash("Expense updated successfully!", "success")
    return redirect(url_for("index"))

@app.route("/delete/<int:expense_id>", methods=["POST"])
def delete_expense(expense_id):
    with get_db() as conn:
        conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    flash("Expense deleted.", "success")
    return redirect(url_for("index"))

@app.route("/budget", methods=["POST"])
def update_budget():
    try:
        budget = float(request.form.get("monthly_budget", ""))
        if budget <= 0 or budget != budget or budget == float("inf"):
            raise ValueError
    except ValueError:
        flash("Please enter a valid budget greater than zero.", "error")
        return redirect(url_for("index"))
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('monthly_budget', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(budget),)
        )
    flash("Monthly budget updated.", "success")
    return redirect(url_for("index"))

@app.route("/export")
def export_csv():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, amount, category, expense_date, payment, notes FROM expenses ORDER BY expense_date DESC"
        ).fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Expense", "Amount (INR)", "Category", "Date", "Payment Method", "Notes"])
    for row in rows:
        writer.writerow([row["id"], row["title"], row["amount"], row["category"],
                         row["expense_date"], row["payment"], row["notes"]])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"}
    )

init_db()

if __name__ == "__main__":
    app.run(debug=True)
