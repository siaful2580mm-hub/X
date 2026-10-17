import os
import random
import string
import requests
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import send_from_directory
from flask import (
    Flask, render_template, request, redirect, 
    url_for, session, flash, jsonify
)
from supabase import create_client, Client
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException

# ==========================================================
# Application Initialization & Setup
# ==========================================================
app = Flask(
    __name__, 
    template_folder='../templates', 
    static_folder='../static'
)
# ==========================================================
# PERMANENT SESSION CONFIGURATION (অটো লগআউট স্থায়ী সমাধান)
# ==========================================================
# ১. ফিক্সড সিক্রেট কি (সার্ভারলেস রিস্টার্টেও সেশন নষ্ট হবে না)
app.secret_key = os.getenv("SECRET_KEY", "microearnx_permanent_super_secure_key_2026_xyz99")

# ২. সেশনের মেয়াদ ৬০ দিন স্থায়ী করা হলো
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=60)

# ৩. মোবাইল ও আধুনিক ব্রাউজার কুকি প্রোটেকশন
app.config['SESSION_COOKIE_SECURE'] = True        # HTTPS সিকিউর কুকি
app.config['SESSION_COOKIE_HTTPONLY'] = True      # জাভাস্ক্রিপ্ট কুকি হাইজ্যাক ব্লক
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'     # ব্রাউজার রিফ্রেশে সেশন থাকবে
app.config['SESSION_REFRESH_EACH_REQUEST'] = True # প্রতিবার পেজ লোড দিলে মেয়াদ ৬০ দিনের জন্য রিনিউ হবে

# ৪. গ্লোবাল ফিল্টার: প্রতি রিকোয়েস্টে সেশনকে পার্মানেন্ট রাখবে
@app.before_request
def make_session_permanent():
    session.permanent = True



# ==========================================================
# Vercel Path Fixer Middleware (404 এরর স্থায়ী সমাধান)
# ==========================================================
class VercelPathFixer:
    """
    Vercel Serverless রিকোয়েস্টে হেডার থেকে আসল URL পাথ পুনরুদ্ধার করে
    যাতে Flask-এর কোনো পেজেই 404 এরর না আসে।
    """
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        real_path = environ.get('HTTP_X_FORWARDED_URI') or environ.get('HTTP_X_MATCHED_PATH')
        if real_path:
            environ['PATH_INFO'] = real_path.split('?')[0]
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathFixer(app.wsgi_app)

# ==========================================================
# Database Connection (Supabase)
# ==========================================================
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

def get_supabase() -> Client:
    """Supabase ক্লায়েন্ট রিটার্ন করে"""
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# অ্যাডমিন সিকিউরিটি পাসওয়ার্ড
ADMIN_SECRET_PASS = os.getenv("ADMIN_KEY", "Admin@MicroEarnX_2026")

# ==========================================================
# Error Handlers (সার্ভার ক্র্যাশ রোধক)
# ==========================================================
@app.errorhandler(Exception)
def handle_global_error(e):
    # সাধারণ HTTP এরর (যেমন 404, 403, 405) স্বাভাবিকভাবে চলতে দেওয়া
    if isinstance(e, HTTPException):
        return e
    
    # ব্যাকএন্ড ক্র্যাশ হলে সেফ রিকভারি
    return render_template(
        'base.html', 
        content="সার্ভারে সাময়িক চাপ রয়েছে। অনুগ্রহ করে রিলোড দিন।"
    ), 200


# ==========================================================
# KYC REQUIRED DECORATOR (কেওয়াইসি ছাড়া কাজ বা উইথড্র ব্লক)
# ==========================================================
def kyc_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("অনুগ্রহ করে প্রথমে লগইন করুন!", "danger")
            return redirect(url_for('index'))
        
        sb = get_supabase()
        user_id = session['user_id']
        
        # অ্যাডমিন (@admin.com বা admin@gmail.com) হলে কেওয়াইসি লাগবে না
        user = sb.table('users').select('email').eq('id', user_id).single().execute().data
        if user and user.get('email') == 'admin@gmail.com':
            return f(*args, **kwargs)

        # ইউজারের কেওয়াইসি স্ট্যাটাস চেক
        kyc_res = sb.table('kyc_requests').select('status').eq('user_id', user_id).order('id', desc=True).limit(1).execute().data
        
        is_approved = False
        if kyc_res and kyc_res[0].get('status') == 'approved':
            is_approved = True

        if not is_approved:
            flash("⚠️ এই পেজে প্রবেশ করতে ও কাজ করতে হলে প্রথমে এককালীন ৫০৳ ফি দিয়ে কেওয়াইসি (KYC) ভেরিফিকেশন সম্পন্ন করতে হবে!", "warning")
            return redirect(url_for('kyc_page'))

        return f(*args, **kwargs)
    return decorated_function
    # ==========================================================
# GLOBAL REDIRECT TO x.html (যেখানেই যাক x.html দেখাবে)
# ==========================================================
@app.before_request
def redirect_to_x_page():
    # ১. স্ট্যাটিক ফাইল (CSS, JS, Images) এবং Favicon লোড হওয়া ব্লক করা যাবে না, তা না হলে ডিজাইন ভেঙে যাবে
    if request.path.startswith('/static') or request.path == '/favicon.ico':
        return None
    
    # ২. আপনি যদি চান শুধু ইউজারদের জন্য ব্লক হবে কিন্তু অ্যাডমিনরা সাইট দেখতে পারবে, তবে নিচের লাইনটি ব্যবহার করতে পারেন:
    # if request.path.startswith('/admin'):
    #     return None

    # ৩. বর্তমানে যদি ইউজার অলরেডি /x পেজেই থাকে, তবে লুপ (infinite loop) আটকাতে হবে
    if request.path == '/x':
        return None

    # ৪. বাকি সব রিকোয়েস্টকে সরাসরি x.html এ পাঠিয়ে দেওয়া
    return render_template('x.html')

@app.route('/x')
def x_page():
    return render_template('x.html')
    
# ==========================================================
# Authentication Guards (Decorators)
# ==========================================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("অনুগ্রহ করে প্রথমে লগইন করুন!", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

    
# ==========================================================
# STRICT ADMIN SECURITY (ONLY admin@gmail.com PERMITTED)
# ==========================================================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # ১. লগইন না থাকলে ব্লক
        if 'user_id' not in session:
            flash("শুধুমাত্র অনুমোদিত অ্যাডমিন এক্সেস করতে পারবে!", "danger")
            return redirect(url_for('index'))
        
        # ২. ইমেইল ভেরিফিকেশন: admin@gmail.com ছাড়া বাকি সবার জন্য চিরতরে ব্লক
        sb = get_supabase()
        user = sb.table('users').select('email').eq('id', session['user_id']).single().execute().data
        if not user or user.get('email') != 'admin@gmail.com':
            flash("অননুমোদিত প্রবেশ! আপনার এই পেজে আসার অনুমতি নেই।", "danger")
            return redirect(url_for('dashboard'))

        # ৩. অ্যাডমিন কি ভেরিফিকেশন
        if not session.get('is_admin'):
            return redirect(url_for('admin_login'))

        return f(*args, **kwargs)
    return decorated_function


    
    
# ==========================================================
# ImgBB Failover Engine (Multi-Key Support)
# ==========================================================
def upload_to_imgbb(file_bytes):
    """
    সবগুলো সক্রিয় ImgBB Key সিরিয়ালি চেষ্টা করে।
    একটি ফেইল হলে বা লিমিট শেষ হলে স্বয়ংক্রিয়ভাবে পরবর্তী কি ব্যবহার করে।
    """
    sb = get_supabase()
    keys_res = sb.table('imgbb_keys').select('*').eq('is_active', True).execute()
    keys = keys_res.data or []

    for key_row in keys:
        api_key = key_row['api_key']
        try:
            url = "https://api.imgbb.com/1/upload"
            payload = {'key': api_key}
            files = {'image': file_bytes}
            res = requests.post(url, data=payload, files=files, timeout=8)
            data = res.json()
            
            if res.status_code == 200 and data.get('success'):
                return data['data']['url']
            else:
                continue
        except Exception:
            continue
            
    return None



# ==========================================================
# TUTORIAL & GUIDELINE VIDEO CONTROLLER
# ==========================================================
@app.route('/tutorial')
def tutorial():
    # ফেসবুক রিলস ভিডিওর লিংক (প্রয়োজনে আপনি আপনার নিজস্ব রিলস লিংক দিয়ে রিপ্লেস করতে পারেন)
    fb_reel_url = "https://www.facebook.com/reel/1719120619189780/"
    return render_template('tutorial.html', fb_reel_url=fb_reel_url)
    
# ==========================================================
# AUTHENTICATION CONTROLLER (INDEX = SIGNUP, /login = LOGIN)
# ==========================================================
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    # GET রিকোয়েস্টে নতুন ফ্ল্যাট লগইন পেজ ওপেন হবে
    if request.method == 'GET':
        return render_template('login.html')

    # POST রিকোয়েস্টে লগইন প্রসেস
    sb = get_supabase()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()

    if not email or not password:
        flash("ইমেইল ও পাসওয়ার্ড প্রদান করুন!", "danger")
        return redirect(url_for('login'))

    # ডেটাবেস কোল্ড-বুট ফিক্স (অটো ৩ বার ট্রাই)
    user_res = None
    for _ in range(3):
        try:
            res = sb.table('users').select('*').eq('email', email).execute()
            if res.data:
                user_res = res.data
                break
        except Exception:
            time.sleep(0.3)

    # একাউন্ট না পাওয়া গেলে সাইনআপ পেজে (Index) রিডাইরেক্ট করে পপআপ দেখাবে
    if not user_res:
        return redirect(url_for('index', not_found_email=email))

    user = user_res[0]
    if user['is_banned']:
        flash("আপনার অ্যাকাউন্টটি স্থায়ীভাবে ব্যান করা হয়েছে!", "danger")
        return redirect(url_for('login'))

    if check_password_hash(user['password_hash'], password):
        session.permanent = True
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        return redirect(url_for('dashboard'))
    else:
        flash("ভুল পাসওয়ার্ড দিয়েছেন! দয়া করে সঠিক পাসওয়ার্ড দিন।", "danger")
        return redirect(url_for('login'))


