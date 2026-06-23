import os
import sqlite3
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import secrets
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
import base64

app = Flask(__name__)
app.secret_key = 'streamflix-admin-secret-key-2024-fixed'  # Fixed secret key for session persistence
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.permanent_session_lifetime = timedelta(days=7)

# Upload helper

def save_uploaded_file(file):
    if not file or not file.filename:
        return None
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    return filepath.replace('\\', '/')


def save_uploaded_files(files):
    saved_files = []
    for file in files:
        saved_path = save_uploaded_file(file)
        if saved_path:
            saved_files.append(saved_path)
    return saved_files

# Database connection
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# Current logged in user helper

def current_user():
    if 'user_id' not in session:
        return None
    return User.get_by_id(session['user_id'])

@app.before_request
def restore_session_role():
    if 'user_id' in session and 'role' not in session:
        user = User.get_by_id(session['user_id'])
        if user:
            session['role'] = user.role

def is_admin():
    user = current_user()
    return user is not None and user.role == 'admin'

@app.context_processor
def inject_user():
    return {
        'user': current_user(),
        'website_settings': WebsiteSettings.get(),
        'social_media': SocialMedia.get_all_active(),
        'contact_info': ContactInfo.get_all_active(),
        'payment_info': PaymentInfo.get_all_active(),
        'about_us': AboutUs.get_active()
    }

# Initialize database
def init_db():
    conn = get_db()
    with open('database.sql', 'r') as f:
        conn.executescript(f.read())
    # Create default admin user if not exists
    admin = conn.execute('SELECT * FROM users WHERE role = "admin"').fetchone()
    if not admin:
        hashed_password = generate_password_hash('admin123')
        conn.execute('INSERT INTO users (name, email, password, role, status, subscription_status) VALUES (?, ?, ?, ?, ?, ?)',
                     ('Admin', 'admin@netflix.com', hashed_password, 'admin', 'active', 'approved'))
    conn.commit()
    conn.close()

