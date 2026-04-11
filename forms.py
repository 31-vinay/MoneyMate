from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    FloatField,
    SelectField,
    BooleanField,
    SubmitField,
    DateField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    NumberRange,
)


class RegistrationForm(FlaskForm):
    username = StringField(
        "Username", validators=[DataRequired(), Length(min=4, max=80)]
    )
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        "Confirm Password", validators=[DataRequired(), EqualTo("password")]
    )
    submit = SubmitField("Sign Up")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


class IncomeForm(FlaskForm):
    source = SelectField(
        "Source",
        choices=[
            ("salary", "Salary"),
            ("business", "Business"),
            ("allowance", "Allowance"),
            ("freelance", "Freelance"),
            ("other", "Other"),
        ],
        validators=[DataRequired()],
    )
    amount = FloatField("Amount (₹)", validators=[DataRequired()])
    date_received = DateField(
        "Date Received", validators=[Optional()], format="%Y-%m-%d"
    )
    description = StringField("Description")
    is_recurring = BooleanField("Recurring / Monthly Salary?")
    submit = SubmitField("Add Income")


class ExpenseForm(FlaskForm):
    main_category = SelectField("Category", choices=[], validators=[DataRequired()])
    sub_category = SelectField("Sub Category", choices=[], validators=[DataRequired()])
    custom_category = StringField("Custom Category", validators=[Optional()])
    amount = FloatField("Amount (₹)", validators=[DataRequired()])
    date = DateField("Date", validators=[Optional()], format="%Y-%m-%d")
    description = StringField("Description", validators=[Optional()])
    is_subscription = BooleanField("Recurring Subscription?")
    sub_start_date = DateField(
        "Subscription Start Date", validators=[Optional()], format="%Y-%m-%d"
    )
    sub_end_date = DateField(
        "Subscription End Date", validators=[Optional()], format="%Y-%m-%d"
    )
    submit = SubmitField("Add Expense")


class GoalForm(FlaskForm):
    name = StringField("Goal Name", validators=[DataRequired(), Length(max=200)])
    target_amount = FloatField(
        "Target Amount (₹)", validators=[DataRequired(), NumberRange(min=1)]
    )
    monthly_savings = FloatField(
        "Monthly Savings (₹)", validators=[DataRequired(), NumberRange(min=0)]
    )
    target_date = DateField(
        "Target Date (Optional)", validators=[Optional()], format="%Y-%m-%d"
    )
    priority = SelectField(
        "Priority (1 = fund first)",
        choices=[(str(i), f"#{i}") for i in range(1, 11)],
        default="1",
    )
    submit = SubmitField("Create Goal")


class SavingsUpdateForm(FlaskForm):
    saved_amount = FloatField(
        "Amount Saved (₹)", validators=[DataRequired(), NumberRange(min=0)]
    )
    submit = SubmitField("Add to Savings")