# ==========================================================
# KYC VERIFICATION & AUTO-PAYOUT CONTROLLER (/kyc)
# ==========================================================
@app.route('/kyc', methods=['GET', 'POST'])
@login_required
def kyc_page():
    sb = get_supabase()
    user_id = session['user_id']
    user = sb.table('users').select('*').eq('id', user_id).single().execute().data

    # ইউজারের অলরেডি কোনো KYC সাবমিশন আছে কিনা চেক
    existing_kyc = sb.table('kyc_requests').select('*').eq('user_id', user_id).order('id', desc=True).execute().data
    latest_kyc = existing_kyc[0] if existing_kyc else None

    if request.method == 'POST':
        # যদি অলরেডি এপ্রুভড বা পেন্ডিং থাকে
        if latest_kyc and latest_kyc['status'] == 'approved':
            flash("আপনার KYC ইতিমধ্যে ভেরিফাইড রয়েছে!", "info")
            return redirect(url_for('kyc_page'))

        full_name = request.form.get('full_name', '').strip()
        try:
            age = int(request.form.get('age', 18))
        except ValueError:
            age = 13

        sender_number = request.form.get('sender_number', '').strip()
        trx_id = request.form.get('trx_id', '').strip()

        if not full_name or not sender_number or not trx_id:
            flash("সবগুলো তথ্য সঠিকভাবে পূরণ করুন!", "danger")
            return redirect(url_for('kyc_page'))

        # TrxID ডুপ্লিকেট চেক
        dup_trx = sb.table('kyc_requests').select('id').eq('trx_id', trx_id).execute().data
        if dup_trx:
            flash("এই TrxID দিয়ে ইতিমধ্যে একটি রিকোয়েস্ট জমা দেওয়া হয়েছে!", "danger")
            return redirect(url_for('kyc_page'))

        sb.table('kyc_requests').insert({
            'user_id': user_id,
            'full_name': full_name,
            'age': age,
            'sender_number': sender_number,
            'trx_id': trx_id,
            'status': 'pending'
        }).execute()

        flash("🎉 আপনার KYC ভেরিফিকেশন ফি সফলভাবে জমা হয়েছে! অ্যাডমিন চেক করে ৩০ মিনিটের মধ্যে একাউন্ট ভেরিফাই করে দেবে।", "success")
        return redirect(url_for('kyc_page'))

    return render_template('kyc.html', user=user, latest_kyc=latest_kyc)
    
# ==========================================================
# ABOUT US & BUSINESS MODEL CONTROLLER
# ==========================================================
@app.route('/about')
def about_page():
    return render_template('about.html')

@app.route('/admin/kyc')
@admin_required
def admin_kyc_list():
    sb = get_supabase()
    page = int(request.args.get('page', 1))
    limit = 20
    offset = (page - 1) * limit

    query = sb.table('kyc_requests').select('*, users(name, email)').eq('status', 'pending')

    kyc_res = query.order('id', desc=True).range(offset, offset + limit - 1).execute().data or []

    all_pending = sb.table('kyc_requests').select('id').eq('status', 'pending').execute().data or []
    total_count = len(all_pending)
    has_next = (offset + limit) < total_count

    return render_template(
        'admin/kyc.html', 
        kyc_requests=kyc_res,
        page=page,
        has_next=has_next,
        total_count=total_count
    )
    

@app.route('/admin/kyc/<int:kyc_id>/approve', methods=['POST'])
@admin_required
def admin_kyc_approve(kyc_id):
    sb = get_supabase()
    req = sb.table('kyc_requests').select('*').eq('id', kyc_id).single().execute().data
    if not req or req.get('status') == 'approved':
        flash("অবৈধ বা ইতিমধ্যে অনুমোদিত রিকোয়েস্ট!", "danger")
        return redirect(url_for('admin_kyc_list'))

    # কেওয়াইসি স্ট্যাটাস 'approved' করা
    sb.table('kyc_requests').update({'status': 'approved'}).eq('id', kyc_id).execute()
    flash("কেওয়াইসি সফলভাবে অ্যাপ্রুভ করা হয়েছে!", "success")
    return redirect(url_for('admin_kyc_list'))

@app.route('/admin/kyc/<int:kyc_id>/reject', methods=['POST'])
@admin_required
def admin_kyc_reject(kyc_id):
    sb = get_supabase()
    sb.table('kyc_requests').update({'status': 'rejected'}).eq('id', kyc_id).execute()
    flash("কেওয়াইসি রিকোয়েস্টটি রিজেক্ট করা হয়েছে!", "warning")
    return redirect(url_for('admin_kyc_list'))
    
# ==========================================================
# SPONSORSHIP & PARTNER PROGRAM CONTROLLER
# ==========================================================
@app.route('/sponsor', methods=['GET', 'POST'])
def sponsor():
    sb = get_supabase()
    user = None
    is_logged_in = 'user_id' in session

    if is_logged_in:
        user = sb.table('users').select('*').eq('id', session['user_id']).single().execute().data

    if request.method == 'POST':
        # শর্ত: লগইন ছাড়া স্পনসর ফর্ম সাবমিট হবে না
        if not is_logged_in:
            flash("স্পনসরশিপের জন্য আবেদন করতে অনুগ্রহ করে প্রথমে লগইন করুন!", "danger")
            return redirect(url_for('index'))

        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        link = request.form.get('link', '').strip()
        description = request.form.get('description', '').strip()

        if not name or not email or not link or not description:
            flash("সবগুলো তথ্য সঠিকভাবে পূরণ করুন!", "danger")
            return redirect(url_for('sponsor'))

        sb.table('sponsors').insert({
            'user_id': session['user_id'],
            'name': name,
            'email': email,
            'link': link,
            'description': description
        }).execute()

        flash("🎉 অভিনন্দন! আপনার স্পনসরশিপ আবেদন সফলভাবে জমা হয়েছে। আমাদের পার্টনারশিপ টিম দ্রুতই আপনার সাথে যোগাযোগ করবে।", "success")
        return redirect(url_for('sponsor'))

    return render_template('sponsor.html', is_logged_in=is_logged_in, user=user)

# ==========================================================
# HELP & SUPPORT CENTER CONTROLLER
# ==========================================================
@app.route('/help')
def help_page():
    sb = get_supabase()
    user = None
    if 'user_id' in session:
        user = sb.table('users').select('*').eq('id', session['user_id']).single().execute().data
    return render_template('help.html', user=user)

@app.route('/help/vote', methods=['POST'])
def help_vote():
    sb = get_supabase()
    data = request.get_json() or {}
    has_tg = bool(data.get('has_telegram', False))
    user_id = session.get('user_id')

    # সরাসরি ডেটাবেসে ভোট সেভ
    sb.table('help_votes').insert({
        'user_id': user_id,
        'has_telegram': has_tg
    }).execute()

    return jsonify({"success": True, "message": "ভোট সফলভাবে জমা হয়েছে!"})
    
@app.route('/register', methods=['POST'])
def register():
    sb = get_supabase()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    
    # ফর্ম অথবা সেশন থেকে রেফারেল কোড নেওয়া (বড়-ছোট হাতের যেকোনো অক্ষর সমর্থন করবে)
    ref_by = request.form.get('ref_by', '').strip().upper() or session.get('cached_ref', '')
    device_id = request.form.get('device_id', '').strip()

    if not name or not email or not password:
        flash("সবগুলো তথ্য সঠিকভাবে পূরণ করুন!", "danger")
        return redirect(url_for('index'))

    # শুধুমাত্র জিমেইল গ্রহণযোগ্য
    if not email.endswith('@gmail.com'):
        flash("অনুগ্রহ করে একটি সঠিক ও বৈধ ইমেইল অ্যাড্রেস প্রদান করুন!", "danger")
        return redirect(url_for('index'))

    # ১ ডিভাইসে একাধিক অ্যাকাউন্ট ব্লক (যদি ডিভাইস টোকেন থাকে)
    if device_id:
        existing_device = sb.table('users').select('id').eq('device_id', device_id).execute().data
        if existing_device:
            flash("এই ডিভাইস থেকে ইতিমধ্যে একটি অ্যাকাউন্ট খোলা হয়েছে!", "danger")
            return redirect(url_for('index'))

    # ইমেইল ডুপ্লিকেট চেক
    existing_email = sb.table('users').select('id').eq('email', email).execute().data
    if existing_email:
        flash("এই ইমেইল দিয়ে ইতিমধ্যে অ্যাকাউন্ট তৈরি করা আছে!", "danger")
        return redirect(url_for('index'))

    # নতুন ইউজারের জন্য নিজস্ব ইউনিক রেফার কোড
    my_ref_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    initial_balance = 50.00  # সরাসরি সাইন-আপে ৫০ টাকা

    # রেফারেল বোনাস লজিক
    valid_referrer = None
    if ref_by:
        # কেস-ইনসেনসিটিভ সার্চ (ছোট-বড় যেকোনো অক্ষরে কাজ করবে)
        referrer_res = sb.table('users').select('*').ilike('referral_code', ref_by).execute().data
        if referrer_res:
            ref_user = referrer_res[0]
            # নিজের অ্যাকাউন্টে নিজে রেফার করা ব্লক
            if ref_user['email'] != email and ref_user.get('device_id') != device_id:
                valid_referrer = ref_user
                initial_balance = 100.00  # রেফারে জয়েন করায় ১০০ টাকা বোনাস

                # রেফারারকে সরাসরি ১৫ টাকা দেওয়া
                new_ref_bal = float(ref_user['balance']) + 15.00
                sb.table('users').update({'balance': new_ref_bal}).eq('id', ref_user['id']).execute()

    new_user = {
        'name': name,
        'email': email,
        'password_hash': generate_password_hash(password),
        'device_id': device_id if device_id else 'DEV-' + ''.join(random.choices(string.hexdigits, k=16)).upper(),
        'referral_code': my_ref_code,
        'referred_by': valid_referrer['referral_code'] if valid_referrer else None,
        'balance': initial_balance
    }

    try:
        inserted = sb.table('users').insert(new_user).execute()
        if inserted.data:
            session.permanent = True
            session['user_id'] = inserted.data[0]['id']
            session['user_name'] = name
            session.pop('cached_ref', None) # ক্লিয়ার সেশন
            flash(f"অভিনন্দন! আপনি ৳{initial_balance:.2f} জয়েনিং বোনাস পেয়েছেন।", "success")
            return redirect(url_for('dashboard'))
    except Exception as e:
        flash("রেজিস্ট্রেশন ত্রুটি, অনুগ্রহ করে পুনরায় চেষ্টা করুন।", "danger")
        
    return redirect(url_for('index'))


