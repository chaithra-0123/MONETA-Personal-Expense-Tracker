
from flask import Flask, flash, redirect, render_template, request, session, url_for
from models import db, Expense, MonthlyBudget, CategoryBudget, User
from werkzeug.security import generate_password_hash, check_password_hash

from collections import defaultdict
from datetime import date, datetime
import calendar
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import re
import secrets


app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///expenses.db"
app.config["SECRET_KEY"] = "moneta-development-secret-change-before-deployment"

db.init_app(app)

serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])


# ---------------- PASSWORD RESET TOKEN HELPERS ----------------

def generate_reset_token(email):
    return serializer.dumps(email, salt="password-reset")


def verify_reset_token(token):
    try:
        email = serializer.loads(
            token,
            salt="password-reset",
            max_age=600
        )
        return email

    except (SignatureExpired, BadSignature):
        return None


# ---------------- HOME / DASHBOARD ----------------

@app.route("/")
def home():

    if "user_id" not in session:
        return redirect(url_for("login"))

    expenses = Expense.query.all()

    total_expenses = sum(
        float(expense.amount) for expense in expenses
    )

    recent_expenses = Expense.query.order_by(
        Expense.id.desc()
    ).limit(5).all()

    today = date.today()

    monthly_totals = defaultdict(float)
    category_totals = defaultdict(float)

    for expense in expenses:
        month_key = expense.date.strftime("%Y-%m")

        monthly_totals[month_key] += float(expense.amount)
        category_totals[expense.category] += float(expense.amount)

    # Prepare the last six months for the trend chart
    month_labels = []
    month_amounts = []

    for offset in range(5, -1, -1):
        month_number = today.month - offset
        year = today.year

        while month_number <= 0:
            month_number += 12
            year -= 1

        month_key = f"{year}-{month_number:02d}"

        month_labels.append(
            calendar.month_abbr[month_number]
        )

        month_amounts.append(
            round(monthly_totals[month_key], 2)
        )

    # Prepare category data for the doughnut chart
    category_labels = list(category_totals.keys())

    category_amounts = [
        round(amount, 2)
        for amount in category_totals.values()
    ]

    return render_template(
        "home.html",
        total_expenses=total_expenses,
        expense_count=len(expenses),
        recent_expenses=recent_expenses,
        month_labels=month_labels,
        month_amounts=month_amounts,
        category_labels=category_labels,
        category_amounts=category_amounts
    )