# Ensure runtime movie schema is up to date
def ensure_movie_columns():
    conn = get_db()
    columns = [col['name'] for col in conn.execute('PRAGMA table_info(movies)').fetchall()]
    if 'banner_image' not in columns:
        conn.execute('ALTER TABLE movies ADD COLUMN banner_image TEXT')
    if 'description' not in columns:
        conn.execute('ALTER TABLE movies ADD COLUMN description TEXT')
    if 'show_in_banner' not in columns:
        conn.execute('ALTER TABLE movies ADD COLUMN show_in_banner INTEGER DEFAULT 0')

    # Ensure subscription_plans table exists
    tables = [table['name'] for table in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if 'subscription_plans' not in tables:
        conn.execute('''
            CREATE TABLE subscription_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                duration_months INTEGER NOT NULL,
                duration_unit TEXT DEFAULT 'month',
                duration_value INTEGER DEFAULT 1,
                price_pkr REAL NOT NULL,
                discount_percentage REAL DEFAULT 0,
                max_users INTEGER DEFAULT 1,
                features TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Insert default plans
        conn.execute('''
            INSERT INTO subscription_plans (name, duration_months, duration_unit, duration_value, price_pkr, discount_percentage, max_users, features, is_active) VALUES
            ('Basic Monthly', 1, 'month', 1, 500, 0, 1, 'HD Streaming, 1 Device, Ad-free', 1),
            ('Standard Monthly', 1, 'month', 1, 800, 0, 2, 'Full HD Streaming, 2 Devices, Ad-free, Download Content', 1),
            ('Premium Monthly', 1, 'month', 1, 1200, 0, 4, '4K Ultra HD, 4 Devices, Ad-free, Download Content, Offline Viewing', 1),
            ('Basic Yearly', 12, 'year', 1, 4500, 25, 1, 'HD Streaming, 1 Device, Ad-free, 3 Months Free', 1),
            ('Standard Yearly', 12, 'year', 1, 7200, 25, 2, 'Full HD Streaming, 2 Devices, Ad-free, Download Content, 3 Months Free', 1),
            ('Premium Yearly', 12, 'year', 1, 10800, 25, 4, '4K Ultra HD, 4 Devices, Ad-free, Download Content, Offline Viewing, 3 Months Free', 1)
        ''')

    if 'subscription_plans' in tables:
        plan_columns = [col['name'] for col in conn.execute('PRAGMA table_info(subscription_plans)').fetchall()]
        if 'max_users' not in plan_columns:
            conn.execute('ALTER TABLE subscription_plans ADD COLUMN max_users INTEGER DEFAULT 1')
        if 'duration_unit' not in plan_columns:
            conn.execute("ALTER TABLE subscription_plans ADD COLUMN duration_unit TEXT DEFAULT 'month'")
        if 'duration_value' not in plan_columns:
            conn.execute('ALTER TABLE subscription_plans ADD COLUMN duration_value INTEGER DEFAULT 1')

    if 'family_groups' not in tables:
        conn.execute('''
            CREATE TABLE family_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                plan_id INTEGER NOT NULL,
                code TEXT UNIQUE NOT NULL,
                max_members INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                FOREIGN KEY (owner_user_id) REFERENCES users(id),
                FOREIGN KEY (plan_id) REFERENCES subscription_plans(id)
            )
        ''')

    if 'family_members' not in tables:
        conn.execute('''
            CREATE TABLE family_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES family_groups(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')

    conn.commit()
    conn.close()

# Classes
class User:
    def __init__(self, id=None, name=None, email=None, password=None, role='user', status='active', subscription_status='inactive'):
        self.id = id
        self.name = name
        self.email = email
        self.password = password
        self.role = role
        self.status = status
        self.subscription_status = subscription_status

    @staticmethod
    def get_by_email(email):
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
        conn.close()
        if user:
            return User(id=user['id'], name=user['name'], email=user['email'], password=user['password'], role=user['role'], status=user['status'], subscription_status=user['subscription_status'])
        return None

    @staticmethod
    def get_by_id(id):
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE id = ?', (id,)).fetchone()
        conn.close()
        if user:
            return User(id=user['id'], name=user['name'], email=user['email'], password=user['password'], role=user['role'], status=user['status'], subscription_status=user['subscription_status'])
        return None

    def save(self):
        conn = get_db()
        if self.id:
            conn.execute('UPDATE users SET name = ?, email = ?, password = ?, role = ?, status = ?, subscription_status = ? WHERE id = ?',
                         (self.name, self.email, self.password, self.role, self.status, self.subscription_status, self.id))
        else:
            conn.execute('INSERT INTO users (name, email, password, role, status, subscription_status) VALUES (?, ?, ?, ?, ?, ?)',
                         (self.name, self.email, self.password, self.role, self.status, self.subscription_status))
        conn.commit()
        conn.close()

class Admin(User):
    def __init__(self, id=None, name=None, email=None, password=None, role='admin', status='active', subscription_status='approved'):
        super().__init__(id, name, email, password, role, status, subscription_status)

    @staticmethod
    def get_all_users():
        conn = get_db()
        users = conn.execute('SELECT * FROM users').fetchall()
        conn.close()
        return [User(id=u['id'], name=u['name'], email=u['email'], password=u['password'], role=u['role'], status=u['status'], subscription_status=u['subscription_status']) for u in users]

    @staticmethod
    def update_user_status(user_id, status):
        conn = get_db()
        conn.execute('UPDATE users SET status = ? WHERE id = ?', (status, user_id))
        conn.commit()
        conn.close()

    @staticmethod
    def get_pending_payments():
        return Payment.get_pending()

    @staticmethod
    def approve_payment(payment_id):
        conn = get_db()
        payment = conn.execute('SELECT * FROM payments WHERE id = ?', (payment_id,)).fetchone()
        if payment:
            conn.execute('UPDATE payments SET status = "approved" WHERE id = ?', (payment_id,))
            user_id = int(payment['user_id'])
            plan_id = int(payment['plan'])
            conn.execute('UPDATE users SET subscription_status = "approved" WHERE id = ?', (user_id,))
            # Create or update subscription
            plan = SubscriptionPlan.get_by_id(plan_id)
            if plan:
                start_date = datetime.now()
                end_date = plan.get_end_date(start_date)
                conn.execute('INSERT OR REPLACE INTO subscriptions (user_id, plan, status, start_date, end_date) VALUES (?, ?, "approved", ?, ?)',
                             (user_id, plan.name, start_date, end_date))
                flash(f'Payment approved successfully! User subscription activated for {plan.name}.', 'success')
            else:
                flash('Payment approved but plan details not found.', 'warning')
        else:
            flash('Payment not found.', 'error')
        conn.commit()
        conn.close()

    @staticmethod
    def reject_payment(payment_id):
        conn = get_db()
        conn.execute('UPDATE payments SET status = "rejected" WHERE id = ?', (payment_id,))
        conn.commit()
        conn.close()

class Movie:
    def __init__(self, id=None, title=None, category_id=None, thumbnail=None, banner_image=None, description=None, video_url=None, trailer_url=None, cast=None, screenshots=None, rating=0.0, featured=0, show_in_banner=0):
        self.id = id
        self.title = title
        self.category_id = category_id
        self.thumbnail = thumbnail
        self.banner_image = banner_image
        self.description = description
        self.video_url = video_url
        self.trailer_url = trailer_url
        self.cast = cast
        self.screenshots = screenshots
        self.rating = rating
        self.featured = featured
        self.show_in_banner = show_in_banner

    @staticmethod
    def get_all():
        conn = get_db()
        movies = conn.execute('SELECT * FROM movies').fetchall()
        conn.close()
        return [Movie(id=m['id'], title=m['title'], category_id=m['category_id'], thumbnail=m['thumbnail'], banner_image=m['banner_image'], description=m['description'], video_url=m['video_url'], trailer_url=m['trailer_url'], cast=m['cast'], screenshots=m['screenshots'], rating=m['rating'], featured=m['featured'], show_in_banner=m['show_in_banner'] if 'show_in_banner' in m.keys() else 0) for m in movies]

    @staticmethod
    def get_by_category(category_id):
        conn = get_db()
        movies = conn.execute('SELECT * FROM movies WHERE category_id = ?', (category_id,)).fetchall()
        conn.close()
        return [Movie(id=m['id'], title=m['title'], category_id=m['category_id'], thumbnail=m['thumbnail'], banner_image=m['banner_image'], description=m['description'], video_url=m['video_url'], trailer_url=m['trailer_url'], cast=m['cast'], screenshots=m['screenshots'], rating=m['rating'], featured=m['featured'], show_in_banner=m['show_in_banner'] if 'show_in_banner' in m.keys() else 0) for m in movies]

    @staticmethod
    def get_featured():
        conn = get_db()
        movies = conn.execute('SELECT * FROM movies WHERE show_in_banner = 1 OR featured = 1 ORDER BY id DESC LIMIT 5').fetchall()
        if not movies:
            movies = conn.execute('SELECT * FROM movies ORDER BY id DESC LIMIT 5').fetchall()
        conn.close()
        return [Movie(id=m['id'], title=m['title'], category_id=m['category_id'], thumbnail=m['thumbnail'], banner_image=m['banner_image'], description=m['description'], video_url=m['video_url'], trailer_url=m['trailer_url'], cast=m['cast'], screenshots=m['screenshots'], rating=m['rating'], featured=m['featured'], show_in_banner=m['show_in_banner'] if 'show_in_banner' in m.keys() else 0) for m in movies]

    @staticmethod
    def get_by_id(id):
        conn = get_db()
        movie = conn.execute('SELECT * FROM movies WHERE id = ?', (id,)).fetchone()
        conn.close()
        if movie:
            return Movie(id=movie['id'], title=movie['title'], category_id=movie['category_id'], thumbnail=movie['thumbnail'], banner_image=movie['banner_image'], description=movie['description'], video_url=movie['video_url'], trailer_url=movie['trailer_url'], cast=movie['cast'], screenshots=movie['screenshots'], rating=movie['rating'], featured=movie['featured'], show_in_banner=movie['show_in_banner'] if 'show_in_banner' in movie.keys() else 0)
        return None

    def save(self):
        conn = get_db()
        if self.id:
            conn.execute('UPDATE movies SET title = ?, category_id = ?, thumbnail = ?, banner_image = ?, description = ?, video_url = ?, trailer_url = ?, cast = ?, screenshots = ?, rating = ?, featured = ?, show_in_banner = ? WHERE id = ?',
                         (self.title, self.category_id, self.thumbnail, self.banner_image, self.description, self.video_url, self.trailer_url, self.cast, self.screenshots, self.rating, self.featured, self.show_in_banner, self.id))
        else:
            cursor = conn.execute('INSERT INTO movies (title, category_id, thumbnail, banner_image, description, video_url, trailer_url, cast, screenshots, rating, featured, show_in_banner) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (self.title, self.category_id, self.thumbnail, self.banner_image, self.description, self.video_url, self.trailer_url, self.cast, self.screenshots, self.rating, self.featured, self.show_in_banner))
            self.id = cursor.lastrowid

        conn.commit()

        if self.show_in_banner:
            extra_rows = conn.execute('SELECT id FROM movies WHERE show_in_banner = 1 ORDER BY id DESC LIMIT -1 OFFSET 5').fetchall()
            if extra_rows:
                conn.executemany('UPDATE movies SET show_in_banner = 0 WHERE id = ?', [(row['id'],) for row in extra_rows])
                conn.commit()

        conn.close()

    def delete(self):
        conn = get_db()
        conn.execute('DELETE FROM movies WHERE id = ?', (self.id,))
        conn.commit()
        conn.close()

class Category:
    def __init__(self, id=None, name=None):
        self.id = id
        self.name = name

    @staticmethod
    def get_all():
        conn = get_db()
        categories = conn.execute('SELECT * FROM categories').fetchall()
        conn.close()
        return [Category(id=c['id'], name=c['name']) for c in categories]

    @staticmethod
    def get_by_id(id):
        conn = get_db()
        category = conn.execute('SELECT * FROM categories WHERE id = ?', (id,)).fetchone()
        conn.close()
        if category:
            return Category(id=category['id'], name=category['name'])
        return None

    def save(self):
        conn = get_db()
        if self.id:
            conn.execute('UPDATE categories SET name = ? WHERE id = ?', (self.name, self.id))
        else:
            conn.execute('INSERT INTO categories (name) VALUES (?)', (self.name,))
        conn.commit()
        conn.close()

    def delete(self):
        conn = get_db()
        conn.execute('DELETE FROM categories WHERE id = ?', (self.id,))
        conn.commit()
        conn.close()

class Subscription:
    def __init__(self, id=None, user_id=None, plan=None, status='pending'):
        self.id = id
        self.user_id = user_id
        self.plan = plan
        self.status = status

    @staticmethod
    def get_by_user_id(user_id):
        conn = get_db()
        sub = conn.execute('SELECT * FROM subscriptions WHERE user_id = ? ORDER BY id DESC LIMIT 1', (user_id,)).fetchone()
        conn.close()
        if sub:
            return Subscription(id=sub['id'], user_id=sub['user_id'], plan=sub['plan'], status=sub['status'])
        return None

class Payment:
    def __init__(self, id=None, user_id=None, plan=None, screenshot=None, status='pending', payment_method=None, bank_name=None, account_number=None, account_holder=None, amount=None, created_at=None):
        self.id = id
        self.user_id = user_id
        self.plan = plan
        self.screenshot = screenshot
        self.status = status
        self.payment_method = payment_method
        self.bank_name = bank_name
        self.account_number = account_number
        self.account_holder = account_holder
        self.amount = amount
        self.created_at = created_at

    def save(self):
        conn = get_db()
        conn.execute('INSERT INTO payments (user_id, plan, screenshot, status, payment_method, bank_name, account_number, account_holder, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                     (self.user_id, self.plan, self.screenshot, self.status, self.payment_method, self.bank_name, self.account_number, self.account_holder, self.amount))
        conn.commit()
        conn.close()

    @staticmethod
    def get_all():
        conn = get_db()
        payments = conn.execute('SELECT * FROM payments ORDER BY created_at DESC').fetchall()
        conn.close()
        return [Payment(id=p['id'], user_id=p['user_id'], plan=p['plan'], screenshot=p['screenshot'], status=p['status'], payment_method=p['payment_method'], bank_name=p['bank_name'], account_number=p['account_number'], account_holder=p['account_holder'], amount=p['amount'], created_at=p['created_at']) for p in payments]

    @staticmethod
    def get_pending():
        conn = get_db()
        payments = conn.execute('SELECT * FROM payments WHERE status = "pending" ORDER BY created_at DESC').fetchall()
        conn.close()
        return [Payment(id=p['id'], user_id=p['user_id'], plan=p['plan'], screenshot=p['screenshot'], status=p['status'], payment_method=p['payment_method'], bank_name=p['bank_name'], account_number=p['account_number'], account_holder=p['account_holder'], amount=p['amount'], created_at=p['created_at']) for p in payments]

class SubscriptionPlan:
    def __init__(self, id=None, name=None, duration_months=None, duration_unit='month', duration_value=1, price_pkr=None, discount_percentage=0, max_users=1, features=None, is_active=1, created_at=None):
        self.id = id
        self.name = name
        self.duration_months = duration_months
        self.duration_unit = duration_unit or 'month'
        self.duration_value = duration_value if duration_value is not None else 1
        self.price_pkr = price_pkr
        self.discount_percentage = discount_percentage
        self.max_users = max_users
        self.features = features
        self.is_active = is_active
        self.created_at = created_at

    @property
    def duration_text(self):
        if self.duration_unit == 'lifetime':
            return 'Lifetime'
        unit = self.duration_unit if self.duration_value == 1 else self.duration_unit + 's'
        return f'{self.duration_value} {unit}'

    def get_end_date(self, start_date):
        if self.duration_unit == 'lifetime':
            return None
        if self.duration_unit == 'day':
            return start_date + timedelta(days=self.duration_value)
        if self.duration_unit == 'year':
            return start_date + timedelta(days=365 * self.duration_value)
        return start_date + timedelta(days=30 * self.duration_value)

    @staticmethod
    def get_all_active():
        conn = get_db()
        plans = conn.execute('SELECT * FROM subscription_plans WHERE is_active = 1 ORDER BY price_pkr ASC').fetchall()
        conn.close()
        return [SubscriptionPlan(
            id=p['id'],
            name=p['name'],
            duration_months=p['duration_months'],
            duration_unit=p['duration_unit'] if 'duration_unit' in p.keys() else 'month',
            duration_value=p['duration_value'] if 'duration_value' in p.keys() else p['duration_months'],
            price_pkr=p['price_pkr'],
            discount_percentage=p['discount_percentage'],
            max_users=p['max_users'],
            features=p['features'],
            is_active=p['is_active'],
            created_at=p['created_at']) for p in plans]

    @staticmethod
    def get_by_id(plan_id):
        conn = get_db()
        plan = conn.execute('SELECT * FROM subscription_plans WHERE id = ?', (plan_id,)).fetchone()
        conn.close()
        if plan:
            return SubscriptionPlan(
                id=plan['id'],
                name=plan['name'],
                duration_months=plan['duration_months'],
                duration_unit=plan['duration_unit'] if 'duration_unit' in plan.keys() else 'month',
                duration_value=plan['duration_value'] if 'duration_value' in plan.keys() else plan['duration_months'],
                price_pkr=plan['price_pkr'],
                discount_percentage=plan['discount_percentage'],
                max_users=plan['max_users'],
                features=plan['features'],
                is_active=plan['is_active'],
                created_at=plan['created_at'])
        return None

    @staticmethod
    def get_by_name(plan_name):
        conn = get_db()
        plan = conn.execute('SELECT * FROM subscription_plans WHERE name = ? AND is_active = 1', (plan_name,)).fetchone()
        conn.close()
        if plan:
            return SubscriptionPlan(
                id=plan['id'],
                name=plan['name'],
                duration_months=plan['duration_months'],
                duration_unit=plan['duration_unit'] if 'duration_unit' in plan.keys() else 'month',
                duration_value=plan['duration_value'] if 'duration_value' in plan.keys() else plan['duration_months'],
                price_pkr=plan['price_pkr'],
                discount_percentage=plan['discount_percentage'],
                max_users=plan['max_users'],
                features=plan['features'],
                is_active=plan['is_active'],
                created_at=plan['created_at'])
        return None

    def save(self):
        conn = get_db()
        if self.id:
            conn.execute('UPDATE subscription_plans SET name = ?, duration_months = ?, duration_unit = ?, duration_value = ?, price_pkr = ?, discount_percentage = ?, max_users = ?, features = ?, is_active = ? WHERE id = ?',
                         (self.name, self.duration_months, self.duration_unit, self.duration_value, self.price_pkr, self.discount_percentage, self.max_users, self.features, self.is_active, self.id))
        else:
            conn.execute('INSERT INTO subscription_plans (name, duration_months, duration_unit, duration_value, price_pkr, discount_percentage, max_users, features, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                         (self.name, self.duration_months, self.duration_unit, self.duration_value, self.price_pkr, self.discount_percentage, self.max_users, self.features, self.is_active))
        conn.commit()
        conn.close()

    def delete(self):
        conn = get_db()
        conn.execute('DELETE FROM subscription_plans WHERE id = ?', (self.id,))
        conn.commit()
        conn.close()

class FamilyGroup:
    def __init__(self, id=None, owner_user_id=None, plan_id=None, code=None, max_members=1, created_at=None, status='active'):
        self.id = id
        self.owner_user_id = owner_user_id
        self.plan_id = plan_id
        self.code = code
        self.max_members = max_members
        self.created_at = created_at
        self.status = status

    @staticmethod
    def generate_code():
        import secrets
        return secrets.token_hex(4).upper()

    @staticmethod
    def get_by_owner(user_id):
        conn = get_db()
        group = conn.execute('SELECT * FROM family_groups WHERE owner_user_id = ? AND status = "active"', (user_id,)).fetchone()
        conn.close()
        if group:
            return FamilyGroup(id=group['id'], owner_user_id=group['owner_user_id'], plan_id=group['plan_id'], code=group['code'], max_members=group['max_members'], created_at=group['created_at'], status=group['status'])
        return None

    @staticmethod
    def get_by_code(code):
        conn = get_db()
        group = conn.execute('SELECT * FROM family_groups WHERE code = ? AND status = "active"', (code,)).fetchone()
        conn.close()
        if group:
            return FamilyGroup(id=group['id'], owner_user_id=group['owner_user_id'], plan_id=group['plan_id'], code=group['code'], max_members=group['max_members'], created_at=group['created_at'], status=group['status'])
        return None

    @staticmethod
    def get_by_member(user_id):
        conn = get_db()
        group = conn.execute('''
            SELECT fg.*
            FROM family_groups fg
            JOIN family_members fm ON fm.group_id = fg.id
            WHERE fm.user_id = ? AND fg.status = "active"
            LIMIT 1
        ''', (user_id,)).fetchone()
        conn.close()
        if group:
            return FamilyGroup(id=group['id'], owner_user_id=group['owner_user_id'], plan_id=group['plan_id'], code=group['code'], max_members=group['max_members'], created_at=group['created_at'], status=group['status'])
        return None

    def save(self):
        conn = get_db()
        if self.id:
            conn.execute('UPDATE family_groups SET owner_user_id = ?, plan_id = ?, code = ?, max_members = ?, status = ? WHERE id = ?',
                         (self.owner_user_id, self.plan_id, self.code, self.max_members, self.status, self.id))
        else:
            conn.execute('INSERT INTO family_groups (owner_user_id, plan_id, code, max_members, status) VALUES (?, ?, ?, ?, ?)',
                         (self.owner_user_id, self.plan_id, self.code, self.max_members, self.status))
        conn.commit()
        conn.close()

    def get_members(self):
        conn = get_db()
        members = conn.execute('''
            SELECT fm.*, u.name, u.email
            FROM family_members fm
            JOIN users u ON fm.user_id = u.id
            WHERE fm.group_id = ?
        ''', (self.id,)).fetchall()
        conn.close()
        return members

class FamilyMember:
    def __init__(self, id=None, group_id=None, user_id=None, joined_at=None):
        self.id = id
        self.group_id = group_id
        self.user_id = user_id
        self.joined_at = joined_at

    def save(self):
        conn = get_db()
        conn.execute('INSERT INTO family_members (group_id, user_id) VALUES (?, ?)',
                     (self.group_id, self.user_id))
        conn.commit()
        conn.close()

class WebsiteSettings:
    def __init__(self, id=None, site_name=None, primary_color=None, secondary_color=None, logo_url=None, favicon_url=None, updated_at=None):
        self.id = id
        self.site_name = site_name or 'StreamFlix'
        self.primary_color = primary_color or '#e50914'
        self.secondary_color = secondary_color or '#ff3858'
        self.logo_url = logo_url
        self.favicon_url = favicon_url
        self.updated_at = updated_at

    @staticmethod
    def get():
        conn = get_db()
        settings = conn.execute('SELECT * FROM website_settings ORDER BY id DESC LIMIT 1').fetchone()
        conn.close()
        if settings:
            return WebsiteSettings(
                id=settings['id'],
                site_name=settings['site_name'],
                primary_color=settings['primary_color'],
                secondary_color=settings['secondary_color'],
                logo_url=settings['logo_url'],
                favicon_url=settings['favicon_url'],
                updated_at=settings['updated_at']
            )
        return WebsiteSettings()

    def save(self):
        conn = get_db()
        # First delete any existing settings
        conn.execute('DELETE FROM website_settings')
        # Then insert the new settings with id=1
        conn.execute('''INSERT INTO website_settings
                        (id, site_name, primary_color, secondary_color, logo_url, favicon_url, updated_at)
                        VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                     (self.site_name, self.primary_color, self.secondary_color, self.logo_url, self.favicon_url))
        conn.commit()
        conn.close()

class SocialMedia:
    def __init__(self, id=None, platform=None, url=None, icon_class=None, is_active=1, display_order=0, created_at=None):
        self.id = id
        self.platform = platform
        self.url = url
        self.icon_class = icon_class
        self.is_active = is_active
        self.display_order = display_order
        self.created_at = created_at

    @staticmethod
    def get_all():
        conn = get_db()
        social_media = conn.execute('SELECT * FROM social_media WHERE is_active = 1 ORDER BY display_order ASC').fetchall()
        conn.close()
        return [SocialMedia(id=s['id'], platform=s['platform'], url=s['url'], icon_class=s['icon_class'],
                           is_active=s['is_active'], display_order=s['display_order'], created_at=s['created_at'])
                for s in social_media]

    @staticmethod
    def get_all_active():
        return SocialMedia.get_all()

    @staticmethod
    def get_by_id(social_id):
        conn = get_db()
        social = conn.execute('SELECT * FROM social_media WHERE id = ?', (social_id,)).fetchone()
        conn.close()
        if social:
            return SocialMedia(id=social['id'], platform=social['platform'], url=social['url'], icon_class=social['icon_class'],
                              is_active=social['is_active'], display_order=social['display_order'], created_at=social['created_at'])
        return None

    def save(self):
        conn = get_db()
        if self.id:
            conn.execute('''UPDATE social_media SET platform=?, url=?, icon_class=?, is_active=?, display_order=? 
                            WHERE id=?''',
                         (self.platform, self.url, self.icon_class, self.is_active, self.display_order, self.id))
        else:
            conn.execute('''INSERT INTO social_media (platform, url, icon_class, is_active, display_order) 
                            VALUES (?, ?, ?, ?, ?)''',
                         (self.platform, self.url, self.icon_class, self.is_active, self.display_order))
        conn.commit()
        conn.close()

    def delete(self):
        conn = get_db()
        conn.execute('DELETE FROM social_media WHERE id = ?', (self.id,))
        conn.commit()
        conn.close()

class AboutUs:
    def __init__(self, id=None, title=None, content=None, mission=None, vision=None, image_url=None, is_active=1, updated_at=None):
        self.id = id
        self.title = title or 'About StreamFlix'
        self.content = content
        self.mission = mission
        self.vision = vision
        self.image_url = image_url
        self.is_active = is_active
        self.updated_at = updated_at

    @staticmethod
    def get():
        conn = get_db()
        about = conn.execute('SELECT * FROM about_us WHERE is_active = 1 ORDER BY id DESC LIMIT 1').fetchone()
        conn.close()
        if about:
            return AboutUs(
                id=about['id'],
                title=about['title'],
                content=about['content'],
                mission=about['mission'],
                vision=about['vision'],
                image_url=about['image_url'],
                is_active=about['is_active'],
                updated_at=about['updated_at']
            )
        return AboutUs()

    @staticmethod
    def get_active():
        return AboutUs.get()

    def save(self):
        conn = get_db()
        conn.execute('''INSERT OR REPLACE INTO about_us 
                        (id, title, content, mission, vision, image_url, is_active, updated_at) 
                        VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                     (self.title, self.content, self.mission, self.vision, self.image_url, self.is_active))
        conn.commit()
        conn.close()

class ContactInfo:
    def __init__(self, id=None, type=None, label=None, value=None, icon_class=None, is_active=1, display_order=0, created_at=None):
        self.id = id
        self.type = type
        self.label = label
        self.value = value
        self.icon_class = icon_class
        self.is_active = is_active
        self.display_order = display_order
        self.created_at = created_at

    @staticmethod
    def get_all():
        conn = get_db()
        contacts = conn.execute('SELECT * FROM contact_info WHERE is_active = 1 ORDER BY display_order ASC').fetchall()
        conn.close()
        return [ContactInfo(id=c['id'], type=c['type'], label=c['label'], value=c['value'], icon_class=c['icon_class'],
                           is_active=c['is_active'], display_order=c['display_order'], created_at=c['created_at'])
                for c in contacts]

    @staticmethod
    def get_all_active():
        return ContactInfo.get_all()

    @staticmethod
    def get_by_id(contact_id):
        conn = get_db()
        contact = conn.execute('SELECT * FROM contact_info WHERE id = ?', (contact_id,)).fetchone()
        conn.close()
        if contact:
            return ContactInfo(id=contact['id'], type=contact['type'], label=contact['label'], value=contact['value'],
                              icon_class=contact['icon_class'], is_active=contact['is_active'],
                              display_order=contact['display_order'], created_at=contact['created_at'])
        return None

    def save(self):
        conn = get_db()
        if self.id:
            conn.execute('''UPDATE contact_info SET type=?, label=?, value=?, icon_class=?, is_active=?, display_order=? 
                            WHERE id=?''',
                         (self.type, self.label, self.value, self.icon_class, self.is_active, self.display_order, self.id))
        else:
            conn.execute('''INSERT INTO contact_info (type, label, value, icon_class, is_active, display_order) 
                            VALUES (?, ?, ?, ?, ?, ?)''',
                         (self.type, self.label, self.value, self.icon_class, self.is_active, self.display_order))
        conn.commit()
        conn.close()

    def delete(self):
        conn = get_db()
        conn.execute('DELETE FROM contact_info WHERE id = ?', (self.id,))
        conn.commit()
        conn.close()

class PaymentInfo:
    def __init__(self, id=None, payment_method=None, account_title=None, account_number=None, bank_name=None,
                 branch_code=None, instructions=None, is_active=1, display_order=0, created_at=None):
        self.id = id
        self.payment_method = payment_method
        self.account_title = account_title
        self.account_number = account_number
        self.bank_name = bank_name
        self.branch_code = branch_code
        self.instructions = instructions
        self.is_active = is_active
        self.display_order = display_order
        self.created_at = created_at

    @staticmethod
    def get_all():
        conn = get_db()
        payments = conn.execute('SELECT * FROM payment_info WHERE is_active = 1 ORDER BY display_order ASC').fetchall()
        conn.close()
        return [PaymentInfo(id=p['id'], payment_method=p['payment_method'], account_title=p['account_title'],
                           account_number=p['account_number'], bank_name=p['bank_name'], branch_code=p['branch_code'],
                           instructions=p['instructions'], is_active=p['is_active'], display_order=p['display_order'],
                           created_at=p['created_at'])
                for p in payments]

    @staticmethod
    def get_all_active():
        return PaymentInfo.get_all()

    @staticmethod
    def get_by_id(payment_id):
        conn = get_db()
        payment = conn.execute('SELECT * FROM payment_info WHERE id = ?', (payment_id,)).fetchone()
        conn.close()
        if payment:
            return PaymentInfo(id=payment['id'], payment_method=payment['payment_method'], account_title=payment['account_title'],
                              account_number=payment['account_number'], bank_name=payment['bank_name'],
                              branch_code=payment['branch_code'], instructions=payment['instructions'],
                              is_active=payment['is_active'], display_order=payment['display_order'],
                              created_at=payment['created_at'])
        return None

    def save(self):
        conn = get_db()
        if self.id:
            conn.execute('''UPDATE payment_info SET payment_method=?, account_title=?, account_number=?, 
                            bank_name=?, branch_code=?, instructions=?, is_active=?, display_order=? 
                            WHERE id=?''',
                         (self.payment_method, self.account_title, self.account_number, self.bank_name,
                          self.branch_code, self.instructions, self.is_active, self.display_order, self.id))
        else:
            conn.execute('''INSERT INTO payment_info (payment_method, account_title, account_number, 
                            bank_name, branch_code, instructions, is_active, display_order) 
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                         (self.payment_method, self.account_title, self.account_number, self.bank_name,
                          self.branch_code, self.instructions, self.is_active, self.display_order))
        conn.commit()
        conn.close()

    def delete(self):
        conn = get_db()
        conn.execute('DELETE FROM payment_info WHERE id = ?', (self.id,))
        conn.commit()
        conn.close()
@app.route('/')
def index():
    user = current_user()
    movies = Movie.get_all()
    categories = Category.get_all()
    category_map = {category.id: category.name for category in categories}
    featured_movies = Movie.get_featured()
    trending = movies[:8]
    top_picks = movies[2:10] if len(movies) > 2 else movies
    new_releases = movies[-8:] if len(movies) > 8 else movies
    action_movies = [movie for movie in movies if category_map.get(movie.category_id, '').lower() == 'action']
    if not action_movies:
        action_movies = movies[:8]
    watchlist = get_watchlist(user.id) if user else []
    recommendations = get_recommendations(user.id if user else None)
    recently_watched = get_recently_watched(user.id if user else None)
    
    # Check if user has family group
    family_group = None
    if user and user.subscription_status == 'approved':
        family_group = FamilyGroup.get_by_owner(user.id)
    
    return render_template(
        'index.html',
        user=user,
        movies=movies,
        categories=categories,
        featured_movies=featured_movies,
        trending=trending,
        top_picks=top_picks,
        action_movies=action_movies,
        new_releases=new_releases,
        recommendations=recommendations,
        recently_watched=recently_watched,
        watchlist=watchlist,
        family_group=family_group,
        active_page='home'
    )

@app.route('/movies')
def movies_page():
    user = current_user()
    movies = Movie.get_all()
    categories = Category.get_all()
    category_map = {category.id: category.name for category in categories}
    return render_template('movies.html', user=user, movies=movies, categories=categories, category_map=category_map, active_page='movies')

@app.route('/tv-shows')
def tv_shows():
    user = current_user()
    movies = Movie.get_all()
    categories = Category.get_all()
    category_map = {category.id: category.name for category in categories}
    return render_template('tv_shows.html', user=user, movies=movies, categories=categories, category_map=category_map, active_page='tv_shows')

@app.route('/movie/<int:movie_id>')
def movie_detail(movie_id):
    user = current_user()
    movie = Movie.get_by_id(movie_id)
    if not movie:
        return 'Movie not found', 404
    category = Category.get_by_id(movie.category_id)
    cast = ['Ava Stone', 'Mason Lee', 'Nina Drake', 'Leo Carter']
    # Get similar movies from same category
    similar_movies = Movie.get_by_category(movie.category_id)[:6] if movie.category_id else Movie.get_all()[:6]
    similar_movies = [m for m in similar_movies if m.id != movie_id][:6]
    return render_template('movie_detail.html', user=user, movie=movie, category=category, cast=cast, similar_movies=similar_movies, active_page='movies')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    user = current_user()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        message = request.form.get('message', '').strip()
        if not name or not email or not message:
            flash('Please complete all fields before submitting.')
            return redirect(url_for('contact'))
        flash('Thanks for reaching out! Our team will get back to you soon.')
        return redirect(url_for('contact'))
    return render_template('contact.html', user=user, active_page='contact')

@app.route('/about')
def about():
    user = current_user()
    return render_template('about.html', user=user, active_page='about')

import requests

# reCAPTCHA verification
def verify_recaptcha(recaptcha_response):
    secret_key = '6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe'  # Test secret key
    payload = {
        'secret': secret_key,
        'response': recaptcha_response
    }
    response = requests.post('https://www.google.com/recaptcha/api/siteverify', data=payload)
    result = response.json()
    return result.get('success', False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        recaptcha_response = request.form.get('g-recaptcha-response')
        
        if not recaptcha_response:
            flash('Please complete the captcha.')
            return render_template('login_page.html')
        
        if not verify_recaptcha(recaptcha_response):
            flash('Captcha verification failed. Please try again.')
            return render_template('login_page.html')
        
        user = User.get_by_email(email)
        if user and check_password_hash(user.password, password):
            if user.status == 'active':
                session.permanent = True
                session['user_id'] = user.id
                session['role'] = user.role
                
                # Check if there's a pending family code to join
                if 'pending_family_code' in session:
                    code = session.pop('pending_family_code')  # Remove from session
                    # Redirect to join family page with the code pre-filled
                    return redirect(url_for('join_family') + '?code=' + code)
                
                return redirect(url_for('index'))
            else:
                flash('Account is blocked.')
        else:
            flash('Invalid credentials.')
    return render_template('login_page.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        user = User(name=name, email=email, password=password)
        user.save()
        flash('Account created successfully. Please login.')
        return redirect(url_for('login'))
    return render_template('signup.html')

# Helper function to detect and convert YouTube URLs
def get_video_info(video_url):
    """
    Detects video type and returns appropriate info for rendering
    Returns: {'type': 'youtube'|'video', 'url': processed_url, 'embed_url': embed_url_if_youtube}
    """
    if not video_url:
        return {'type': 'video', 'url': video_url, 'embed_url': None}
    
    url_lower = video_url.lower()
    
    # YouTube detection
    youtube_patterns = [
        'youtube.com/watch',
        'youtu.be/',
        'youtube.com/embed',
        'youtube.com/v/'
    ]
    
    is_youtube = any(pattern in url_lower for pattern in youtube_patterns)
    
    if is_youtube:
        # Extract video ID from various YouTube URL formats
        video_id = None
        
        if 'youtu.be/' in url_lower:
            # Short URL: https://youtu.be/dQw4w9WgXcQ
            video_id = video_url.split('youtu.be/')[-1].split('?')[0].split('&')[0]
        elif 'youtube.com/watch' in url_lower:
            # Standard URL: https://www.youtube.com/watch?v=dQw4w9WgXcQ
            if 'v=' in video_url:
                video_id = video_url.split('v=')[1].split('&')[0]
        elif 'youtube.com/embed' in url_lower:
            # Already embed format
            video_id = video_url.split('/embed/')[-1].split('?')[0]
        elif 'youtube.com/v/' in url_lower:
            # Old format: https://www.youtube.com/v/dQw4w9WgXcQ
            video_id = video_url.split('/v/')[-1].split('?')[0]
        
        if video_id:
            embed_url = f'https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1&fs=1'
            return {'type': 'youtube', 'url': video_url, 'embed_url': embed_url}
    
    # Check for other streaming formats
    if any(pattern in url_lower for pattern in ['.m3u8', 'hls', 'stream']):
        return {'type': 'hls', 'url': video_url, 'embed_url': None}
    
    # Default to regular video
    return {'type': 'video', 'url': video_url, 'embed_url': None}

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/search')
def search():
    query = request.args.get('q', '')
    if not query:
        return render_template('search.html', movies=[])
    conn = get_db()
    movies = conn.execute('SELECT * FROM movies WHERE title LIKE ?', ('%' + query + '%',)).fetchall()
    conn.close()
    movies = [Movie(id=m['id'], title=m['title'], category_id=m['category_id'], thumbnail=m['thumbnail'], video_url=m['video_url'], rating=m['rating']) for m in movies]
    return render_template('search.html', movies=movies, query=query)

@app.route('/watch/<int:movie_id>')
def watch(movie_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.get_by_id(session['user_id'])
    if user.subscription_status != 'approved':
        flash('Please subscribe to watch content.')
        return redirect(url_for('subscription'))
    movie = Movie.get_by_id(movie_id)
    if not movie:
        return 'Movie not found', 404
    # Add to watched
    conn = get_db()
    conn.execute('INSERT OR REPLACE INTO watched (user_id, movie_id) VALUES (?, ?)', (session['user_id'], movie_id))
    conn.commit()
    conn.close()
    # Get video info (detects YouTube, HLS, etc.)
    video_info = get_video_info(movie.video_url)
    return render_template('watch.html', movie=movie, video_info=video_info)

@app.route('/add_to_watchlist/<int:movie_id>')
def add_to_watchlist(movie_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    conn.execute('INSERT OR IGNORE INTO watchlist (user_id, movie_id) VALUES (?, ?)', (session['user_id'], movie_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('index'))

@app.route('/remove_from_watchlist/<int:movie_id>')
def remove_from_watchlist(movie_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    conn.execute('DELETE FROM watchlist WHERE user_id = ? AND movie_id = ?', (session['user_id'], movie_id))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('index'))

def get_watchlist(user_id):
    conn = get_db()
    watchlist = conn.execute('SELECT movie_id FROM watchlist WHERE user_id = ?', (user_id,)).fetchall()
    conn.close()
    return [row['movie_id'] for row in watchlist]

def get_recommendations(user_id):
    if not user_id:
        # For non-logged in users, return random movies
        movies = Movie.get_all()
        import random
        return random.sample(movies, min(8, len(movies)))
    
    watchlist_ids = get_watchlist(user_id)
    if not watchlist_ids:
        # If no watchlist, return high-rated movies
        conn = get_db()
        movies = conn.execute('SELECT * FROM movies ORDER BY rating DESC LIMIT 8').fetchall()
        conn.close()
        return [Movie(id=m['id'], title=m['title'], category_id=m['category_id'], thumbnail=m['thumbnail'], video_url=m['video_url'], rating=m['rating']) for m in movies]
    
    # Get categories from watchlist movies
    conn = get_db()
    categories = conn.execute('SELECT DISTINCT category_id FROM movies WHERE id IN ({})'.format(','.join('?' * len(watchlist_ids))), watchlist_ids).fetchall()
    category_ids = [c['category_id'] for c in categories]
    if category_ids:
        # Get movies from those categories, excluding watchlist
        movies = conn.execute('SELECT * FROM movies WHERE category_id IN ({}) AND id NOT IN ({}) ORDER BY rating DESC LIMIT 8'.format(','.join('?' * len(category_ids)), ','.join('?' * len(watchlist_ids))), category_ids + watchlist_ids).fetchall()
    else:
        movies = conn.execute('SELECT * FROM movies WHERE id NOT IN ({}) ORDER BY rating DESC LIMIT 8'.format(','.join('?' * len(watchlist_ids))), watchlist_ids).fetchall()
    conn.close()
    return [Movie(id=m['id'], title=m['title'], category_id=m['category_id'], thumbnail=m['thumbnail'], video_url=m['video_url'], rating=m['rating']) for m in movies]

def get_recently_watched(user_id):
    if not user_id:
        return []
    conn = get_db()
    movies = conn.execute('SELECT m.* FROM movies m JOIN watched w ON m.id = w.movie_id WHERE w.user_id = ? ORDER BY w.watched_at DESC LIMIT 8', (user_id,)).fetchall()
    conn.close()
    return [Movie(id=m['id'], title=m['title'], category_id=m['category_id'], thumbnail=m['thumbnail'], video_url=m['video_url'], rating=m['rating']) for m in movies]

@app.route('/watchlist')
def watchlist():
    user = current_user()
    if not user:
        return redirect(url_for('login'))
    conn = get_db()
    movies = conn.execute('SELECT m.* FROM movies m JOIN watchlist w ON m.id = w.movie_id WHERE w.user_id = ?', (user.id,)).fetchall()
    conn.close()
    movies = [Movie(id=m['id'], title=m['title'], category_id=m['category_id'], thumbnail=m['thumbnail'], video_url=m['video_url'], rating=m['rating']) for m in movies]
    return render_template('watchlist.html', user=user, movies=movies, active_page='watchlist')

@app.route('/subscription', methods=['GET', 'POST'])
def subscription():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.get_by_id(session['user_id'])
    plans = SubscriptionPlan.get_all_active()
    family_group_member = FamilyGroup.get_by_member(user.id)

    current_plan = None
    if family_group_member:
        family_group_owner = User.get_by_id(family_group_member.owner_user_id)
        plan = SubscriptionPlan.get_by_id(family_group_member.plan_id)
        if plan:
            current_plan = {
                'name': plan.name,
                'duration_text': plan.duration_text,
                'price_pkr': plan.price_pkr,
                'discount_percentage': plan.discount_percentage,
                'max_users': plan.max_users,
                'is_family': True,
                'owner_name': family_group_owner.name if family_group_owner else None
            }
    else:
        subscription = Subscription.get_by_user_id(user.id)
        if subscription and subscription.status == 'approved':
            plan = SubscriptionPlan.get_by_name(subscription.plan)
            if plan:
                current_plan = {
                    'name': plan.name,
                    'duration_text': plan.duration_text,
                    'price_pkr': plan.price_pkr,
                    'discount_percentage': plan.discount_percentage,
                    'max_users': plan.max_users,
                    'is_family': False
                }

    # Check if user has pending payments
    conn = get_db()
    pending_payment = conn.execute('''
        SELECT p.*, sp.name as plan_name, sp.duration_months, sp.duration_unit, sp.duration_value, sp.price_pkr, sp.discount_percentage
        FROM payments p
        JOIN subscription_plans sp ON CAST(p.plan AS INTEGER) = sp.id
        WHERE p.user_id = ? AND p.status = 'pending'
        ORDER BY p.created_at DESC LIMIT 1
    ''', (user.id,)).fetchone()
    conn.close()

    if request.method == 'POST':
        # If user is currently a family group member, leave the group before subscribing on your own
        if family_group_member:
            conn = get_db()
            conn.execute('DELETE FROM family_members WHERE group_id = ? AND user_id = ?', (family_group_member.id, user.id))
            conn.execute('UPDATE users SET subscription_status = "inactive" WHERE id = ?', (user.id,))
            conn.commit()
            conn.close()
            flash('You have left your family group and can now subscribe with your own plan.')

        # If user already has pending payment, don't allow new submission
        if pending_payment:
            flash('You already have a pending payment request. Please wait for approval or cancel your current request.')
            return redirect(url_for('subscription'))

        plan_id = request.form['plan_id']
        payment_method = request.form['payment_method']
        bank_name = request.form.get('bank_name', '')
        account_number = request.form.get('account_number', '')
        account_holder = request.form.get('account_holder', '')

        file = request.files.get('screenshot')
        if file and file.filename:
            screenshot_path = save_uploaded_file(file)
            filename = os.path.basename(screenshot_path)

            plan = SubscriptionPlan.get_by_id(int(plan_id))
            if plan:
                discount_amount = plan.price_pkr * (plan.discount_percentage / 100)
                final_amount = plan.price_pkr - discount_amount

                payment = Payment(
                    user_id=session['user_id'],
                    plan=str(plan_id),
                    screenshot=filename,  # Store only filename, not full path
                    payment_method=payment_method,
                    bank_name=bank_name,
                    account_number=account_number,
                    account_holder=account_holder,
                    amount=final_amount
                )
                payment.save()
                user.subscription_status = 'pending'
                user.save()
                flash('Payment submitted successfully! Waiting for admin approval.')
                return redirect(url_for('payment_pending'))

    return render_template('subscription.html', user=user, plans=plans, pending_payment=pending_payment, active_page='subscription', family_group_member=family_group_member, current_plan=current_plan)

@app.route('/payment-pending')
def payment_pending():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.get_by_id(session['user_id'])
    
    # Get user's pending payments
    conn = get_db()
    pending_payments = conn.execute('''
        SELECT p.*, sp.name as plan_name, sp.duration_months, sp.duration_unit, sp.duration_value, sp.price_pkr, sp.discount_percentage
        FROM payments p
        JOIN subscription_plans sp ON CAST(p.plan AS INTEGER) = sp.id
        WHERE p.user_id = ? AND p.status = 'pending'
        ORDER BY p.created_at DESC
    ''', (user.id,)).fetchall()
    conn.close()
    
    return render_template('payment_pending.html', user=user, pending_payments=pending_payments)

@app.route('/cancel-payment/<int:payment_id>', methods=['POST'])
def cancel_payment(payment_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.get_by_id(session['user_id'])
    conn = get_db()
    
    # Check if payment belongs to user and is pending
    payment = conn.execute('SELECT * FROM payments WHERE id = ? AND user_id = ? AND status = "pending"', 
                          (payment_id, user.id)).fetchone()
    
    if payment:
        conn.execute('UPDATE payments SET status = "cancelled" WHERE id = ?', (payment_id,))
        conn.execute('UPDATE users SET subscription_status = "inactive" WHERE id = ?', (user.id,))
        conn.commit()
        flash('Payment request cancelled successfully.')
    else:
        flash('Payment not found or already processed.')
    
    conn.close()
    return redirect(url_for('payment_pending'))

@app.route('/check-status')
def check_status():
    if 'user_id' not in session:
        return {'status': 'not_logged_in', 'redirect': url_for('login')}, 401
    
    user = User.get_by_id(session['user_id'])
    
    # Check if user was pending but now approved
    if user.subscription_status == 'approved':
        # Check if they have an active subscription
        conn = get_db()
        subscription = conn.execute('''
            SELECT * FROM subscriptions 
            WHERE user_id = ? AND status = 'approved' AND (end_date IS NULL OR end_date > datetime('now'))
            ORDER BY end_date DESC LIMIT 1
        ''', (user.id,)).fetchone()
        conn.close()
        
        if subscription:
            flash('Congratulations! Your payment has been approved and your subscription is now active!', 'success')
            return {'status': 'approved', 'redirect': url_for('congratulations')}, 200
    
    return {'status': 'pending'}, 200

@app.route('/congratulations')
def congratulations():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.get_by_id(session['user_id'])
    
    # Get user's active subscription
    conn = get_db()
    subscription = conn.execute('''
        SELECT s.*, sp.duration_months, sp.duration_unit, sp.duration_value, sp.price_pkr, sp.discount_percentage
        FROM subscriptions s
        LEFT JOIN subscription_plans sp ON s.plan = sp.name
        WHERE s.user_id = ? AND s.status = 'approved' AND (s.end_date IS NULL OR s.end_date > datetime('now'))
        ORDER BY s.end_date DESC LIMIT 1
    ''', (user.id,)).fetchone()

    # If the user is part of a family group, infer the plan from the group if needed
    family_group = FamilyGroup.get_by_member(user.id)
    if family_group:
        owner = User.get_by_id(family_group.owner_user_id)
        plan = SubscriptionPlan.get_by_id(family_group.plan_id)
        owner_subscription = conn.execute('''
            SELECT * FROM subscriptions 
            WHERE user_id = ? AND status = 'approved' AND (end_date IS NULL OR end_date > datetime('now'))
            ORDER BY end_date DESC LIMIT 1
        ''', (owner.id,)).fetchone() if owner else None

        if plan:
            subscription = {
                'plan': plan.name,
                'duration_text': plan.duration_text,
                'duration_unit': plan.duration_unit,
                'duration_value': plan.duration_value,
                'duration_months': plan.duration_months,
                'is_family': True,
                'owner_name': owner.name if owner else None,
                'start_date': datetime.fromisoformat(owner_subscription['start_date']) if owner_subscription and owner_subscription['start_date'] else None,
                'end_date': datetime.fromisoformat(owner_subscription['end_date']) if owner_subscription and owner_subscription['end_date'] else None
            }
    
    conn.close()
    
    # Parse dates if subscription exists
    if subscription and not isinstance(subscription, dict):
        subscription_dict = dict(subscription)
        if subscription_dict.get('start_date'):
            subscription_dict['start_date'] = datetime.fromisoformat(subscription_dict['start_date'])
        if subscription_dict.get('end_date'):
            subscription_dict['end_date'] = datetime.fromisoformat(subscription_dict['end_date'])
        
        # If duration_months is not available from join, calculate it
        if not subscription_dict.get('duration_months') and subscription_dict.get('start_date') and subscription_dict.get('end_date'):
            duration_days = (subscription_dict['end_date'] - subscription_dict['start_date']).days
            subscription_dict['duration_months'] = max(1, round(duration_days / 30))

        # Backfill units for older records
        if not subscription_dict.get('duration_unit'):
            duration_months = subscription_dict.get('duration_months') or 1
            subscription_dict['duration_unit'] = 'month'
            subscription_dict['duration_value'] = duration_months
            subscription_dict['duration_text'] = f"{duration_months} month{'s' if duration_months != 1 else ''}"
        else:
            if not subscription_dict.get('duration_value'):
                subscription_dict['duration_value'] = subscription_dict.get('duration_months') or 1
            if not subscription_dict.get('duration_text'):
                unit = subscription_dict['duration_unit']
                value = subscription_dict['duration_value']
                if unit == 'lifetime':
                    subscription_dict['duration_text'] = 'Lifetime'
                else:
                    subscription_dict['duration_text'] = f"{value} {unit}{'s' if value != 1 else ''}"
        
        subscription = subscription_dict
    elif subscription and isinstance(subscription, dict):
        if not subscription.get('duration_months') and subscription.get('start_date') and subscription.get('end_date'):
            duration_days = (subscription['end_date'] - subscription['start_date']).days
            subscription['duration_months'] = max(1, round(duration_days / 30))
        if not subscription.get('duration_unit'):
            duration_months = subscription.get('duration_months') or 1
            subscription['duration_unit'] = 'month'
            subscription['duration_value'] = duration_months
            subscription['duration_text'] = f"{duration_months} month{'s' if duration_months != 1 else ''}"
        else:
            if not subscription.get('duration_value'):
                subscription['duration_value'] = subscription.get('duration_months') or 1
            if not subscription.get('duration_text'):
                unit = subscription['duration_unit']
                value = subscription['duration_value']
                if unit == 'lifetime':
                    subscription['duration_text'] = 'Lifetime'
                else:
                    subscription['duration_text'] = f"{value} {unit}{'s' if value != 1 else ''}"
    
    return render_template('congratulations.html', user=user, subscription=subscription, now=datetime.now(), active_page='your_plan')

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user = User.get_by_id(session['user_id'])
    if request.method == 'POST':
        if 'update_profile' in request.form:
            user.name = request.form['name']
            user.email = request.form['email']
            user.save()
            flash('Profile updated.')
        elif 'change_password' in request.form:
            old_password = request.form['old_password']
            new_password = request.form['new_password']
            if check_password_hash(user.password, old_password):
                user.password = generate_password_hash(new_password)
                user.save()
                flash('Password changed.')
            else:
                flash('Old password incorrect.')
    
    # Get family group data if user has active subscription
    family_group = None
    family_members = []
    plan_name = None
    plan_max_users = 1
    
    family_group_owner = None
    is_group_owner = False

    if user.subscription_status == 'approved':
        family_group = FamilyGroup.get_by_owner(user.id)
        if family_group:
            is_group_owner = True
            family_members = family_group.get_members()
            plan = SubscriptionPlan.get_by_id(family_group.plan_id)
            if plan:
                plan_name = plan.name
                plan_max_users = plan.max_users
        else:
            family_group = FamilyGroup.get_by_member(user.id)
            if family_group:
                family_members = family_group.get_members()
                family_group_owner = User.get_by_id(family_group.owner_user_id)
                plan = SubscriptionPlan.get_by_id(family_group.plan_id)
                if plan:
                    plan_name = plan.name
                    plan_max_users = plan.max_users
            else:
                # Get user's subscription plan for max_users info
                subscription = Subscription.get_by_user_id(user.id)
                if subscription:
                    plan = SubscriptionPlan.get_by_name(subscription.plan)
                    if plan:
                        plan_max_users = plan.max_users
    
    return render_template('settings.html', user=user, family_group=family_group, family_members=family_members, plan_name=plan_name, plan_max_users=plan_max_users, family_group_owner=family_group_owner, is_group_owner=is_group_owner)

# Admin routes
@app.route('/admin')
@app.route('/admin/dashboard')
def admin_dashboard():
    if not is_admin():
        return redirect(url_for('login'))

    conn = get_db()
    
    conn = get_db()
    
    # Get statistics
    total_users = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
    total_movies = conn.execute('SELECT COUNT(*) as count FROM movies').fetchone()['count']
    total_watched = conn.execute('SELECT COUNT(*) as count FROM watched').fetchone()['count']
    active_subscriptions = conn.execute('SELECT COUNT(*) as count FROM users WHERE subscription_status = "approved"').fetchone()['count']
    
    # Get watch frequency data
    watch_data = conn.execute('''
        SELECT movie_id, COUNT(*) as views FROM watched 
        GROUP BY movie_id ORDER BY views DESC LIMIT 5
    ''').fetchall()
    
    watch_movies = []
    watch_counts = []
    for row in watch_data:
        movie = Movie.get_by_id(row['movie_id'])
        if movie:
            watch_movies.append(movie.title[:15])  # Truncate long titles
            watch_counts.append(row['views'])
    
    # Get subscription stats
    sub_stats = conn.execute('''
        SELECT subscription_status, COUNT(*) as count 
        FROM users GROUP BY subscription_status
    ''').fetchall()
    
    sub_labels = [row['subscription_status'].upper() for row in sub_stats]
    sub_counts = [row['count'] for row in sub_stats]
    
    # Get category distribution
    category_stats = conn.execute('''
        SELECT c.name, COUNT(m.id) as count 
        FROM categories c 
        LEFT JOIN movies m ON c.id = m.category_id 
        GROUP BY c.name
    ''').fetchall()
    
    cat_labels = [row['name'] for row in category_stats]
    cat_counts = [row['count'] for row in category_stats]
    
    conn.close()
    
    # Generate charts
    watch_chart = generate_chart('bar', watch_counts, watch_movies, 'Top 5 Most Watched Movies') if watch_movies else None
    sub_chart = generate_chart('pie', sub_counts, sub_labels, 'User Subscription Status')
    cat_chart = generate_chart('bar', cat_counts, cat_labels, 'Movies per Category') if cat_labels else None
    
    return render_template('admin_dashboard.html', 
        total_users=total_users,
        total_movies=total_movies,
        total_watched=total_watched,
        active_subscriptions=active_subscriptions,
        watch_chart=watch_chart,
        sub_chart=sub_chart,
        cat_chart=cat_chart
    )

@app.route('/admin/users')
def admin_users():
    if not is_admin():
        return redirect(url_for('login'))
    users = Admin.get_all_users()
    return render_template('admin_users.html', users=users)

@app.route('/admin/user/<int:user_id>/status/<status>')
def admin_update_user_status(user_id, status):
    if not is_admin():
        return redirect(url_for('login'))
    Admin.update_user_status(user_id, status)
    return redirect(url_for('admin_users'))

@app.route('/admin/payments')
def admin_payments():
    if not is_admin():
        return redirect(url_for('login'))

    conn = get_db()
    payments = conn.execute('''
        SELECT p.*, u.name as user_name, u.email as user_email,
               sp.name as plan_name, sp.price_pkr as plan_price
        FROM payments p
        LEFT JOIN users u ON p.user_id = u.id
        LEFT JOIN subscription_plans sp ON CAST(p.plan AS INTEGER) = sp.id
        ORDER BY p.created_at DESC
    ''').fetchall()
    conn.close()

    # Convert to objects with additional attributes
    payment_objects = []
    for p in payments:
        payment = Payment(
            id=p['id'], user_id=p['user_id'], plan=p['plan'], screenshot=p['screenshot'],
            status=p['status'], payment_method=p['payment_method'], bank_name=p['bank_name'],
            account_number=p['account_number'], account_holder=p['account_holder'],
            amount=p['amount'], created_at=p['created_at']
        )
        # Add additional attributes
        payment.user_name = p['user_name']
        payment.user_email = p['user_email']
        payment.plan_name = p['plan_name'] or p['plan']
        payment_objects.append(payment)

    return render_template('admin_payments.html', payments=payment_objects)

@app.route('/admin/payment/<int:payment_id>/approve')
def admin_approve_payment(payment_id):
    if not is_admin():
        return redirect(url_for('login'))
    Admin.approve_payment(payment_id)
    return redirect(url_for('admin_payments'))

@app.route('/admin/payment/<int:payment_id>/reject')
def admin_reject_payment(payment_id):
    if not is_admin():
        return redirect(url_for('login'))
    Admin.reject_payment(payment_id)
    return redirect(url_for('admin_payments'))

@app.route('/admin/subscriptions')
def admin_subscriptions():
    if not is_admin():
        return redirect(url_for('login'))
    plans = SubscriptionPlan.get_all_active()
    return render_template('admin_subscriptions.html', plans=plans)

@app.route('/admin/subscription/add', methods=['GET', 'POST'])
def admin_add_subscription():
    if not is_admin():
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        duration_unit = request.form['duration_unit']
        duration_value = int(request.form['duration_value']) if request.form.get('duration_value') else 0
        if duration_unit != 'lifetime' and duration_value < 1:
            duration_value = 1
        duration_months = 0
        if duration_unit == 'month':
            duration_months = duration_value
        elif duration_unit == 'year':
            duration_months = duration_value * 12
        elif duration_unit == 'day':
            duration_months = max(1, round(duration_value / 30))

        price_pkr = float(request.form['price_pkr'])
        discount_percentage = float(request.form.get('discount_percentage', 0))
        max_users = int(request.form['max_users'])
        features = request.form['features']
        is_active = 1 if request.form.get('is_active') else 0

        plan = SubscriptionPlan(
            name=name,
            duration_months=duration_months,
            duration_unit=duration_unit,
            duration_value=duration_value,
            price_pkr=price_pkr,
            discount_percentage=discount_percentage,
            max_users=max_users,
            features=features,
            is_active=is_active
        )
        plan.save()
        flash('Subscription plan added successfully!')
        return redirect(url_for('admin_subscriptions'))
    return render_template('admin_edit_subscription.html', plan=None)

@app.route('/admin/subscription/<int:plan_id>/edit', methods=['GET', 'POST'])
def admin_edit_subscription(plan_id):
    if not is_admin():
        return redirect(url_for('login'))
    plan = SubscriptionPlan.get_by_id(plan_id)
    if not plan:
        return redirect(url_for('admin_subscriptions'))

    if request.method == 'POST':
        plan.name = request.form['name']
        plan.duration_unit = request.form['duration_unit']
        plan.duration_value = int(request.form['duration_value']) if request.form.get('duration_value') else 0
        if plan.duration_unit != 'lifetime' and plan.duration_value < 1:
            plan.duration_value = 1
        plan.duration_months = 0
        if plan.duration_unit == 'month':
            plan.duration_months = plan.duration_value
        elif plan.duration_unit == 'year':
            plan.duration_months = plan.duration_value * 12
        elif plan.duration_unit == 'day':
            plan.duration_months = max(1, round(plan.duration_value / 30))
        plan.price_pkr = float(request.form['price_pkr'])
        plan.discount_percentage = float(request.form.get('discount_percentage', 0))
        plan.max_users = int(request.form['max_users'])
        plan.features = request.form['features']
        plan.is_active = 1 if request.form.get('is_active') else 0
        plan.save()
        flash('Subscription plan updated successfully!')
        return redirect(url_for('admin_subscriptions'))
    return render_template('admin_edit_subscription.html', plan=plan)

@app.route('/admin/subscription/<int:plan_id>/delete')
def admin_delete_subscription(plan_id):
    if not is_admin():
        return redirect(url_for('login'))
    plan = SubscriptionPlan.get_by_id(plan_id)
    if plan:
        plan.delete()
        flash('Subscription plan deleted successfully!')
    return redirect(url_for('admin_subscriptions'))

# Family Sharing Routes
@app.route('/family/generate-code', methods=['POST'])
def generate_family_code():
    user = current_user()
    if not user or user.subscription_status != 'approved':
        flash('You need an approved subscription to create a family group.')
        return redirect(url_for('subscription'))
    
    # Check if user already has a family group
    existing_group = FamilyGroup.get_by_owner(user.id)
    if existing_group:
        flash('You already have a family group. You can manage it from your settings.')
        return redirect(url_for('settings'))
    
    # Get user's subscription plan
    subscription = Subscription.get_by_user_id(user.id)
    if not subscription:
        flash('No active subscription found.')
        return redirect(url_for('subscription'))
    
    plan = SubscriptionPlan.get_by_name(subscription.plan)
    if not plan:
        flash('Subscription plan not found.')
        return redirect(url_for('subscription'))
    
    # Create family group
    group = FamilyGroup(
        owner_user_id=user.id,
        plan_id=plan.id,
        code=FamilyGroup.generate_code(),
        max_members=plan.max_users - 1  # Owner counts as 1, so allow max_users - 1 additional members
    )
    group.save()
    
    flash(f'Family group created! Share this code with family members: {group.code}')
    return redirect(url_for('settings'))

@app.route('/family/join', methods=['GET', 'POST'])
def join_family():
    code_from_url = request.args.get('code', '').strip().upper()
    
    if request.method == 'POST':
        code = request.form['code'].strip().upper()
        
        # Check if code exists and is active
        group = FamilyGroup.get_by_code(code)
        if not group:
            flash('Invalid family code. Please check and try again.')
            return render_template('join_family.html', prefilled_code=code_from_url)
        
        user = current_user()
        if not user:
            # Store code in session for after login/signup
            session['pending_family_code'] = code
            flash('Please login or create an account to join the family group.')
            return redirect(url_for('login'))
        
        # Check if user already has a subscription
        if user.subscription_status == 'approved':
            flash('You already have an active subscription. You cannot join a family group.')
            return redirect(url_for('index'))
        
        # Check if user is already in this group
        conn = get_db()
        existing_member = conn.execute('SELECT * FROM family_members WHERE group_id = ? AND user_id = ?', (group.id, user.id)).fetchone()
        conn.close()
        
        if existing_member:
            flash('You are already a member of this family group.')
            return redirect(url_for('index'))
        
        # Check if group is full
        members = group.get_members()
        if len(members) >= group.max_members:
            flash('This family group is full. Maximum members reached.')
            return render_template('join_family.html', prefilled_code=code_from_url)
        
        # Add user to family group
        member = FamilyMember(group_id=group.id, user_id=user.id)
        member.save()
        
        # Update user subscription status
        conn = get_db()
        conn.execute('UPDATE users SET subscription_status = "approved" WHERE id = ?', (user.id,))
        conn.commit()
        conn.close()
        
        flash('Successfully joined the family group! You now have access to the subscription.')
        return redirect(url_for('index'))
    
    return render_template('join_family.html', prefilled_code=code_from_url)

@app.route('/family/remove-member/<int:member_id>', methods=['POST'])
def remove_family_member(member_id):
    user = current_user()
    if not user or user.subscription_status != 'approved':
        flash('You must be logged in with an active subscription to manage family members.')
        return redirect(url_for('login'))

    group = FamilyGroup.get_by_owner(user.id)
    if not group:
        flash('Only the family group owner can remove members.')
        return redirect(url_for('settings'))

    conn = get_db()
    member = conn.execute('SELECT * FROM family_members WHERE id = ? AND group_id = ?', (member_id, group.id)).fetchone()
    if not member:
        flash('Member not found in your family group.')
        conn.close()
        return redirect(url_for('settings'))

    conn.execute('DELETE FROM family_members WHERE id = ?', (member_id,))
    conn.execute('UPDATE users SET subscription_status = "inactive" WHERE id = ?', (member['user_id'],))
    conn.commit()
    conn.close()

    flash('Family member removed successfully. Their subscription access has been revoked.')
    return redirect(url_for('settings'))

@app.route('/family/leave', methods=['POST'])
def leave_family():
    user = current_user()
    if not user:
        return redirect(url_for('login'))

    group = FamilyGroup.get_by_member(user.id)
    if not group:
        flash('You are not part of a family group.')
        return redirect(url_for('settings'))

    conn = get_db()
    conn.execute('DELETE FROM family_members WHERE group_id = ? AND user_id = ?', (group.id, user.id))
    conn.execute('UPDATE users SET subscription_status = "inactive" WHERE id = ?', (user.id,))
    conn.commit()
    conn.close()

    flash('You have left the family group and can now subscribe on your own.')
    return redirect(url_for('settings'))

@app.route('/cancel-subscription', methods=['POST'])
def cancel_subscription():
    user = current_user()
    if not user:
        return redirect(url_for('login'))

    if user.subscription_status != 'approved':
        flash('You do not have an active subscription to cancel.')
        return redirect(url_for('settings'))

    conn = get_db()
    conn.execute('UPDATE subscriptions SET status = "cancelled" WHERE user_id = ? AND status = "approved"', (user.id,))

    group = FamilyGroup.get_by_owner(user.id)
    if group:
        members = group.get_members()
        member_ids = [m['user_id'] for m in members]
        if member_ids:
            placeholders = ','.join(['?'] * len(member_ids))
            conn.execute(f'UPDATE users SET subscription_status = "inactive" WHERE id IN ({placeholders})', tuple(member_ids))
        conn.execute('DELETE FROM family_members WHERE group_id = ?', (group.id,))
        conn.execute('UPDATE family_groups SET status = "inactive" WHERE id = ?', (group.id,))
    else:
        member_group = FamilyGroup.get_by_member(user.id)
        if member_group:
            conn.execute('DELETE FROM family_members WHERE group_id = ? AND user_id = ?', (member_group.id, user.id))

    conn.execute('UPDATE users SET subscription_status = "inactive" WHERE id = ?', (user.id,))
    conn.commit()
    conn.close()

    flash('Your subscription has been cancelled successfully. You can subscribe again anytime.')
    return redirect(url_for('settings'))

@app.route('/admin/family-groups')
def admin_family_groups():
    if not is_admin():
        return redirect(url_for('login'))
    
    conn = get_db()
    groups = conn.execute('''
        SELECT fg.*, u.name as owner_name, u.email as owner_email, sp.name as plan_name, sp.max_users
        FROM family_groups fg
        JOIN users u ON fg.owner_user_id = u.id
        JOIN subscription_plans sp ON fg.plan_id = sp.id
        ORDER BY fg.created_at DESC
    ''').fetchall()
    
    # Convert to dictionaries and get members for each group
    groups_list = []
    total_members = 0
    for group in groups:
        group_dict = dict(group)
        members = FamilyGroup(id=group['id']).get_members()
        group_dict['members'] = members
        group_dict['member_count'] = len(members)
        total_members += len(members)
        groups_list.append(group_dict)
    
    conn.close()
    return render_template('admin_family_groups.html', groups=groups_list, total_members=total_members)

@app.route('/admin/movies', methods=['GET', 'POST'])
def admin_movies():
    if not is_admin():
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form['title']
        category_id = request.form['category_id']
        description = request.form.get('description', '')
        trailer_url = request.form.get('trailer_url', '')
        cast = request.form.get('cast', '')
        rating = request.form.get('rating', 0.0)
        
        # Handle video file upload
        video_file = request.files.get('video_file')
        video_url = request.form.get('video_url', '')
        if video_file and video_file.filename:
            video_url = save_uploaded_file(video_file)
        
        # Handle thumbnail
        thumbnail = None
        thumbnail_file = request.files.get('thumbnail')
        if thumbnail_file and thumbnail_file.filename:
            thumbnail = save_uploaded_file(thumbnail_file)

        # Handle banner image
        banner_image = None
        banner_file = request.files.get('banner_image')
        if banner_file and banner_file.filename:
            banner_image = save_uploaded_file(banner_file)
        
        # Handle screenshots (multiple files)
        screenshot_files = request.files.getlist('screenshots')
        screenshots = save_uploaded_files(screenshot_files)
        screenshots_str = ','.join(screenshots) if screenshots else ''
        
        show_in_banner = 1 if request.form.get('show_in_banner') else 0
        featured = 1 if request.form.get('featured') else 0
        
        movie = Movie(title=title, category_id=category_id, thumbnail=thumbnail, banner_image=banner_image, description=description, video_url=video_url, trailer_url=trailer_url, cast=cast, screenshots=screenshots_str, rating=rating, featured=featured, show_in_banner=show_in_banner)
        movie.save()
        return redirect(url_for('admin_movies'))
    movies = Movie.get_all()
    categories = Category.get_all()
    category_map = {category.id: category.name for category in categories}
    return render_template('admin_movies.html', movies=movies, categories=categories, category_map=category_map)

@app.route('/admin/movie/<int:movie_id>/edit', methods=['GET', 'POST'])
def admin_edit_movie(movie_id):
    if not is_admin():
        return redirect(url_for('login'))
    movie = Movie.get_by_id(movie_id)
    if not movie:
        return 'Movie not found', 404
    if request.method == 'POST':
        movie.title = request.form['title']
        movie.category_id = request.form['category_id']
        movie.description = request.form.get('description', '')
        movie.trailer_url = request.form.get('trailer_url', '')
        movie.cast = request.form.get('cast', '')
        movie.rating = request.form.get('rating', 0.0)
        movie.show_in_banner = 1 if request.form.get('show_in_banner') else 0
        movie.featured = 1 if request.form.get('featured') else 0
        
        # Handle video file upload
        video_file = request.files.get('video_file')
        if video_file and video_file.filename:
            movie.video_url = save_uploaded_file(video_file)
        else:
            movie.video_url = request.form.get('video_url', movie.video_url)
        
        # Handle thumbnail
        thumbnail_file = request.files.get('thumbnail')
        if thumbnail_file and thumbnail_file.filename:
            movie.thumbnail = save_uploaded_file(thumbnail_file)

        # Handle banner image
        banner_file = request.files.get('banner_image')
        if banner_file and banner_file.filename:
            movie.banner_image = save_uploaded_file(banner_file)
        
        # Handle screenshots (multiple files)
        screenshot_files = request.files.getlist('screenshots')
        screenshots = save_uploaded_files(screenshot_files)
        if screenshots:
            movie.screenshots = ','.join(screenshots)
        
        movie.save()
        return redirect(url_for('admin_movies'))
    categories = Category.get_all()
    return render_template('admin_edit_movie.html', movie=movie, categories=categories)

@app.route('/admin/movie/<int:movie_id>/delete')
def admin_delete_movie(movie_id):
    if not is_admin():
        return redirect(url_for('login'))
    movie = Movie.get_by_id(movie_id)
    if movie:
        movie.delete()
    return redirect(url_for('admin_movies'))

@app.route('/admin/categories', methods=['GET', 'POST'])
def admin_categories():
    if not is_admin():
        return redirect(url_for('login'))
    if request.method == 'POST':
        name = request.form['name']
        category = Category(name=name)
        category.save()
        return redirect(url_for('admin_categories'))
    categories = Category.get_all()
    return render_template('admin_categories.html', categories=categories)

@app.route('/admin/category/<int:category_id>/edit', methods=['GET', 'POST'])
def admin_edit_category(category_id):
    if not is_admin():
        return redirect(url_for('login'))
    category = Category.get_by_id(category_id)
    if not category:
        return 'Category not found', 404
    if request.method == 'POST':
        category.name = request.form['name']
        category.save()
        return redirect(url_for('admin_categories'))
    return render_template('admin_edit_category.html', category=category)

@app.route('/admin/category/<int:category_id>/delete')
def admin_delete_category(category_id):
    if not is_admin():
        return redirect(url_for('login'))
    category = Category.get_by_id(category_id)
    if category:
        category.delete()
    return redirect(url_for('admin_categories'))

# Website Settings Management
@app.route('/admin/website-settings', methods=['GET', 'POST'])
def admin_website_settings():
    if not is_admin():
        return redirect(url_for('login'))

    settings = WebsiteSettings.get()

    if request.method == 'POST':
        settings.site_name = request.form.get('site_name', 'StreamFlix')
        settings.primary_color = request.form.get('primary_color', '#e50914')
        settings.secondary_color = request.form.get('secondary_color', '#ff3858')
        settings.logo_url = request.form.get('logo_url')
        settings.favicon_url = request.form.get('favicon_url')
        settings.save()
        flash('Website settings updated successfully!', 'success')
        return redirect(url_for('admin_website_settings'))

    return render_template('admin_website_settings.html', settings=settings)

# Social Media Management
@app.route('/admin/social-media', methods=['GET', 'POST'])
def admin_social_media():
    if not is_admin():
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'add_social' in request.form:
            social = SocialMedia()
            social.platform = request.form.get('platform')
            social.url = request.form.get('url')
            social.icon_class = request.form.get('icon_class')
            social.display_order = int(request.form.get('display_order', 0))
            social.save()
            flash('Social media platform added successfully!', 'success')
        elif 'update_social' in request.form:
            social_id = request.form.get('social_id')
            social = SocialMedia.get_by_id(social_id)
            if social:
                social.platform = request.form.get('platform')
                social.url = request.form.get('url')
                social.icon_class = request.form.get('icon_class')
                social.display_order = int(request.form.get('display_order', 0))
                social.save()
                flash('Social media platform updated successfully!', 'success')
        return redirect(url_for('admin_social_media'))

    social_media = SocialMedia.get_all()
    return render_template('admin_social_media.html', social_media=social_media)

@app.route('/admin/social-media/<int:social_id>/delete')
def admin_delete_social_media(social_id):
    if not is_admin():
        return redirect(url_for('login'))
    social = SocialMedia.get_by_id(social_id)
    if social:
        social.delete()
        flash('Social media platform deleted successfully!', 'success')
    return redirect(url_for('admin_social_media'))

# About Us Management
@app.route('/admin/about-us', methods=['GET', 'POST'])
def admin_about_us():
    if not is_admin():
        return redirect(url_for('login'))

    about = AboutUs.get()

    if request.method == 'POST':
        about.title = request.form.get('title', 'About StreamFlix')
        about.content = request.form.get('content')
        about.mission = request.form.get('mission')
        about.vision = request.form.get('vision')
        about.image_url = request.form.get('image_url')
        about.save()
        flash('About Us content updated successfully!', 'success')
        return redirect(url_for('admin_about_us'))

    return render_template('admin_about_us.html', about=about)

# Contact Information Management
@app.route('/admin/contact-info', methods=['GET', 'POST'])
def admin_contact_info():
    if not is_admin():
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'add_contact' in request.form:
            contact = ContactInfo()
            contact.type = request.form.get('type')
            contact.label = request.form.get('label')
            contact.value = request.form.get('value')
            contact.icon_class = request.form.get('icon_class')
            contact.display_order = int(request.form.get('display_order', 0))
            contact.save()
            flash('Contact information added successfully!', 'success')
        elif 'update_contact' in request.form:
            contact_id = request.form.get('contact_id')
            contact = ContactInfo.get_by_id(contact_id)
            if contact:
                contact.type = request.form.get('type')
                contact.label = request.form.get('label')
                contact.value = request.form.get('value')
                contact.icon_class = request.form.get('icon_class')
                contact.display_order = int(request.form.get('display_order', 0))
                contact.save()
                flash('Contact information updated successfully!', 'success')
        return redirect(url_for('admin_contact_info'))

    contacts = ContactInfo.get_all()
    return render_template('admin_contact_info.html', contacts=contacts)

@app.route('/admin/contact-info/<int:contact_id>/delete')
def admin_delete_contact_info(contact_id):
    if not is_admin():
        return redirect(url_for('login'))
    contact = ContactInfo.get_by_id(contact_id)
    if contact:
        contact.delete()
        flash('Contact information deleted successfully!', 'success')
    return redirect(url_for('admin_contact_info'))

# Payment Information Management
@app.route('/admin/payment-info', methods=['GET', 'POST'])
def admin_payment_info():
    if not is_admin():
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'add_payment' in request.form:
            payment = PaymentInfo()
            payment.payment_method = request.form.get('payment_method')
            payment.account_title = request.form.get('account_title')
            payment.account_number = request.form.get('account_number')
            payment.bank_name = request.form.get('bank_name')
            payment.branch_code = request.form.get('branch_code')
            payment.instructions = request.form.get('instructions')
            payment.display_order = int(request.form.get('display_order', 0))
            payment.save()
            flash('Payment information added successfully!', 'success')
        elif 'update_payment' in request.form:
            payment_id = request.form.get('payment_id')
            payment = PaymentInfo.get_by_id(payment_id)
            if payment:
                payment.payment_method = request.form.get('payment_method')
                payment.account_title = request.form.get('account_title')
                payment.account_number = request.form.get('account_number')
                payment.bank_name = request.form.get('bank_name')
                payment.branch_code = request.form.get('branch_code')
                payment.instructions = request.form.get('instructions')
                payment.display_order = int(request.form.get('display_order', 0))
                payment.save()
                flash('Payment information updated successfully!', 'success')
        return redirect(url_for('admin_payment_info'))

    payments = PaymentInfo.get_all()
    return render_template('admin_payment_info.html', payments=payments)

@app.route('/admin/payment-info/<int:payment_id>/delete')
def admin_delete_payment_info(payment_id):
    if not is_admin():
        return redirect(url_for('login'))
    payment = PaymentInfo.get_by_id(payment_id)
    if payment:
        payment.delete()
        flash('Payment information deleted successfully!', 'success')
    return redirect(url_for('admin_payment_info'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Chart generation helper
def generate_chart(chart_type, data, labels, title):
    """Generate matplotlib chart and return as base64 image"""
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor('#050507')
    
    if chart_type == 'bar':
        bars = ax.bar(labels, data, color='#e50914', edgecolor='#ff3858', linewidth=2)
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}', ha='center', va='bottom', color='#fff')
    elif chart_type == 'pie':
        ax.pie(data, labels=labels, autopct='%1.1f%%', colors=['#e50914', '#ff3858', '#c9070d', '#ff5a7a'])
        
    ax.set_title(title, fontsize=16, fontweight='bold', color='#fff', pad=20)
    ax.set_facecolor('#040406')
    
    # Style the spines
    for spine in ax.spines.values():
        spine.set_color('#333')
        spine.set_linewidth(0.5)
    
    ax.tick_params(colors='#ccc')
    plt.tight_layout()
    
    # Convert to base64
    buffer = BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight', facecolor='#050507')
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.getvalue()).decode()
    plt.close()
    
    return image_base64



@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)



if __name__ == '__main__':
    if not os.path.exists('database.db'):
        init_db()
    else:
        ensure_movie_columns()
    app.run(debug=True)