# ==========================================================
# ADMIN PROMOTIONS & ADVERTISER LEADS (/admin/promote)
# ==========================================================
@app.route('/admin/promote')
@admin_required
def admin_promotions():
    sb = get_supabase()
    all_promos = sb.table('promotions').select('*').order('id', desc=True).execute().data or []
    
    pending_count = sum(1 for p in all_promos if p.get('status') == 'pending')
    completed_count = sum(1 for p in all_promos if p.get('status') == 'completed')

    return render_template(
        'admin/promote.html', 
        promotions=all_promos,
        pending_count=pending_count,
        completed_count=completed_count
    )

@app.route('/admin/promote/<int:promo_id>/status/<new_status>', methods=['POST'])
@admin_required
def admin_promotion_status(promo_id, new_status):
    sb = get_supabase()
    if new_status in ['pending', 'contacted', 'completed']:
        sb.table('promotions').update({'status': new_status}).eq('id', promo_id).execute()
        flash(f"ক্যাম্পেইন স্ট্যাটাস সফলভাবে '{new_status}' করা হয়েছে!", "success")
    return redirect(url_for('admin_promotions'))

@app.route('/admin/promote/<int:promo_id>/delete', methods=['POST'])
@admin_required
def admin_promotion_delete(promo_id):
    sb = get_supabase()
    sb.table('promotions').delete().eq('id', promo_id).execute()
    flash("প্রমোশন রিকোয়েস্টটি মুছে ফেলা হয়েছে!", "success")
    return redirect(url_for('admin_promotions'))
    
# ==========================================================
# ADMIN USER PASSWORD RESET & CARD GENERATOR (/admin/pass)
# ==========================================================
@app.route('/admin/pass', methods=['GET', 'POST'])
@admin_required
def admin_change_password():
    sb = get_supabase()
    reset_data = None
    
    if request.method == 'POST':
        user_identifier = request.form.get('user_identifier', '').strip()
        new_password = request.form.get('new_password', '').strip()

        if not user_identifier or not new_password:
            flash("ইউজারের ইমেইল/আইডি এবং নতুন পাসওয়ার্ড উভয়ই আবশ্যক!", "danger")
            return redirect(url_for('admin_change_password'))

        query = sb.table('users').select('id, name, email')
        if user_identifier.isdigit():
            user_data = query.eq('id', int(user_identifier)).execute().data
        else:
            user_data = query.eq('email', user_identifier.lower()).execute().data

        if not user_data:
            flash(f"'{user_identifier}' দিয়ে কোনো ইউজার খুঁজে পাওয়া যায়নি!", "danger")
            return redirect(url_for('admin_change_password'))

        target_user = user_data[0]

        # পাসওয়ার্ড হ্যাশ করে আপডেট
        hashed_password = generate_password_hash(new_password)
        sb.table('users').update({'password_hash': hashed_password}).eq('id', target_user['id']).execute()

        flash(f"🎉 ইউজার '{target_user['name']}' এর পাসওয়ার্ড সফলভাবে রিসেট হয়েছে!", "success")
        
        # ইউজারকে পাঠানোর জন্য রেডিমেড ডাটা পাস করা
        reset_data = {
            'id': target_user['id'],
            'name': target_user['name'],
            'email': target_user['email'],
            'password': new_password,
            'time': datetime.now().strftime('%d %b, %Y • %I:%M %p')
        }

    # ইউজার তালিকা আনা
    search_q = request.args.get('q', '').strip()
    u_query = sb.table('users').select('id, name, email, referral_code, created_at')
    if search_q:
        u_query = u_query.ilike('email', f"%{search_q}%")
    recent_users = u_query.order('id', desc=True).limit(10).execute().data or []

    return render_template(
        'admin/pass.html', 
        users=recent_users, 
        search_q=search_q, 
        reset_data=reset_data
        )


# ==========================================================
# MATH QUIZ EARNING CONTROLLER (15 CHANCES / 24 HOURS)
# ==========================================================
def generate_math_problem():
    """মিড-লেভেল অংক এবং ৪টি সম্ভাব্য অপশন তৈরি করে"""
    op_type = random.choice(['add', 'sub', 'mul'])
    
    if op_type == 'add':
        n1 = random.randint(25, 75)
        n2 = random.randint(15, 65)
        ans = n1 + n2
        expr = f"{n1} + {n2}"
    elif op_type == 'sub':
        n1 = random.randint(50, 99)
        n2 = random.randint(15, 49)
        ans = n1 - n2
        expr = f"{n1} - {n2}"
    else:
        n1 = random.randint(8, 16)
        n2 = random.randint(5, 12)
        ans = n1 * n2
        expr = f"{n1} × {n2}"

    # ৩টি ভুল ও ১টি সঠিক অপশন তৈরি
    options = {ans}
    while len(options) < 4:
        offset = random.choice([-10, -5, -2, -1, 1, 2, 5, 10])
        fake = ans + offset
        if fake > 0:
            options.add(fake)

    opts = list(options)
    random.shuffle(opts)
    return expr, ans, opts

# ==========================================================
# GMAIL FARMING CONTROLLER (AUTO 2-HOUR LOCK & RELEASE)
# ==========================================================
def auto_release_expired_gmail_tasks(sb):
    """২ ঘণ্টা পার হয়ে যাওয়া লকড টাস্কগুলোকে সবার জন্য পুনরায় উন্মুক্ত করে"""
    two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    sb.table('gmail_tasks').update({
        'status': 'available',
        'locked_by': None,
        'locked_at': None
    }).eq('status', 'locked').lt('locked_at', two_hours_ago).execute()

@app.route('/gmail')
@login_required
@kyc_required
def gmail_hub():
    sb = get_supabase()
    user_id = session['user_id']
    auto_release_expired_gmail_tasks(sb)

    # ইউজারের বর্তমান লক করা কোনো কাজ আছে কিনা চেক
    my_locked_task = sb.table('gmail_tasks').select('*') \
        .eq('locked_by', user_id).in_('status', ['locked', 'submitted']).execute().data

    active_task = my_locked_task[0] if my_locked_task else None

    # সবার জন্য উন্মুক্ত টাস্কগুলো আনা
    available_tasks = sb.table('gmail_tasks').select('*') \
        .eq('status', 'available').order('id', desc=True).execute().data or []

    return render_template('gmail.html', active_task=active_task, tasks=available_tasks)

@app.route('/gmail/lock/<int:task_id>', methods=['POST'])
@login_required
def gmail_lock_task(task_id):
    sb = get_supabase()
    user_id = session['user_id']
    auto_release_expired_gmail_tasks(sb)

    # ১ জন ইউজার একসাথে ১টির বেশি টাস্ক লক রাখতে পারবে না
    existing = sb.table('gmail_tasks').select('id') \
        .eq('locked_by', user_id).eq('status', 'locked').execute().data
    if existing:
        flash("আপনার ইতিমধ্যে একটি কাজ চালু রয়েছে! সেটি সম্পন্ন বা বাতিল করুন।", "warning")
        return redirect(url_for('gmail_hub'))

    # টাস্কটি এখনো অ্যাভেইলেবল আছে কিনা চেক
    task = sb.table('gmail_tasks').select('*').eq('id', task_id).single().execute().data
    if not task or task.get('status') != 'available':
        flash("এই কাজটি ইতিমধ্যে অন্য একজন ইউজার নিয়ে নিয়েছে!", "danger")
        return redirect(url_for('gmail_hub'))

    # টাস্কটি এই ইউজারের জন্য ২ ঘণ্টার জন্য লক করা
    sb.table('gmail_tasks').update({
        'status': 'locked',
        'locked_by': user_id,
        'locked_at': datetime.now(timezone.utc).isoformat()
    }).eq('id', task_id).execute()

    flash("টাস্কটি আপনার জন্য সফলভাবে ২ ঘণ্টার জন্য লক করা হয়েছে!", "success")
    return redirect(url_for('gmail_hub'))