# ---------------- REGISTRATION ----------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.", "danger")
            return redirect(url_for("register"))

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            flash("This email is already registered.", "danger")
            return redirect(url_for("register"))

        password_pattern = (
            r"^(?=.*[A-Z])"
            r"(?=.*[a-z])"
            r"(?=.*[0-9])"
            r"(?=.*[^A-Za-z0-9\s])"
            r".{8,}$"
        )

        if not re.match(password_pattern, password):
            flash(
                "Password must contain at least 8 characters, "
                "one uppercase letter, one lowercase letter, "
                "one number, and one special character.",
                "danger"
            )
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        new_user = User(
            name=name,
            email=email,
            password=hashed_password
        )

        db.session.add(new_user)
        db.session.commit()

        flash(
            "Registration successful! Please log in.",
            "success"
        )

        return redirect(url_for("login"))

    return render_template("registration.html")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):

            session.clear()
            session["user_id"] = user.id
            session["user_name"] = user.name

            return redirect(url_for("home"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():

    session.clear()

    flash("You have been logged out successfully.", "success")

    return redirect(url_for("login"))

# ---------------- TEST EXPENSE (DISABLED) ----------------

# @app.route("/test-expense")
# def test_expense():
#     expense = Expense(
#         title="Lunch",
#         amount=150.00,
#         category="Food",
#         date=date.today()
#     )
#
#     db.session.add(expense)
#     db.session.commit()
#
#     return "Expense saved successfully!"


# ---------------- MONTHLY BUDGET ----------------

@app.route("/monthly-budget", methods=["GET", "POST"])
def monthly_budget():

    categories = ["Food", "Travel", "Shopping", "Bills"]

    if request.method == "POST":

        form_type = request.form.get("form_type")

        if form_type == "monthly":

            budget_date = date.fromisoformat(
                request.form.get("budget_date")
            )

            entered_amount = float(
                request.form.get("budget_amount")
            )

            budget = MonthlyBudget.query.filter(
                db.extract("month", MonthlyBudget.budget_date) == budget_date.month,
                db.extract("year", MonthlyBudget.budget_date) == budget_date.year
            ).first()

            if budget:
                budget.amount = entered_amount
            else:
                db.session.add(MonthlyBudget(
                    budget_date=budget_date,
                    amount=entered_amount
                ))

            db.session.commit()

            return redirect(url_for(
                "monthly_budget",
                saved="1",
                budget_date=budget_date.isoformat()
            ))

        elif form_type == "category":

            budget_date = date.fromisoformat(
                request.form.get("category_budget_date")
            )

            category = request.form.get("category")

            entered_amount = float(
                request.form.get("category_budget_amount")
            )

            all_budgets = CategoryBudget.query.filter_by(
                category=category
            ).all()

            category_budget = next(
                (
                    item for item in all_budgets
                    if item.budget_month.year == budget_date.year
                    and item.budget_month.month == budget_date.month
                ),
                None
            )

            if category_budget:
                category_budget.amount = entered_amount
            else:
                db.session.add(CategoryBudget(
                    budget_month=budget_date.replace(day=1),
                    category=category,
                    amount=entered_amount
                ))

            db.session.commit()

            return redirect(url_for(
                "monthly_budget",
                saved_category="1",
                budget_date=budget_date.isoformat()
            ))

    # Success messages
    success_message = None

    if request.args.get("saved") == "1":
        success_message = "Monthly budget saved successfully!"

    elif request.args.get("saved_category") == "1":
        success_message = "Category budget saved successfully!"

    # Selected month
    date_text = (
        request.args.get("budget_date")
        or date.today().isoformat()
    )

    selected_date = date.fromisoformat(date_text)

    selected_month = selected_date.month
    selected_year = selected_date.year
    month_start = selected_date.replace(day=1)

    # Load selected category budget for editing
    edit_category = request.args.get("edit_category", "")

    all_category_budgets = CategoryBudget.query.all()

    edit_budget = next(
        (
            item for item in all_category_budgets
            if item.category == edit_category
            and item.budget_month.year == selected_year
            and item.budget_month.month == selected_month
        ),
        None
    )

    edit_amount = (
        float(edit_budget.amount) if edit_budget else ""
    )

    # Get expenses for selected month
    month_expenses = Expense.query.filter(
        db.extract("month", Expense.date) == selected_month,
        db.extract("year", Expense.date) == selected_year
    ).all()

    total_spent = sum(
        float(expense.amount) for expense in month_expenses
    )

    # Get overall monthly budget
    budget = MonthlyBudget.query.filter(
        db.extract("month", MonthlyBudget.budget_date) == selected_month,
        db.extract("year", MonthlyBudget.budget_date) == selected_year
    ).first()

    budget_amount = float(budget.amount) if budget else 0
    remaining_budget = budget_amount - total_spent

    # Category-wise summary
    category_data = []

    for category in categories:

        category_spent = sum(
            float(expense.amount)
            for expense in month_expenses
            if expense.category == category
        )

        category_budget = next(
            (
                item for item in all_category_budgets
                if item.category == category
                and item.budget_month.year == selected_year
                and item.budget_month.month == selected_month
            ),
            None
        )

        category_limit = (
            float(category_budget.amount)
            if category_budget else 0
        )

        category_data.append({
            "name": category,
            "budget": category_limit,
            "spent": category_spent,
            "remaining": category_limit - category_spent
        })

    return render_template(
        "monthly_budget.html",
        success_message=success_message,
        budget_amount=budget_amount,
        total_spent=total_spent,
        remaining_budget=remaining_budget,
        categories=categories,
        category_data=category_data,
        selected_date=date_text,
        edit_category=edit_category,
        edit_amount=edit_amount
    )


# ---------------- EXPENSES ----------------

@app.route("/expenses")
def show_expenses():

    category = request.args.get("category", "").strip()
    selected_month = request.args.get("month", "").strip()

    categories = ["Food", "Travel", "Shopping", "Bills"]

    query = Expense.query

    # Filter by category
    if category:
        query = query.filter_by(category=category)

    # Filter by selected month
    if selected_month:
        year, month = map(int, selected_month.split("-"))

        query = query.filter(
            db.extract("year", Expense.date) == year,
            db.extract("month", Expense.date) == month
        )

    expenses = query.order_by(Expense.date.desc()).all()

    total_spent = sum(
        float(expense.amount) for expense in expenses
    )

    return render_template(
        "expenses.html",
        expenses=expenses,
        categories=categories,
        category=category,
        selected_month=selected_month,
        total_spent=total_spent
    )


# ---------------- EDIT EXPENSE ----------------

@app.route("/edit-expense/<int:expense_id>", methods=["GET", "POST"])
def edit_expense(expense_id):

    expense = db.session.get(Expense, expense_id)

    if expense is None:
        return "Expense not found", 404

    if request.method == "POST":

        expense.title = request.form["title"]
        expense.amount = request.form["amount"]
        expense.category = request.form["category"]
        expense.date = date.fromisoformat(request.form["date"])

        db.session.commit()

        return redirect(url_for("show_expenses"))

    return render_template(
        "edit_expense.html",
        expense=expense
    )


# ---------------- ADD EXPENSE ----------------

@app.route("/add-expense", methods=["POST"])
def add_expense():

    title = request.form["title"]
    amount = request.form["amount"]
    category = request.form["category"]
    expense_date = date.fromisoformat(request.form["date"])

    expense = Expense(
        title=title,
        amount=amount,
        category=category,
        date=expense_date
    )

    db.session.add(expense)
    db.session.commit()

    return redirect(url_for("show_expenses"))


# ---------------- DELETE EXPENSE ----------------

@app.route("/delete-expense/<int:expense_id>", methods=["POST"])
def delete_expense(expense_id):

    expense = db.session.get(Expense, expense_id)

    if expense is None:
        return "Expense not found", 404

    db.session.delete(expense)
    db.session.commit()

    return redirect(url_for("show_expenses"))


# ---------------- FORGOT PASSWORD ----------------

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form.get("email", "").strip()

        user = User.query.filter_by(email=email).first()

        if not user:
            flash("No account found with this email.", "danger")
            return redirect(url_for("forgot_password"))

        # Generate a six-digit OTP
        otp = str(secrets.randbelow(900000) + 100000)

        # Store OTP information in the session
        session["reset_otp"] = otp
        session["reset_email"] = email
        session["reset_otp_created"] = datetime.now().timestamp()
        session["reset_otp_attempts"] = 0
        session.pop("otp_verified", None)

        return render_template(
            "verify_otp.html",
            otp=otp
        )

    return render_template("forgot_password.html")


# ---------------- VERIFY OTP ----------------

@app.route("/verify-otp", methods=["POST"])
def verify_otp():

    entered_otp = request.form.get("otp", "").strip()

    saved_otp = session.get("reset_otp")
    created_time = session.get("reset_otp_created")

    if not saved_otp or not created_time:
        flash("Please request a new OTP.", "danger")
        return redirect(url_for("forgot_password"))

    # OTP expires after 10 minutes
    current_time = datetime.now().timestamp()

    if current_time - created_time > 600:
        session.pop("reset_otp", None)
        session.pop("reset_email", None)
        session.pop("reset_otp_created", None)
        session.pop("reset_otp_attempts", None)

        flash("OTP expired. Please request a new one.", "danger")
        return redirect(url_for("forgot_password"))

    # Limit incorrect OTP attempts
    attempts = session.get("reset_otp_attempts", 0)

    if attempts >= 5:
        session.pop("reset_otp", None)
        session.pop("reset_email", None)
        session.pop("reset_otp_created", None)
        session.pop("reset_otp_attempts", None)

        flash("Too many incorrect attempts. Request a new OTP.", "danger")
        return redirect(url_for("forgot_password"))

    if entered_otp == saved_otp:

        session["otp_verified"] = True

        return redirect(url_for("reset_password"))

    session["reset_otp_attempts"] = attempts + 1

    flash("Invalid OTP. Please try again.", "danger")
    return redirect(url_for("forgot_password"))


# ---------------- RESET PASSWORD ----------------

# ---------------- RESET PASSWORD ----------------

@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():

    if not session.get("otp_verified"):
        flash("Please verify your OTP first.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":

        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # 1. Check empty fields
        if not password or not confirm_password:
            flash("Please fill in both password fields.", "danger")
            return redirect(url_for("reset_password"))

        # 2. Compare both passwords FIRST
        if password != confirm_password:
            flash("Passwords do not match. Please try again.", "danger")
            return redirect(url_for("reset_password"))

        # 3. Validate password strength
        password_pattern = (
            r"^(?=.*[A-Z])"
            r"(?=.*[a-z])"
            r"(?=.*[0-9])"
            r"(?=.*[^A-Za-z0-9\s])"
            r".{8,}$"
        )

        if not re.match(password_pattern, password):
            flash(
                "Password must contain at least 8 characters, "
                "one uppercase letter, one lowercase letter, "
                "one number, and one special character.",
                "danger"
            )
            return redirect(url_for("reset_password"))

        # 4. Find the user
        email = session.get("reset_email")
        user = User.query.filter_by(email=email).first()

        if not user:
            flash("User not found. Please try again.", "danger")
            return redirect(url_for("forgot_password"))

        # 5. Save the new password
        user.password = generate_password_hash(password)
        db.session.commit()

        # 6. Clear OTP session
        session.pop("reset_otp", None)
        session.pop("reset_email", None)
        session.pop("reset_otp_created", None)
        session.pop("reset_otp_attempts", None)
        session.pop("otp_verified", None)

        flash("Password reset successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html")


# ---------------- CREATE DATABASE TABLES ----------------

with app.app_context():
    db.create_all()


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    app.run(debug=True)