@app.route('/gmail/submit/<int:task_id>', methods=['POST'])
@login_required
def gmail_submit_task(task_id):
    sb = get_supabase()
    user_id = session['user_id']

    task = sb.table('gmail_tasks').select('*').eq('id', task_id).single().execute().data
    if not task or task.get('locked_by') != user_id:
        flash("অবৈধ রিকোয়েস্ট!", "danger")
        return redirect(url_for('gmail_hub'))

    # ইউজারের টাইপ করার দরকার নেই, সিস্টেম স্বয়ংক্রিয়ভাবে প্রিফিক্স দিয়ে ইমেইল সেট করবে
    auto_email = f"{task['email_prefix']}@gmail.com"

    # সাবমিট করা হলো
    sb.table('gmail_tasks').update({
        'status': 'submitted',
        'submitted_email': auto_email,
        'submitted_at': datetime.now(timezone.utc).isoformat()
    }).eq('id', task_id).execute()

    flash("🎉 কাজ সফলভাবে জমা হয়েছে! অ্যাডমিন চেক করে টাকা ব্যালেন্সে যোগ করে দেবে।", "success")
    return redirect(url_for('gmail_hub'))
    
@app.route('/gmail/cancel/<int:task_id>', methods=['POST'])
@login_required
def gmail_cancel_task(task_id):
    sb = get_supabase()
    user_id = session['user_id']
    # লক বাতিল করে পুনরায় সবার জন্য উন্মুক্ত করা
    sb.table('gmail_tasks').update({
        'status': 'available',
        'locked_by': None,
        'locked_at': None
    }).eq('id', task_id).eq('locked_by', user_id).eq('status', 'locked').execute()

    flash("টাস্কটি বাতিল করা হয়েছে এবং সবার জন্য উন্মুক্ত করে দেওয়া হয়েছে।", "info")
    return redirect(url_for('gmail_hub'))

# ==========================================================
# ADMIN GMAIL FARM CONTROLLER (/admin/gmail)
# ==========================================================
@app.route('/admin/gmail', methods=['GET', 'POST'])
@admin_required
def admin_gmail():
    sb = get_supabase()
    auto_release_expired_gmail_tasks(sb)

    # নতুন জিমেইল টাস্ক তৈরি
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        email_prefix = request.form.get('email_prefix', '').strip()
        password = request.form.get('password', '').strip()
        try:
            price = float(request.form.get('price', 8.00))
        except ValueError:
            price = 8.00

        sb.table('gmail_tasks').insert({
            'first_name': first_name,
            'email_prefix': email_prefix,
            'password': password,
            'price': price,
            'status': 'available'
        }).execute()

        flash("নতুন জিমেইল ফার্মিং টাস্ক সফলভাবে তৈরি হয়েছে!", "success")
        return redirect(url_for('admin_gmail'))

    # পর্যালোচনার জন্য জমা পড়া কাজ
    submitted_tasks = sb.table('gmail_tasks').select('*, users(name, email)') \
        .eq('status', 'submitted').order('submitted_at', desc=True).execute().data or []

    # সকল টাস্কের তালিকা
    all_tasks = sb.table('gmail_tasks').select('*').order('id', desc=True).limit(50).execute().data or []

    return render_template('admin/gmail.html', submitted=submitted_tasks, all_tasks=all_tasks)

@app.route('/admin/gmail/<int:task_id>/approve', methods=['POST'])
@admin_required
def admin_gmail_approve(task_id):
    sb = get_supabase()
    task = sb.table('gmail_tasks').select('*').eq('id', task_id).single().execute().data
    if not task or task.get('status') != 'submitted':
        flash("অবৈধ টাস্ক!", "danger")
        return redirect(url_for('admin_gmail'))

    # ইউজারের ব্যালেন্সে টাকা যোগ
    user = sb.table('users').select('balance').eq('id', task['locked_by']).single().execute().data
    new_bal = float(user['balance']) + float(task['price'])
    sb.table('users').update({'balance': new_bal}).eq('id', task['locked_by']).execute()

    # স্ট্যাটাস completed করা
    sb.table('gmail_tasks').update({'status': 'completed'}).eq('id', task_id).execute()

    flash(f"জিমেইল অ্যাপ্রুভ হয়েছে এবং ইউজারের অ্যাকাউন্টে ৳{task['price']} যোগ হয়েছে!", "success")
    return redirect(url_for('admin_gmail'))

    
# ==========================================================
# ADMIN SPONSORSHIP MANAGEMENT CONTROLLER (/admin/sponsor)
# ==========================================================
@app.route('/admin/sponsor')
@admin_required
def admin_sponsors():
    sb = get_supabase()
    all_sponsors = sb.table('sponsors').select('*').order('id', desc=True).execute().data or []
    
    pending_count = sum(1 for s in all_sponsors if s.get('status') == 'pending')
    approved_count = sum(1 for s in all_sponsors if s.get('status') == 'approved')

    return render_template(
        'admin/sponsor.html', 
        sponsors=all_sponsors,
        pending_count=pending_count,
        approved_count=approved_count
    )

@app.route('/admin/sponsor/<int:sponsor_id>/approve', methods=['POST'])
@admin_required
def admin_sponsor_approve(sponsor_id):
    sb = get_supabase()
    sb.table('sponsors').update({'status': 'approved'}).eq('id', sponsor_id).execute()
    flash("স্পনসরশিপ আবেদনটি সফলভাবে অনুমোদন (Approved) করা হয়েছে!", "success")
    return redirect(url_for('admin_sponsors'))

@app.route('/admin/sponsor/<int:sponsor_id>/reject', methods=['POST'])
@admin_required
def admin_sponsor_reject(sponsor_id):
    sb = get_supabase()
    sb.table('sponsors').update({'status': 'rejected'}).eq('id', sponsor_id).execute()
    flash("স্পনসরশিপ আবেদনটি রিজেক্ট করা হয়েছে!", "warning")
    return redirect(url_for('admin_sponsors'))

@app.route('/admin/sponsor/<int:sponsor_id>/delete', methods=['POST'])
@admin_required
def admin_sponsor_delete(sponsor_id):
    sb = get_supabase()
    sb.table('sponsors').delete().eq('id', sponsor_id).execute()
    flash("আবেদনটি ডাটাবেস থেকে মুছে ফেলা হয়েছে!", "success")
    return redirect(url_for('admin_sponsors'))
    
@app.route('/admin/gmail/<int:task_id>/reject', methods=['POST'])
@admin_required
def admin_gmail_reject(task_id):
    sb = get_supabase()
    # শর্ত: রিজেক্ট করলে কাজটি পুনরায় সবার জন্য available হয়ে যাবে
    sb.table('gmail_tasks').update({
        'status': 'available',
        'locked_by': None,
        'locked_at': None,
        'submitted_email': None,
        'submitted_at': None
    }).eq('id', task_id).execute()

    flash("টাস্কটি রিজেক্ট করা হয়েছে এবং পুনরায় সবার জন্য সাইটে লাইভ করে দেওয়া হয়েছে!", "warning")
    return redirect(url_for('admin_gmail'))

@app.route('/admin/gmail/<int:task_id>/delete', methods=['POST'])
@admin_required
def admin_gmail_delete(task_id):
    sb = get_supabase()
    sb.table('gmail_tasks').delete().eq('id', task_id).execute()
    flash("টাস্কটি ডিলিট করা হয়েছে!", "success")
    return redirect(url_for('admin_gmail'))
    


@app.route('/quiz')
@login_required
@kyc_required
def math_quiz():
    sb = get_supabase()
    user_id = session['user_id']
    user = sb.table('users').select('*').eq('id', user_id).single().execute().data

    # বিগত ২৪ ঘণ্টার হিসাব
    past_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    quizzes_done = sb.table('daily_activities').select('id') \
        .eq('user_id', user_id).eq('activity_type', 'quiz') \
        .gte('created_at', past_24h).execute().data or []

    remaining = max(0, 5 - len(quizzes_done))
    expr, ans, opts = generate_math_problem()
    session['quiz_answer'] = ans

    return render_template(
        'quiz.html', 
        user=user, 
        remaining=remaining, 
        question=expr, 
        options=opts
    )

@app.route('/quiz/submit', methods=['POST'])
@login_required
def quiz_submit():
    sb = get_supabase()
    user_id = session['user_id']
    data = request.get_json() or {}
    user_ans = data.get('answer')

    # ২৪ ঘণ্টার লিমিট চেক
    past_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    quizzes_done = sb.table('daily_activities').select('id') \
        .eq('user_id', user_id).eq('activity_type', 'quiz') \
        .gte('created_at', past_24h).execute().data or []

    if len(quizzes_done) >= 5:
        return jsonify({"success": False, "message": "আপনার আজকের ৫টি কুইজের সুযোগ শেষ! ২৪ ঘণ্টা পর আবার আসুন।", "remaining": 0})

    correct_ans = session.get('quiz_answer')
    if correct_ans is None:
        return jsonify({"success": False, "message": "প্রশ্নটি মেয়াদোত্তীর্ণ, রিফ্রেশ দিন!"})

    # উত্তর যাচাই
    if str(user_ans).strip() == str(correct_ans):
        # রিওয়ার্ড: ৩ থেকে ৬ টাকা (র‍্যান্ডম)
        reward_pool = [3.00, 3.50, 4.00, 4.50, 5.00, 5.50, 6.00]
        reward = random.choice(reward_pool)

        user = sb.table('users').select('balance').eq('id', user_id).single().execute().data
        new_bal = float(user['balance']) + reward

        sb.table('users').update({'balance': new_bal}).eq('id', user_id).execute()
        sb.table('daily_activities').insert({
            'user_id': user_id,
            'activity_type': 'quiz',
            'reward_earned': reward
        }).execute()

        remaining = max(0, 5 - (len(quizzes_done) + 1))
        session.pop('quiz_answer', None)

        return jsonify({
            "success": True, 
            "correct": True, 
            "reward": reward, 
            "new_balance": new_bal, 
            "remaining": remaining,
            "message": f"🎉 দারুণ! সঠিক উত্তর। আপনি ৳{reward:.2f} জিতেছেন!"
        })
    else:
        # ভুল উত্তর
        session.pop('quiz_answer', None)
        remaining = max(0, 5 - len(quizzes_done))
        return jsonify({
            "success": True, 
            "correct": False, 
            "correct_ans": correct_ans,
            "remaining": remaining,
            "message": f"ভুল উত্তর! সঠিক উত্তর ছিল: {correct_ans}। টাকা যোগ হয়নি।"
        })

@app.route('/quiz/next', methods=['POST'])
@login_required
def quiz_next():
    expr, ans, opts = generate_math_problem()
    session['quiz_answer'] = ans
    return jsonify({"question": expr, "options": opts})

# ==========================================================
# LOGOUT CONTROLLER (লগআউট করলে সরাসরি /login এ যাবে)
# ==========================================================
@app.route('/logout')
def logout():
    session.clear()
    flash("সফলভাবে লগআউট করা হয়েছে!", "info")
    return redirect(url_for('login'))
# ==========================================================
# USER ACCOUNT & PROFILE CONTROLLER
# ==========================================================
@app.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    sb = get_supabase()
    user_id = session['user_id']
    user = sb.table('users').select('*').eq('id', user_id).single().execute().data

    if request.method == 'POST':
        name = request.form.get('name', '').strip() or user['name']
        fb_link = request.form.get('fb_link', '').strip()
        tg_link = request.form.get('tg_link', '').strip()
        avatar_file = request.files.get('avatar')

        update_payload = {
            'name': name,
            'fb_link': fb_link if fb_link else None,
            'tg_link': tg_link if tg_link else None
        }

        # প্রোফাইল ছবি ImgBB Failover-এ আপলোড
        if avatar_file and avatar_file.filename != '':
            img_url = upload_to_imgbb(avatar_file.read())
            if img_url:
                update_payload['avatar_url'] = img_url
            else:
                flash("ইমেজ আপলোড ফেইল হয়েছে, সার্ভার ব্যস্ত!", "danger")
                return redirect(url_for('account'))

        sb.table('users').update(update_payload).eq('id', user_id).execute()
        flash("প্রোফাইল তথ্য সফলভাবে আপডেট হয়েছে!", "success")
        return redirect(url_for('account'))

    # রেফারেল ও টাস্ক সম্পন্ন সংখ্যা
    ref_count = len(sb.table('users').select('id').eq('referred_by', user['referral_code']).execute().data or [])
    completed_tasks = len(sb.table('submissions').select('id').eq('user_id', user_id).eq('status', 'approved').execute().data or [])

    return render_template('account.html', user=user, ref_count=ref_count, completed_tasks=completed_tasks)


# ==========================================================
# REFERRAL PAGE CONTROLLER
# ==========================================================
@app.route('/refer')
@login_required
def refer_page():
    sb = get_supabase()
    user_id = session['user_id']
    user = sb.table('users').select('*').eq('id', user_id).single().execute().data

    # ইউজারের রেফারেল কোড ব্যবহার করে যারা জয়েন করেছে তাদের তালিকা
    referred_users = sb.table('users').select('name, email, created_at') \
        .eq('referred_by', user['referral_code']) \
        .order('id', desc=True).execute().data or []

    # মোট রেফারেল আয়
    total_earned = len(referred_users) * 15.00

    return render_template(
        'refer.html',
        user=user,
        referred_users=referred_users,
        total_earned=total_earned
   ) 
    
# ==========================================================
# User Portal & Earning Features
# ==========================================================
@app.route('/app')
@login_required
def dashboard():
    sb = get_supabase()
    user = sb.table('users').select('*').eq('id', session['user_id']).single().execute().data
    
    # নোটিশ লোড করা
    notice_res = sb.table('settings').select('value').eq('key', 'site_notice').execute().data
    site_notice = notice_res[0]['value'] if notice_res else ""

    # মোট রেফার সংখ্যা
    ref_count = len(sb.table('users').select('id').eq('referred_by', user['referral_code']).execute().data or [])
    
    return render_template(
        'dashboard.html', 
        user=user, 
        notice=site_notice, 
        referral_count=ref_count
    )
    
# ==========================================================
# USER TASKS HUB (নতুন টাস্ক সবার উপরে থাকবে)
# ==========================================================
@app.route('/tasks')
@login_required
@kyc_required
def tasks():
    sb = get_supabase()
    user_id = session['user_id']

    # ১. ইউজারের পেন্ডিং ও অনুমোদিত টাস্ক তালিকা আনা
    user_subs = sb.table('submissions').select('task_id, status').eq('user_id', user_id).execute().data or []
    hidden_task_ids = [s['task_id'] for s in user_subs if s['status'] in ['pending', 'approved']]

    # ২. নতুন টাস্ক সবার উপরে আনার জন্য order('id', desc=True) যোগ করা হলো
    all_tasks = sb.table('tasks').select('*').eq('is_active', True).order('id', desc=True).execute().data or []
    
    # ৩. ইতিমধ্যে সম্পন্ন করা কাজ ফিল্টার করে নতুন কাজগুলো ক্রমানুসারে রাখা
    available_tasks = [t for t in all_tasks if t['id'] not in hidden_task_ids]

    return render_template('tasks.html', tasks=available_tasks)
    
@app.route('/task/<int:task_id>', methods=['GET', 'POST'])
@login_required
def task_detail(task_id):
    sb = get_supabase()
    task = sb.table('tasks').select('*').eq('id', task_id).single().execute().data
    if not task:
        flash("টাস্কটি খুঁজে পাওয়া যায়নি!", "danger")
        return redirect(url_for('tasks'))

    if request.method == 'POST':
        file = request.files.get('screenshot')
        if not file or file.filename == '':
            flash("প্রমাণের স্ক্রিনশট সিলেক্ট করুন!", "danger")
            return redirect(request.url)

        # ImgBB Failover আপলোড
        img_url = upload_to_imgbb(file.read())
        if not img_url:
            flash("ইমেজ হোস্ট সার্ভার ব্যস্ত! অনুগ্রহ করে এডমিনকে জানান।", "danger")
            return redirect(request.url)

        sb.table('submissions').insert({
            'task_id': task_id,
            'user_id': session['user_id'],
            'proof_url': img_url,
            'status': 'pending'
        }).execute()

        flash("টাস্ক প্রুফ জমা হয়েছে! এডমিন রিভিউ শেষে টাকা যোগ হবে।", "success")
        return redirect(url_for('tasks'))

    return render_template('task_details.html', task=task)
    
# ==========================================================
# LUCKY SPIN CONTROLLER (BUG-FREE WITH LIVE REMAINING)
# ==========================================================
@app.route('/spin', methods=['GET', 'POST'])
@login_required
def spin_page():
    sb = get_supabase()
    user_id = session['user_id']
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    spins_today = sb.table('daily_activities').select('id') \
        .eq('user_id', user_id).eq('activity_type', 'spin') \
        .gte('created_at', today_start).execute().data or []

    # POST: স্পিন রিওয়ার্ড ক্যালকুলেশন
    if request.method == 'POST':
        if len(spins_today) >= 3:
            return jsonify({
                "success": False, 
                "message": "আজকের ৩টি স্পিন সম্পন্ন হয়েছে! আগামীকাল আবার আসুন।", 
                "remaining": 0
            })

        # হুইলের স্লাইসের সাথে মিল রেখে রিওয়ার্ডস
        slices = [0.50, 1.00, 1.50, 2.00, 3.00, 5.00]
        reward = random.choice(slices)

        user = sb.table('users').select('balance').eq('id', user_id).single().execute().data
        new_bal = float(user['balance']) + reward

        sb.table('users').update({'balance': new_bal}).eq('id', user_id).execute()
        sb.table('daily_activities').insert({
            'user_id': user_id, 
            'activity_type': 'spin', 
            'reward_earned': reward
        }).execute()

        # নতুন বাকি সংখ্যা হিসাব
        remaining = max(0, 3 - (len(spins_today) + 1))
        
        return jsonify({
            "success": True, 
            "reward": reward, 
            "new_balance": new_bal, 
            "remaining": remaining
        })

    # GET: পেজ রেন্ডার
    user = sb.table('users').select('*').eq('id', user_id).single().execute().data
    remaining_spins = max(0, 3 - len(spins_today))
    return render_template('spin.html', user=user, remaining=remaining_spins)

# ==========================================================
# SCRATCH CARD CONTROLLER (BUG-FREE WITH LIVE REMAINING)
# ==========================================================
@app.route('/scratch', methods=['GET', 'POST'])
@login_required
def scratch_page():
    sb = get_supabase()
    user_id = session['user_id']
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
    scratch_today = sb.table('daily_activities').select('id') \
        .eq('user_id', user_id).eq('activity_type', 'scratch') \
        .gte('created_at', today_start).execute().data or []

    # POST: স্ক্র্যাচ রিওয়ার্ড ক্লেম
    if request.method == 'POST':
        if len(scratch_today) >= 3:
            return jsonify({
                "success": False, 
                "message": "আজকের ৩টি স্ক্র্যাচ ইতিমধ্যে শেষ হয়েছে! আগামীকাল আবার আসুন।",
                "remaining": 0
            })

        # রিওয়ার্ড অ্যামাউন্ট (৳১.০০ থেকে ৳৬.০০)
        reward_pool = [1.00, 1.50, 2.00, 2.50, 3.00, 4.00, 5.00, 6.00]
        reward = random.choice(reward_pool)

        user = sb.table('users').select('balance').eq('id', user_id).single().execute().data
        new_bal = float(user['balance']) + reward

        sb.table('users').update({'balance': new_bal}).eq('id', user_id).execute()
        sb.table('daily_activities').insert({
            'user_id': user_id, 
            'activity_type': 'scratch', 
            'reward_earned': reward
        }).execute()

        remaining = max(0, 3 - (len(scratch_today) + 1))
        
        return jsonify({
            "success": True, 
            "reward": reward, 
            "new_balance": new_bal, 
            "remaining": remaining
        })

    # GET: পেজ রেন্ডার
    user = sb.table('users').select('*').eq('id', user_id).single().execute().data
    remaining_scratch = max(0, 3 - len(scratch_today))
    return render_template('scratch.html', user=user, remaining=remaining_scratch)
    
@app.route('/withdraw', methods=['GET', 'POST'])
@login_required
@kyc_required
def withdraw():
    sb = get_supabase()
    user_id = session['user_id']
    user = sb.table('users').select('*').eq('id', user_id).single().execute().data
    ref_count = len(sb.table('users').select('id').eq('referred_by', user['referral_code']).execute().data or [])

    # GET: ডেডিকেটেড পেজ রেন্ডার
    if request.method == 'GET':
        return render_template('withdraw.html', user=user, referral_count=ref_count)
        
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        amount = 0

    method = request.form.get('method', '').strip()
    account = request.form.get('account', '').strip()

    if amount < 450:
        flash("সর্বনিম্ন উইথড্রয়াল অ্যামাউন্ট 450 টাকা!", "danger")
        return redirect(url_for('withdraw'))

    if float(user['balance']) < amount:
        flash("আপনার অ্যাকাউন্টে পর্যাপ্ত ব্যালেন্স নেই!", "danger")
        return redirect(url_for('withdraw'))

    if ref_count < 4:
        flash(f"উইথড্র করতে সর্বনিম্ন ৪টি রেফারেল প্রয়োজন! আপনার বর্তমান রেফারেল: {ref_count} টি।", "danger")
        return redirect(url_for('withdraw'))
        
    sb.table('users').update({'balance': float(user['balance']) - amount}).eq('id', user_id).execute()
    sb.table('withdrawals').insert({
        'user_id': user_id,
        'amount': amount,
        'method': method,
        'account_number': account,
        'status': 'pending'
    }).execute()

    flash("উইথড্রয়াল রিকোয়েস্ট সফলভাবে জমা হয়েছে!", "success")
    return redirect(url_for('dashboard'))


# ==========================================================
# ADMIN TASK EDIT & DELETE CONTROLLER
# ==========================================================
@app.route('/admin/task/<int:task_id>/edit', methods=['POST'])
@admin_required
def admin_task_edit(task_id):
    sb = get_supabase()
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '').strip()
    link = request.form.get('link', '').strip()
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        amount = 0.0

    sb.table('tasks').update({
        'title': title,
        'description': description,
        'amount': amount,
        'link': link
    }).eq('id', task_id).execute()

    flash("টাস্কের তথ্য সফলভাবে আপডেট করা হয়েছে!", "success")
    return redirect(url_for('admin_task'))

# ==========================================================
# ADMIN USER ID INVESTIGATION & FULL AUDIT (/admin/check)
# ==========================================================
@app.route('/admin/check')
@admin_required
def admin_user_check():
    sb = get_supabase()
    q = request.args.get('q', '').strip()
    
    target_user = None
    referrer = None
    referred_members = []
    task_subs = []
    withdrawals = []
    stats = {}

    if q:
        # ১. UID (সংখ্যা), Email বা Referral Code দিয়ে ইউজার খোঁজা
        if q.isdigit():
            res = sb.table('users').select('*').eq('id', int(q)).execute().data
            if res: target_user = res[0]
            
        if not target_user:
            res = sb.table('users').select('*').eq('email', q.lower()).execute().data
            if res: target_user = res[0]
            
        if not target_user:
            res = sb.table('users').select('*').eq('referral_code', q.upper()).execute().data
            if res: target_user = res[0]

        # ২. ইউজার পাওয়া গেলে তার সব ডাটা বের করা
        if target_user:
            u_id = target_user['id']
            ref_code = target_user['referral_code']

            # ক) এই ইউজারকে কে রেফার করেছে (Referrer)
            if target_user.get('referred_by'):
                ref_res = sb.table('users').select('id, name, email, referral_code').eq('referral_code', target_user['referred_by']).execute().data
                if ref_res: referrer = ref_res[0]

            # খ) এই ইউজারের রেফার করা সব মেম্বার ও তাদের বর্তমান ব্যালেন্স
            referred_members = sb.table('users').select('id, name, email, balance, is_banned, created_at') \
                .eq('referred_by', ref_code).order('id', desc=True).execute().data or []

            # গ) টাস্ক সাবমিশন হিস্ট্রি
            task_subs = sb.table('submissions').select('*, tasks(title, amount)') \
                .eq('user_id', u_id).order('id', desc=True).execute().data or []

            # ঘ) উইথড্রয়াল হিস্ট্রি (রিজেক্ট সহ)
            withdrawals = sb.table('withdrawals').select('*') \
                .eq('user_id', u_id).order('id', desc=True).execute().data or []

            # ঙ) সামারি ও অ্যাক্টিভিটি হিসাব
            total_ref_balance = sum(float(m.get('balance', 0)) for m in referred_members)
            rejected_withdraws = sum(1 for w in withdrawals if w.get('status') == 'rejected')
            approved_withdraws = sum(1 for w in withdrawals if w.get('status') == 'approved')
            
            stats = {
                'total_ref_count': len(referred_members),
                'total_ref_balance': total_ref_balance,
                'rejected_withdraws': rejected_withdraws,
                'approved_withdraws': approved_withdraws,
                'total_tasks': len(task_subs),
                'approved_tasks': sum(1 for t in task_subs if t.get('status') == 'approved')
            }

    return render_template(
        'admin/check.html',
        q=q,
        user=target_user,
        referrer=referrer,
        referred_members=referred_members,
        task_subs=task_subs,
        withdrawals=withdrawals,
        stats=stats
    )
    
@app.route('/admin/task/<int:task_id>/delete', methods=['POST'])
@admin_required
def admin_task_delete(task_id):
    sb = get_supabase()
    sb.table('tasks').delete().eq('id', task_id).execute()
    flash("টাস্কটি স্থায়ীভাবে মুছে ফেলা হয়েছে!", "success")
    return redirect(url_for('admin_task'))
    
# ==========================================================
# USER HISTORY (TASKS & WITHDRAWALS)
# ==========================================================
@app.route('/history')
@login_required
def history():
    sb = get_supabase()
    user_id = session['user_id']
    user = sb.table('users').select('*').eq('id', user_id).single().execute().data

    # ১. টাস্ক সাবমিশন হিস্ট্রি
    task_subs = sb.table('submissions').select('*, tasks(title, amount)') \
        .eq('user_id', user_id).order('id', desc=True).execute().data or []

    # ২. উইথড্রয়াল হিস্ট্রি
    withdrawals = sb.table('withdrawals').select('*') \
        .eq('user_id', user_id).order('id', desc=True).execute().data or []

    return render_template(
        'history.html', 
        user=user, 
        task_subs=task_subs, 
        withdrawals=withdrawals
    )
    

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    # লগইন না থাকলে সরাসরি হোমপেজে পাঠাবে
    if 'user_id' not in session:
        flash("প্রথমে admin@gmail.com দিয়ে লগইন করুন!", "danger")
        return redirect(url_for('index'))

    # admin@gmail.com ছাড়া অন্য কোনো ইউজার এই পেজ ওপেন করতে পারবে না
    sb = get_supabase()
    user = sb.table('users').select('email').eq('id', session['user_id']).single().execute().data
    if not user or user.get('email') != 'admin@gmail.com':
        flash("শুধুমাত্র প্রধান অ্যাডমিন (admin@gmail.com) এর জন্য সংরক্ষিত!", "danger")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        secret = request.form.get('admin_key', '')
        if secret == ADMIN_SECRET_PASS:
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        flash("ভুল অ্যাডমিন সিক্রেট কি!", "danger")

    return render_template('admin/login.html')

    
# ==========================================================
# ADMIN DASHBOARD STATS CONTROLLER (UNLIMITED COUNT FIX)
# ==========================================================
@app.route('/admin')
@admin_required
def admin_dashboard():
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    try:
        # ১. সঠিক ও আনলিমিটেড মোট ইউজার গণনা (count='exact')
        total_res = sb.table('users').select('id', count='exact').execute()
        total_users = total_res.count if total_res.count is not None else len(total_res.data or [])

        # ২. আজকের সাইন-আপ গণনা
        today_res = sb.table('users').select('id', count='exact').gte('created_at', today_start).execute()
        today_users = today_res.count if today_res.count is not None else len(today_res.data or [])

        # ৩. গতকালের সাইন-আপ গণনা
        yest_res = sb.table('users').select('id', count='exact').gte('created_at', yesterday_start).lt('created_at', today_start).execute()
        yesterday_users = yest_res.count if yest_res.count is not None else len(yest_res.data or [])

        # ৪. আজকের টাস্ক সাবমিশন গণনা
        sub_res = sb.table('submissions').select('id', count='exact').gte('created_at', today_start).execute()
        today_submissions = sub_res.count if sub_res.count is not None else len(sub_res.data or [])

    except Exception:
        # ফলব্যাক হিসাব যদি কুয়েরি কাউন্ট কখনো ফেইল করে
        total_users = len(sb.table('users').select('id').execute().data or [])
        today_users = len(sb.table('users').select('id').gte('created_at', today_start).execute().data or [])
        yesterday_users = len(sb.table('users').select('id').gte('created_at', yesterday_start).lt('created_at', today_start).execute().data or [])
        today_submissions = len(sb.table('submissions').select('id').gte('created_at', today_start).execute().data or [])

    # গ্লোবাল সাইট নোটিশ আনা
    notice_res = sb.table('settings').select('value').eq('key', 'site_notice').execute().data
    current_notice = notice_res[0]['value'] if notice_res else ""

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        today_users=today_users,
        yesterday_users=yesterday_users,
        today_submissions=today_submissions,
        notice=current_notice
    )
    
# ==========================================================
# GLOBAL TEMPLATE CONTEXT (হেডারে প্রোফাইল ছবি পাওয়ার জন্য)
# ==========================================================
@app.context_processor
def inject_global_user():
    if 'user_id' in session:
        sb = get_supabase()
        u = sb.table('users').select('id, name, balance, avatar_url, referral_code') \
            .eq('id', session['user_id']).single().execute().data
        return dict(current_user=u)
    return dict(current_user=None)

# ==========================================================
# ALL WORK HUB (/allwork)
# ==========================================================
@app.route('/allwork')
@login_required
def all_work():
    return render_template('allwork.html')
    
@app.route('/admin/notice', methods=['POST'])
@admin_required
def admin_update_notice():
    sb = get_supabase()
    new_notice = request.form.get('site_notice', '').strip()
    sb.table('settings').upsert({'key': 'site_notice', 'value': new_notice}).execute()
    flash("সাইট নোটিশ সফলভাবে আপডেট হয়েছে!", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@admin_required
def admin_users():
    sb = get_supabase()
    page = int(request.args.get('page', 1))
    search = request.args.get('q', '').strip()
    limit = 20
    offset = (page - 1) * limit

    query = sb.table('users').select('*')
    if search:
        query = query.ilike('email', f"%{search}%")

    users_list = query.order('id', desc=True).range(offset, offset + limit - 1).execute().data or []
    return render_template('admin/users.html', users=users_list, page=page, search=search)

@app.route('/admin/user/<int:user_id>/ban', methods=['POST'])
@admin_required
def admin_toggle_ban(user_id):
    sb = get_supabase()
    user = sb.table('users').select('is_banned').eq('id', user_id).single().execute().data
    if user:
        sb.table('users').update({'is_banned': not user['is_banned']}).eq('id', user_id).execute()
        flash("ইউজার স্ট্যাটাস পরিবর্তন করা হয়েছে।", "success")
    return redirect(request.referrer or url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/balance', methods=['POST'])
@admin_required
def admin_modify_balance(user_id):
    sb = get_supabase()
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        amount = 0
        
    user = sb.table('users').select('balance').eq('id', user_id).single().execute().data
    if user:
        new_balance = float(user['balance']) + amount
        sb.table('users').update({'balance': new_balance}).eq('id', user_id).execute()
        flash("ব্যালেন্স আপডেট সফল হয়েছে!", "success")
    return redirect(request.referrer or url_for('admin_users'))

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    sb = get_supabase()
    sb.table('users').delete().eq('id', user_id).execute()
    flash("ইউজার ডিলিট করা হয়েছে!", "success")
    return redirect(url_for('admin_users'))

@app.route('/admin/withdraw')
@admin_required
def admin_withdraw():
    sb = get_supabase()
    reqs = sb.table('withdrawals').select('*, users(email, balance)').eq('status', 'pending').order('id', desc=True).execute().data or []

    # ইউজারের আগের মোট রিজেকশন হিস্ট্রি গণনা
    for r in reqs:
        rej_count = len(sb.table('withdrawals').select('id').eq('user_id', r['user_id']).eq('status', 'rejected').execute().data or [])
        r['rejection_count'] = rej_count

    return render_template('admin/withdraw.html', requests=reqs)

@app.route('/admin/withdraw/<int:withdraw_id>/<action>', methods=['POST'])
@admin_required
def admin_handle_withdraw(withdraw_id, action):
    sb = get_supabase()
    req = sb.table('withdrawals').select('*').eq('id', withdraw_id).single().execute().data
    if not req or req['status'] != 'pending':
        flash("অবৈধ রিকোয়েস্ট!", "danger")
        return redirect(url_for('admin_withdraw'))

    if action == 'approve':
        sb.table('withdrawals').update({'status': 'approved'}).eq('id', withdraw_id).execute()
        flash("উইথড্রয়াল অ্যাপ্রুভ হয়েছে!", "success")
    elif action == 'reject':
        # রিজেক্ট হলে ব্যালেন্স ইউজারের একাউন্টে রিফান্ড হবে
        user = sb.table('users').select('balance').eq('id', req['user_id']).single().execute().data
        sb.table('users').update({'balance': float(user['balance']) + float(req['amount'])}).eq('id', req['user_id']).execute()
        sb.table('withdrawals').update({'status': 'rejected'}).eq('id', withdraw_id).execute()
        flash("উইথড্রয়াল রিজেক্ট করা হয়েছে এবং টাকা ফেরত দেওয়া হয়েছে।", "warning")

    return redirect(url_for('admin_withdraw'))

@app.route('/admin/imgbb', methods=['GET', 'POST'])
@admin_required
def admin_imgbb():
    sb = get_supabase()
    if request.method == 'POST':
        key = request.form.get('api_key', '').strip()
        if key:
            sb.table('imgbb_keys').insert({'api_key': key}).execute()
            flash("ImgBB Key সফলভাবে যুক্ত হয়েছে!", "success")
        return redirect(url_for('admin_imgbb'))

    keys = sb.table('imgbb_keys').select('*').order('id', desc=True).execute().data or []
    return render_template('admin/imgbb.html', keys=keys)

@app.route('/admin/imgbb/delete/<int:key_id>', methods=['POST'])
@admin_required
def admin_imgbb_delete(key_id):
    sb = get_supabase()
    sb.table('imgbb_keys').delete().eq('id', key_id).execute()
    flash("API Key ডিলিট করা হয়েছে!", "success")
    return redirect(url_for('admin_imgbb'))

# ==========================================================
# ADMIN AUTO PAYMENT PROOF IMAGE GENERATOR
# ==========================================================
@app.route('/admin/pay')
@admin_required
def admin_pay_generator():
    return render_template('admin/pay.html')
    
@app.route('/admin/task', methods=['GET', 'POST'])
@admin_required
def admin_task():
    sb = get_supabase()
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        amount = float(request.form.get('amount', 0))
        link = request.form.get('link', '').strip()

        sb.table('tasks').insert({
            'title': title,
            'description': description,
            'amount': amount,
            'link': link
        }).execute()
        flash("নতুন টাস্ক তৈরি হয়েছে!", "success")
        return redirect(url_for('admin_task'))

    all_tasks = sb.table('tasks').select('*').order('id', desc=True).execute().data or []
    return render_template('admin/tasks.html', tasks=all_tasks)

@app.route('/admin/submit')
@admin_required
def admin_submissions():
    sb = get_supabase()
    pending = sb.table('submissions').select('*, tasks(title, amount), users(email)').eq('status', 'pending').order('id', desc=True).execute().data or []
    return render_template('admin/submissions.html', submissions=pending)

# ==========================================================
# Bulk Review Engine (Max 30, Auto 3 Reject, Rest Approve)
# ==========================================================
@app.route('/admin/submit/bulk', methods=['POST'])
@admin_required
def admin_bulk_submissions():
    sb = get_supabase()
    pending = sb.table('submissions').select('*, tasks(amount)').eq('status', 'pending').limit(30).execute().data or []
    
    if not pending:
        flash("কোনো পেন্ডিং টাস্ক নেই।", "info")
        return redirect(url_for('admin_submissions'))

    # সর্বোচ্চ ৩টি র‍্যান্ডম রিজেক্ট নির্বাচন
    reject_count = min(3, len(pending))
    rejected_items = random.sample(pending, reject_count)
    rejected_ids = [item['id'] for item in rejected_items]

    approved_count = 0
    for item in pending:
        if item['id'] in rejected_ids:
            # Reject
            sb.table('submissions').update({'status': 'rejected'}).eq('id', item['id']).execute()
        else:
            # Approve + ইউজারের ব্যালেন্সে টাকা যুক্ত করা
            sb.table('submissions').update({'status': 'approved'}).eq('id', item['id']).execute()
            user = sb.table('users').select('balance').eq('id', item['user_id']).single().execute().data
            reward = float(item['tasks']['amount']) if item.get('tasks') else 0.0
            sb.table('users').update({'balance': float(user['balance']) + reward}).eq('id', item['user_id']).execute()
            approved_count += 1

    flash(f"বাল্ক রিভিউ শেষ! {approved_count}টি অ্যাপ্রুভ এবং {reject_count}টি র‍্যান্ডমলি রিজেক্ট হয়েছে।", "success")
    return redirect(url_for('admin_submissions'))

import re

# --- YouTube Video ID Extractor Helper ---
def extract_yt_id(url):
    regex = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})'
    match = re.search(regex, url)
    return match.group(1) if match else None

# ==========================================================
# YOUTUBE EARN CONTROLLER (SEEN VIDEOS 100% AUTO-HIDDEN)
# ==========================================================
@app.route('/yt')
@login_required
def yt_videos():
    sb = get_supabase()
    user_id = session['user_id']
    page = int(request.args.get('page', 1))
    limit = 20
    offset = (page - 1) * limit

    # ১. এই ইউজার যেসব ভিডিও ইতিমধ্যে দেখে ফেলেছে সেগুলোর আইডি নেওয়া
    claimed_rows = sb.table('yt_claims').select('video_id').eq('user_id', user_id).execute().data or []
    claimed_ids = set(c['video_id'] for c in claimed_rows)

    # ২. সিস্টেমের সকল সক্রিয় ভিডিও আনা
    all_videos = sb.table('yt_videos').select('*').eq('is_active', True).order('id', desc=True).execute().data or []

    # ৩. অলরেডি দেখা ভিডিওগুলো তালিকা থেকে ১০০% হাইড করা
    available_videos = [v for v in all_videos if v['id'] not in claimed_ids]

    # ৪. শুধুমাত্র না-দেখা ভিডিওগুলোর ওপর ২০টি করে পেজিনেশন করা
    total_available = len(available_videos)
    paginated_videos = available_videos[offset : offset + limit]
    has_next = (offset + limit) < total_available

    return render_template(
        'yt.html', 
        videos=paginated_videos, 
        page=page, 
        has_next=has_next,
        total_available=total_available
    )

@app.route('/yt/claim', methods=['POST'])
@login_required
def yt_claim():
    sb = get_supabase()
    user_id = session['user_id']
    data = request.get_json() or {}
    video_id = data.get('video_id')

    if not video_id:
        return jsonify({'success': False, 'message': 'অবৈধ ভিডিও আইডি!'})

    # ১. কঠোর চেকিং: ১ বারের বেশি দ্বিতীয়বার দেখা সম্পূর্ণ ব্লক
    already_seen = sb.table('yt_claims').select('id').eq('user_id', user_id).eq('video_id', video_id).execute().data
    if already_seen:
        return jsonify({
            'success': False, 
            'message': 'আপনি এই ভিডিওটি ইতিমধ্যে দেখে ফেলেছেন! এটি দ্বিতীয়বার দেখা যাবে না।'
        })

    # ২. ভিডিওর সত্যতা যাচাই
    video = sb.table('yt_videos').select('*').eq('id', video_id).single().execute().data
    if not video or not video.get('is_active'):
        return jsonify({'success': False, 'message': 'ভিডিওটি পাওয়া যায়নি বা নিষ্ক্রিয় রয়েছে!'})

    amount = float(video['amount'])

    # ৩. অ্যাকাউন্টে টাকা যোগ করা
    user = sb.table('users').select('balance').eq('id', user_id).single().execute().data
    new_balance = float(user['balance']) + amount

    sb.table('users').update({'balance': new_balance}).eq('id', user_id).execute()

    # ৪. দেখা সম্পন্ন হিসেবে রেকর্ড (যাতে পেজ থেকে চিরতরে হাইড হয়ে যায়)
    sb.table('yt_claims').insert({
        'video_id': video_id,
        'user_id': user_id,
        'amount_earned': amount
    }).execute()

    return jsonify({
        'success': True,
        'message': f'🎉 অভিনন্দন! আপনি ৳{amount:.2f} সফলভাবে ক্লেইম করেছেন!',
        'new_balance': new_balance
    })
    
# ==========================================================
# ADMIN YOUTUBE CONTROLLER
# ==========================================================
@app.route('/admin/yt', methods=['GET', 'POST'])
@admin_required
def admin_yt():
    sb = get_supabase()
    if request.method == 'POST':
        raw_url = request.form.get('video_url', '').strip()
        title = request.form.get('title', '').strip() or 'YouTube Video'
        try:
            amount = float(request.form.get('amount', 1.00))
        except ValueError:
            amount = 1.00

        vid = extract_yt_id(raw_url)
        if not vid:
            flash("ইউটিউব লিংক সঠিক নয়! (যেমন: https://youtu.be/... বা watch?v=... দিন)", "danger")
            return redirect(url_for('admin_yt'))

        sb.table('yt_videos').insert({
            'video_url': raw_url,
            'video_id': vid,
            'title': title,
            'amount': amount
        }).execute()

        flash("নতুন YouTube ভিডিও সফলভাবে যুক্ত হয়েছে!", "success")
        return redirect(url_for('admin_yt'))

    videos = sb.table('yt_videos').select('*').order('id', desc=True).execute().data or []
    return render_template('admin/yt.html', videos=videos)

@app.route('/admin/yt/delete/<int:video_id>', methods=['POST'])
@admin_required
def admin_yt_delete(video_id):
    sb = get_supabase()
    sb.table('yt_videos').delete().eq('id', video_id).execute()
    flash("ভিডিওটি সফলভাবে ডিলিট করা হয়েছে!", "success")
    return redirect(url_for('admin_yt'))

# ==========================================================
# ADVERTISER & PROMOTION LANDING CONTROLLER
# ==========================================================
@app.route('/promote', methods=['GET', 'POST'])
def promote():
    sb = get_supabase()
    user = None
    is_logged_in = 'user_id' in session

    if is_logged_in:
        user = sb.table('users').select('*').eq('id', session['user_id']).single().execute().data

    if request.method == 'POST':
        # শর্ত: লগইন ছাড়া ফর্ম সাবমিট হবে না
        if not is_logged_in:
            flash("প্রমোশন ফর্ম জমা দিতে অনুগ্রহ করে প্রথমে লগইন করুন!", "danger")
            return redirect(url_for('index'))

        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        service_type = request.form.get('service_type', 'General').strip()
        requirement = request.form.get('requirement', '').strip()

        if not name or not email or not phone or not requirement:
            flash("ফর্মের সবকটি তথ্য সঠিকভাবে পূরণ করুন!", "danger")
            return redirect(url_for('promote'))

        sb.table('promotions').insert({
            'user_id': session['user_id'],
            'name': name,
            'email': email,
            'phone': phone,
            'service_type': service_type,
            'requirement': requirement
        }).execute()

        flash("🎉 আপনার রিকোয়েস্ট সফলভাবে জমা হয়েছে! আমাদের টিম দ্রুতই আপনার সাথে যোগাযোগ করবে।", "success")
        return redirect(url_for('promote'))

    return render_template('promote.html', is_logged_in=is_logged_in, user=user)

# ==========================================================
# PWA MANIFEST, SERVICE WORKER & /install CONTROLLER
# ==========================================================
@app.route('/manifest.json')
def pwa_manifest():
    manifest_data = {
        "name": "MicroEarnX - Micro Task & Earn",
        "short_name": "MicroEarnX",
        "start_url": "/app",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#E11D48",
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "https://i.ibb.co/1JbqCDHq/Add-Text-10-10-03-15-45.jpg",
                "sizes": "192x192",
                "type": "image/jpeg",
                "purpose": "any maskable"
            },
            {
                "src": "https://i.ibb.co/1JbqCDHq/Add-Text-10-10-03-15-45.jpg",
                "sizes": "512x512",
                "type": "image/jpeg",
                "purpose": "any maskable"
            }
        ]
    }
    return jsonify(manifest_data)


# ==========================================================
# SINGLE TASK SUBMISSION APPROVE & REJECT CONTROLLER
# ==========================================================
@app.route('/admin/submit/<int:sub_id>/approve', methods=['POST'])
@admin_required
def admin_single_approve_submission(sub_id):
    sb = get_supabase()
    # সাবমিশন ও টাস্কের অ্যামাউন্ট বের করা
    sub = sb.table('submissions').select('*, tasks(amount)').eq('id', sub_id).single().execute().data
    
    if not sub or sub.get('status') != 'pending':
        flash("অবৈধ বা ইতিমধ্যে সম্পন্ন হওয়া সাবমিশন!", "danger")
        return redirect(url_for('admin_submissions'))

    # ১. সাবমিশন স্ট্যাটাস 'approved' করা
    sb.table('submissions').update({'status': 'approved'}).eq('id', sub_id).execute()

    # ২. ইউজারের একাউন্টে টাকা যোগ করা
    user = sb.table('users').select('balance').eq('id', sub['user_id']).single().execute().data
    task_amount = float(sub['tasks']['amount']) if sub.get('tasks') else 0.0
    new_balance = float(user['balance']) + task_amount

    sb.table('users').update({'balance': new_balance}).eq('id', sub['user_id']).execute()

    flash(f"টাস্কটি সফলভাবে অ্যাপ্রুভ করা হয়েছে এবং ইউজারের অ্যাকাউন্টে ৳{task_amount:.2f} যোগ হয়েছে!", "success")
    return redirect(url_for('admin_submissions'))


@app.route('/admin/submit/<int:sub_id>/reject', methods=['POST'])
@admin_required
def admin_single_reject_submission(sub_id):
    sb = get_supabase()
    sub = sb.table('submissions').select('id, status').eq('id', sub_id).single().execute().data
    
    if not sub or sub.get('status') != 'pending':
        flash("অবৈধ বা ইতিমধ্যে সম্পন্ন হওয়া সাবমিশন!", "danger")
        return redirect(url_for('admin_submissions'))

    # সাবমিশন স্ট্যাটাস 'rejected' করা
    sb.table('submissions').update({'status': 'rejected'}).eq('id', sub_id).execute()

    flash("টাস্কটি রিজেক্ট করা হয়েছে!", "warning")
    return redirect(url_for('admin_submissions'))
    
@app.route('/sw.js')
def pwa_sw():
    sw_code = """
    self.addEventListener('install', (e) => { self.skipWaiting(); });
    self.addEventListener('activate', (e) => { e.waitUntil(clients.claim()); });
    self.addEventListener('fetch', (e) => {
        e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    });
    """
    return app.response_class(sw_code, mimetype='application/javascript')

@app.route('/install')
def install_app_page():
    return render_template('install.html')



@app.route('/sw.js')
def serve_sw():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return send_from_directory(root_dir, 'sw.js', mimetype='application/javascript')
    
# ==========================================================
# Local Development Execution
# ==========================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
