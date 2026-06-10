from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timezone, timedelta
import os
import uuid
import secrets
import time
import json
import re
import io
import base64
import binascii
import hashlib
import html as html_lib
import hmac
import struct
import smtplib
import urllib.parse
import urllib.request
from functools import wraps
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image
import threading

try:
    import qrcode
    import qrcode.image.svg
except ImportError:
    qrcode = None

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '0').strip() == '1'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=int(os.environ.get('SESSION_LIFETIME_HOURS', '8') or 8))
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()
app.config['GOOGLE_DISCOVERY_AUTH_URL'] = 'https://accounts.google.com/o/oauth2/v2/auth'
app.config['GOOGLE_TOKEN_URL'] = 'https://oauth2.googleapis.com/token'
app.config['GOOGLE_USERINFO_URL'] = 'https://openidconnect.googleapis.com/v1/userinfo'
app.config['SMTP_HOST'] = os.environ.get('SMTP_HOST', '').strip()
app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', '587') or 587)
app.config['SMTP_USERNAME'] = os.environ.get('SMTP_USERNAME', '').strip()
app.config['SMTP_PASSWORD'] = os.environ.get('SMTP_PASSWORD', '').strip()
app.config['SMTP_FROM'] = os.environ.get('SMTP_FROM', app.config['SMTP_USERNAME']).strip()
app.config['SMTP_FROM_NAME'] = os.environ.get('SMTP_FROM_NAME', 'UI Battle Arena').strip()
app.config['SMTP_USE_TLS'] = os.environ.get('SMTP_USE_TLS', '1').strip() != '0'
app.config['MAILJET_API_KEY'] = os.environ.get('MAILJET_API_KEY', app.config['SMTP_USERNAME']).strip()
app.config['MAILJET_SECRET_KEY'] = os.environ.get('MAILJET_SECRET_KEY', app.config['SMTP_PASSWORD']).strip()
app.config['MAILJET_API_URL'] = os.environ.get('MAILJET_API_URL', 'https://api.mailjet.com/v3.1/send').strip()

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_SITE_MEDIA_EXTENSIONS = ALLOWED_EXTENSIONS | {'webp', 'mp4', 'webm', 'mov'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

from models import (
    db, User, Challenge, Room, Submission, ChatMessage,
    Tournament, TournamentParticipant, TournamentMatch, MatchResult, AdminAction, AwardCard, RoomAccess,
    Competition, CompetitionWave, CompetitionAdminAssignment, AdminTask, DisputeCase
)
from moderation_terms import (
    BAD_LANGUAGE_TERMS,
    SENSITIVE_LANGUAGE_PATTERNS,
    SENSITIVE_LANGUAGE_PHRASES,
    SENSITIVE_LANGUAGE_TERMS
)
from auth import login_required, admin_required, get_current_user

db.init_app(app)

configured_socket_origins = [
    origin.strip()
    for origin in os.environ.get('SOCKETIO_ALLOWED_ORIGINS', '').split(',')
    if origin.strip()
]
# The browser client uses long-polling, so threading avoids Eventlet warnings on Windows/Python 3.14.
socketio = SocketIO(
    app,
    cors_allowed_origins=configured_socket_origins or None,
    async_mode='threading'
)


@app.after_request
def add_media_permission_headers(response):
    response.headers.setdefault('Permissions-Policy', 'camera=(self), microphone=(self)')
    return response

room_timers = {}
room_preview_data = {}
connected_users = {}
room_spectators = {}
room_typing_users = {}
room_typing_expiry = {}
RATE_LIMITS = {}
PROFILE_STORE = os.path.join(app.root_path, 'profile_store.json')
LEADERBOARD_STREAK_TARGET = 5
schema_upgrades_ready = False
CARD_TEMPLATES = [
    {'id': 'champion', 'name': 'Champion Crest', 'icon': 'fa-trophy', 'layout': 'classic', 'shape': 'rounded', 'primary': '#f59e0b', 'secondary': '#111827'},
    {'id': 'loyalty', 'name': 'Loyalty Star', 'icon': 'fa-star', 'layout': 'badge', 'shape': 'ticket', 'primary': '#22d3ee', 'secondary': '#0f172a'},
    {'id': 'consistency', 'name': 'Consistency Ring', 'icon': 'fa-repeat', 'layout': 'split', 'shape': 'rounded', 'primary': '#10b981', 'secondary': '#1e293b'},
    {'id': 'focus', 'name': 'Focus Lens', 'icon': 'fa-bullseye', 'layout': 'classic', 'shape': 'hex', 'primary': '#8b5cf6', 'secondary': '#f8fafc'},
    {'id': 'mentor', 'name': 'Mentor Flame', 'icon': 'fa-fire', 'layout': 'diagonal', 'shape': 'rounded', 'primary': '#ef4444', 'secondary': '#111827'},
    {'id': 'creative', 'name': 'Creative Spark', 'icon': 'fa-wand-magic-sparkles', 'layout': 'badge', 'shape': 'wave', 'primary': '#ec4899', 'secondary': '#fef3c7'},
    {'id': 'precision', 'name': 'Precision Grid', 'icon': 'fa-crosshairs', 'layout': 'split', 'shape': 'sharp', 'primary': '#3b82f6', 'secondary': '#e0f2fe'},
    {'id': 'teamwork', 'name': 'Team Builder', 'icon': 'fa-users', 'layout': 'classic', 'shape': 'ticket', 'primary': '#14b8a6', 'secondary': '#042f2e'},
    {'id': 'resilience', 'name': 'Resilience Shield', 'icon': 'fa-shield-halved', 'layout': 'diagonal', 'shape': 'hex', 'primary': '#6366f1', 'secondary': '#eef2ff'},
    {'id': 'innovation', 'name': 'Innovation Orbit', 'icon': 'fa-atom', 'layout': 'badge', 'shape': 'wave', 'primary': '#06b6d4', 'secondary': '#164e63'},
    {'id': 'leadership', 'name': 'Leadership Seal', 'icon': 'fa-crown', 'layout': 'classic', 'shape': 'rounded', 'primary': '#d97706', 'secondary': '#fff7ed'},
    {'id': 'growth', 'name': 'Growth Path', 'icon': 'fa-seedling', 'layout': 'split', 'shape': 'sharp', 'primary': '#84cc16', 'secondary': '#1a2e05'}
]
AVATAR_TEMPLATES = [
    {'id': 'spark', 'name': 'Spark', 'icon': 'fa-bolt', 'shape': 'circle'},
    {'id': 'pilot', 'name': 'Pilot', 'icon': 'fa-rocket', 'shape': 'shield'},
    {'id': 'artist', 'name': 'Artist', 'icon': 'fa-palette', 'shape': 'blob'},
    {'id': 'coder', 'name': 'Coder', 'icon': 'fa-code', 'shape': 'square'},
    {'id': 'strategist', 'name': 'Strategist', 'icon': 'fa-chess-knight', 'shape': 'hex'},
    {'id': 'builder', 'name': 'Builder', 'icon': 'fa-hammer', 'shape': 'circle'},
    {'id': 'guardian', 'name': 'Guardian', 'icon': 'fa-shield-heart', 'shape': 'shield'},
    {'id': 'navigator', 'name': 'Navigator', 'icon': 'fa-compass', 'shape': 'blob'},
    {'id': 'analyst', 'name': 'Analyst', 'icon': 'fa-chart-line', 'shape': 'square'},
    {'id': 'maker', 'name': 'Maker', 'icon': 'fa-cubes', 'shape': 'hex'},
    {'id': 'visionary', 'name': 'Visionary', 'icon': 'fa-eye', 'shape': 'circle'},
    {'id': 'anchor', 'name': 'Anchor', 'icon': 'fa-anchor', 'shape': 'shield'},
    {'id': 'storm', 'name': 'Storm', 'icon': 'fa-cloud-bolt', 'shape': 'blob'},
    {'id': 'logic', 'name': 'Logic', 'icon': 'fa-brain', 'shape': 'square'},
    {'id': 'signal', 'name': 'Signal', 'icon': 'fa-signal', 'shape': 'hex'},
    {'id': 'craft', 'name': 'Craft', 'icon': 'fa-gem', 'shape': 'circle'}
]
LEET_TRANSLATION = str.maketrans({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a', '$': 's', '*': '', '!': 'i', '+': 't'})

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_site_media_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_SITE_MEDIA_EXTENSIONS

def generate_room_code():
    import random
    import string
    return '#' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

def clean_hex_color(value, fallback='#22d3ee'):
    value = (value or '').strip()
    return value if re.fullmatch(r'#[0-9a-fA-F]{6}', value) else fallback

def valid_email(value):
    value = (value or '').strip().lower()
    if not value:
        return ''
    return value if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value) else None


def configured_admin_email():
    return (
        valid_email(os.environ.get('ADMIN_EMAIL'))
        or valid_email(app.config.get('SMTP_FROM'))
        or valid_email(app.config.get('SMTP_USERNAME'))
        or ''
    )


def admin_login_uses_email(user, identifier):
    if not user or user.role != 'admin':
        return True
    admin_email = (user.email or configured_admin_email() or '').lower()
    supplied = (identifier or '').strip().lower()
    if not admin_email:
        return bool(valid_email(supplied))
    return bool(admin_email and supplied == admin_email)


def find_login_user(identifier):
    supplied = (identifier or '').strip()
    normalized_email = valid_email(supplied)
    user = User.query.filter(
        (User.username == supplied) | (User.email == supplied.lower())
    ).first()
    if user or not normalized_email:
        return user
    configured_email = configured_admin_email()
    if configured_email and normalized_email != configured_email:
        return None
    admin = User.query.filter_by(role='admin').first()
    if admin and (not admin.email or admin.email == configured_email):
        return admin
    return None


def bind_admin_login_email(user, identifier):
    supplied_email = valid_email(identifier)
    if not user or user.role != 'admin' or not supplied_email:
        return False
    if user.email == supplied_email:
        return False
    if user.email and user.email != configured_admin_email():
        return False
    user.email = supplied_email
    profiles, profile = get_profile_record(user.id)
    profile['email_verified'] = False
    profile.pop('email_verification_hash', None)
    profile.pop('email_verification_expires_at', None)
    db.session.commit()
    save_profile_store(profiles)
    return True

def password_is_strong(password):
    password = password or ''
    return (
        len(password) >= 12
        and re.search(r'[A-Z]', password)
        and re.search(r'[a-z]', password)
        and re.search(r'\d', password)
    )


def get_csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token


def csrf_failed_response():
    if request.is_json or request.accept_mimetypes.best == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False, 'error': 'Security token expired. Refresh the page and try again.'}), 400
    return redirect(url_for('login_page'))


def verify_csrf_request():
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return None
    expected = session.get('csrf_token')
    supplied = (
        request.headers.get('X-CSRFToken')
        or request.headers.get('X-CSRF-Token')
        or (request.form.get('csrf_token') if request.form else '')
    )
    if not expected or not supplied or not secrets.compare_digest(str(expected), str(supplied)):
        return csrf_failed_response()
    return None


def client_rate_identity():
    return request.headers.get('X-Forwarded-For', request.remote_addr or 'local').split(',')[0].strip()


def rate_limited(scope, identifier=None, limit=5, window_seconds=300):
    now = time.time()
    key = (scope, identifier or client_rate_identity())
    cutoff = now - window_seconds
    RATE_LIMITS[key] = [stamp for stamp in RATE_LIMITS.get(key, []) if stamp >= cutoff]
    if len(RATE_LIMITS[key]) >= limit:
        return True
    RATE_LIMITS[key].append(now)
    if len(RATE_LIMITS) > 2000:
        for old_key, stamps in list(RATE_LIMITS.items()):
            RATE_LIMITS[old_key] = [stamp for stamp in stamps if stamp >= cutoff]
            if not RATE_LIMITS[old_key]:
                RATE_LIMITS.pop(old_key, None)
    return False


def rate_limit_response(message='Too many attempts. Wait a few minutes and try again.'):
    return jsonify({'success': False, 'error': message}), 429


def socket_current_user():
    user_id = session.get('user_id')
    return db.session.get(User, user_id) if user_id else None


def role_for_user_in_room(user, room):
    if not user or not room:
        return None
    if user.role == 'admin':
        return 'admin'
    if room.player1_id == user.id:
        return 'player1'
    if room.player2_id == user.id:
        return 'player2'
    return 'spectator'


def get_room_access(room, user):
    if not room or not user:
        return None
    return RoomAccess.query.filter_by(room_id=room.id, user_id=user.id).first()


def record_room_access(room, user, role, status='active', granted_by=None, reason=None):
    if not room or not user or user.role == 'admin':
        return None
    access = get_room_access(room, user)
    if not access:
        access = RoomAccess(room_id=room.id, user_id=user.id)
        db.session.add(access)
    access.role = role
    access.status = status
    access.granted_by = granted_by
    access.reason = (reason or '')[:240] or access.reason
    return access


def room_access_is_suspended(room, user):
    if not room or not user or user.role == 'admin':
        return False
    access = get_room_access(room, user)
    if access and access.status in {'suspended', 'blocked'}:
        return True
    return DisputeCase.query.filter(
        DisputeCase.room_id == room.id,
        DisputeCase.player_id == user.id,
        ((DisputeCase.type == 'disqualification') | (DisputeCase.status == 'disqualified'))
    ).first() is not None


def room_access_redirect_or_error(room, user, requested_role, json_response=False):
    if not room or not user or user.role == 'admin':
        return None
    if room_access_is_suspended(room, user):
        message = 'You were removed from this match by an admin.'
        return (jsonify({'success': False, 'error': message}), 403) if json_response else redirect(url_for('dashboard'))
    access = get_room_access(room, user)
    is_player = is_room_player(user, room)
    if requested_role == 'spectator' and (is_player or (access and access.role == 'player' and access.status == 'active')):
        return (jsonify({'success': True, 'room_id': room.id, 'role': 'player', 'redirect': url_for('arena', room_id=room.id)}), 200) if json_response else redirect(url_for('arena', room_id=room.id))
    if requested_role == 'player' and access and access.role == 'spectator' and access.status == 'active' and not is_player:
        message = 'You are locked as a spectator for this match. Ask an admin to grant player access.'
        return (jsonify({'success': False, 'error': message}), 403) if json_response else redirect(url_for('arena', room_id=room.id))
    return None


def socket_room_context(data):
    try:
        room_id = int((data or {}).get('room_id'))
    except (TypeError, ValueError):
        return None, None, None
    user = socket_current_user()
    room = db.session.get(Room, room_id)
    if not user or not room:
        return None, None, None
    return user, room, role_for_user_in_room(user, room)


def is_room_player(user, room):
    return bool(user and room and user.id in {room.player1_id, room.player2_id})

def smtp_configured():
    return bool(app.config['SMTP_HOST'] and app.config['SMTP_FROM'])


def mailjet_api_configured():
    return bool(
        app.config.get('MAILJET_API_KEY')
        and app.config.get('MAILJET_SECRET_KEY')
        and valid_email(app.config.get('SMTP_FROM'))
    )


def email_configured():
    return mailjet_api_configured() or smtp_configured()


def smtp_configuration_error():
    missing = []
    if not valid_email(app.config['SMTP_FROM']):
        missing.append('SMTP_FROM')
    if mailjet_api_configured():
        return ''
    if not app.config.get('MAILJET_API_KEY') and not app.config['SMTP_HOST']:
        missing.append('MAILJET_API_KEY or SMTP_HOST')
    if app.config.get('MAILJET_API_KEY') and not app.config.get('MAILJET_SECRET_KEY'):
        missing.append('MAILJET_SECRET_KEY')
    if app.config['SMTP_HOST'] and app.config['SMTP_USERNAME'] and not app.config['SMTP_PASSWORD']:
        missing.append('SMTP_PASSWORD')
    if not missing and not app.config['SMTP_HOST']:
        missing.append('SMTP_HOST')
    if missing:
        return 'Email sending is not configured. Missing: ' + ', '.join(missing)
    return ''


def email_footer_text():
    sender = valid_email(app.config.get('SMTP_FROM')) or 'the UI Battle Arena administrator'
    return (
        '\n\n--\n'
        'UI Battle Arena\n'
        f'Sent by {app.config.get("SMTP_FROM_NAME") or "UI Battle Arena"} from {sender}.\n'
        'This message was sent because you have a UI Battle Arena account, match invite, or admin notification. '
        'If you did not expect this email, contact the arena administrator.'
    )


def build_email_html(subject, body):
    safe_subject = html_lib.escape((subject or 'UI Battle Arena').strip())
    paragraphs = [
        html_lib.escape(part.strip()).replace('\n', '<br>')
        for part in re.split(r'\n\s*\n', (body or '').strip())
        if part.strip()
    ]
    content = ''.join(f'<p>{paragraph}</p>' for paragraph in paragraphs)
    brand = html_lib.escape(app.config.get('SMTP_FROM_NAME') or 'UI Battle Arena')
    sender = html_lib.escape(valid_email(app.config.get('SMTP_FROM')) or '')
    return f'''<!doctype html>
<html>
<body style="margin:0;background:#f6f8fb;color:#172033;font-family:Arial,Helvetica,sans-serif;">
  <div style="display:none;overflow:hidden;line-height:1px;opacity:0;max-height:0;max-width:0;">{safe_subject}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fb;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
          <tr>
            <td style="background:#111827;color:#ffffff;padding:20px 24px;">
              <div style="font-size:18px;font-weight:700;letter-spacing:.2px;">{brand}</div>
              <div style="font-size:13px;color:#cbd5e1;margin-top:4px;">Official arena notification</div>
            </td>
          </tr>
          <tr>
            <td style="padding:24px;font-size:15px;line-height:1.58;color:#172033;">
              <h1 style="font-size:20px;line-height:1.3;margin:0 0 16px;color:#111827;">{safe_subject}</h1>
              {content}
            </td>
          </tr>
          <tr>
            <td style="padding:16px 24px;background:#f9fafb;border-top:1px solid #e5e7eb;font-size:12px;line-height:1.5;color:#64748b;">
              Sent by {brand}{f' from {sender}' if sender else ''}. This message was sent because you have a UI Battle Arena account, match invite, or admin notification.
              If you did not expect this email, contact the arena administrator.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''


def prepare_email_content(subject, body, html_body=None):
    text_body = (body or '').strip()
    if email_footer_text().strip() not in text_body:
        text_body += email_footer_text()
    return text_body, html_body or build_email_html(subject, text_body)


def send_email_via_mailjet_api(to_email, subject, body, html_body=None):
    api_key = app.config.get('MAILJET_API_KEY') or app.config.get('SMTP_USERNAME')
    secret_key = app.config.get('MAILJET_SECRET_KEY') or app.config.get('SMTP_PASSWORD')
    from_email = valid_email(app.config['SMTP_FROM'])
    if not api_key or not secret_key or not to_email or not from_email:
        return False
    text_body, html_body = prepare_email_content(subject, body, html_body)
    payload = {
        'Messages': [{
            'From': {
                'Email': from_email,
                'Name': app.config.get('SMTP_FROM_NAME') or 'UI Battle Arena'
            },
            'To': [{'Email': to_email}],
            'ReplyTo': {
                'Email': from_email,
                'Name': app.config.get('SMTP_FROM_NAME') or 'UI Battle Arena'
            },
            'Subject': subject[:160],
            'TextPart': text_body,
            'HTMLPart': html_body,
            'Headers': {
                'List-Unsubscribe': f'<mailto:{from_email}>',
                'X-Entity-Ref-ID': secrets.token_hex(12)
            }
        }]
    }
    data = json.dumps(payload).encode('utf-8')
    request_obj = urllib.request.Request(
        app.config.get('MAILJET_API_URL') or 'https://api.mailjet.com/v3.1/send',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    auth_token = base64.b64encode(f'{api_key}:{secret_key}'.encode('utf-8')).decode('ascii')
    request_obj.add_header('Authorization', f'Basic {auth_token}')
    try:
        with urllib.request.urlopen(request_obj, timeout=10) as response:
            response_body = response.read().decode('utf-8', errors='replace')
            success = 200 <= response.status < 300
            if not success:
                app.logger.error('Mailjet API send failed with status %s: %s', response.status, response_body[:500])
            return success
    except urllib.error.HTTPError as error:
        response_body = error.read().decode('utf-8', errors='replace')
        app.logger.error('Mailjet API send failed with status %s: %s', error.code, response_body[:500])
        return False
    except Exception:
        app.logger.exception('Mailjet API send failed')
        return False


def send_email(to_email, subject, body, html_body=None):
    to_email = valid_email(to_email)
    from_email = valid_email(app.config['SMTP_FROM'])
    if not to_email or not from_email or not email_configured():
        return False
    if mailjet_api_configured():
        return send_email_via_mailjet_api(to_email, subject, body, html_body)
    text_body, html_body = prepare_email_content(subject, body, html_body)
    message = EmailMessage()
    message['Subject'] = subject[:160]
    message['From'] = formataddr((app.config.get('SMTP_FROM_NAME') or 'UI Battle Arena', from_email))
    message['To'] = to_email
    message['Reply-To'] = from_email
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid(domain=from_email.split('@')[-1])
    message['X-Mailer'] = 'UI Battle Arena'
    message['List-Unsubscribe'] = f'<mailto:{from_email}>'
    message.set_content(text_body + '\n')
    message.add_alternative(html_body, subtype='html')
    with smtplib.SMTP(app.config['SMTP_HOST'], app.config['SMTP_PORT'], timeout=10) as smtp:
        if app.config['SMTP_USE_TLS']:
            smtp.starttls()
        if app.config['SMTP_USERNAME'] and app.config['SMTP_PASSWORD']:
            smtp.login(app.config['SMTP_USERNAME'], app.config['SMTP_PASSWORD'])
        smtp.send_message(message)
    return True

def default_certificate_template():
    return {
        'organization': 'Ministry of Education',
        'department': 'State Department of Technical Training',
        'association': 'Kenya Association of Technical Training Institutions',
        'certificate_title': 'Certificate of Merit',
        'award_line': 'This certificate is awarded to',
        'recipient_name': 'Outstanding Player',
        'competition_name': 'UI Battle Arena Competition',
        'category': 'Web Design Challenge',
        'held_at': 'UI Battle Arena',
        'award_date': datetime.now().strftime('%d %b %Y'),
        'regards_text': 'In recognition of excellent participation, performance, discipline, and official contribution.',
        'sponsor_name': 'Official Sponsors',
        'accent_color': '#b91c1c',
        'seal_text': 'Award',
        'sponsor_logos': [],
        'officials': [
            {'name': 'Chairperson', 'title': 'Competition Chairperson', 'signature': ''},
            {'name': 'Secretary', 'title': 'Competition Secretary', 'signature': ''}
        ]
    }

def normalize_certificate_settings(data=None, fallback=None):
    source = {}
    source.update(default_certificate_template())
    if isinstance(fallback, dict):
        source.update(fallback)
    if isinstance(data, dict):
        source.update(data)

    officials = []
    for item in (source.get('officials') if isinstance(source.get('officials'), list) else [])[:6]:
        if not isinstance(item, dict):
            continue
        officials.append({
            'name': str(item.get('name') or '')[:120],
            'title': str(item.get('title') or '')[:120],
            'signature': str(item.get('signature') or '')[:500000]
        })
    if not officials:
        officials = default_certificate_template()['officials']

    return {
        'organization': str(source.get('organization') or '')[:160],
        'department': str(source.get('department') or '')[:160],
        'association': str(source.get('association') or '')[:180],
        'certificate_title': str(source.get('certificate_title') or 'Certificate of Merit')[:140],
        'award_line': str(source.get('award_line') or 'This certificate is awarded to')[:180],
        'recipient_name': str(source.get('recipient_name') or 'Outstanding Player')[:140],
        'competition_name': str(source.get('competition_name') or '')[:180],
        'category': str(source.get('category') or '')[:160],
        'held_at': str(source.get('held_at') or '')[:160],
        'award_date': str(source.get('award_date') or '')[:80],
        'regards_text': str(source.get('regards_text') or '')[:800],
        'sponsor_name': str(source.get('sponsor_name') or '')[:160],
        'accent_color': clean_hex_color(source.get('accent_color'), '#b91c1c'),
        'seal_text': str(source.get('seal_text') or 'Award')[:40],
        'sponsor_logos': [
            str(item)[:500000]
            for item in (source.get('sponsor_logos') if isinstance(source.get('sponsor_logos'), list) else [])
            if item
        ][:24],
        'officials': officials
    }

def get_card_template(template_id):
    return next((item for item in CARD_TEMPLATES if item['id'] == template_id), CARD_TEMPLATES[0])

def get_avatar_template(template_id):
    return next((item for item in AVATAR_TEMPLATES if item['id'] == template_id), AVATAR_TEMPLATES[0])

def serialize_award_card(card):
    template = get_card_template(card.card_template)
    avatar = get_avatar_template(card.avatar_template)
    color = card.student_color or card.primary_color or template['primary']
    certificate_payload = None
    if getattr(card, 'certificate_payload', None):
        try:
            certificate_payload = json.loads(card.certificate_payload)
        except (TypeError, json.JSONDecodeError):
            certificate_payload = None
    return {
        'id': card.id,
        'username': card.user.username if card.user else 'Student',
        'title': card.title,
        'reason': card.reason or '',
        'message': card.message or '',
        'card_template': card.card_template,
        'avatar_template': card.avatar_template,
        'accent_icon': card.accent_icon or template['icon'],
        'avatar_label': card.avatar_label or (card.user.username if card.user else 'Student'),
        'primary_color': card.primary_color or template['primary'],
        'secondary_color': card.secondary_color or template['secondary'],
        'student_color': card.student_color,
        'display_color': color,
        'shape': card.shape or template['shape'],
        'avatar_shape': card.avatar_shape or avatar['shape'],
        'layout': card.layout or template['layout'],
        'template_name': template['name'],
        'avatar_name': avatar['name'],
        'avatar_icon': avatar['icon'],
        'certificate_payload': certificate_payload,
        'created_at': card.created_at
    }

def normalize_chat_text(message):
    normalized = (message or '').lower().translate(LEET_TRANSLATION)
    return re.sub(r'[^a-z0-9]+', ' ', normalized)

def contains_bad_language(message):
    words = normalize_chat_text(message).split()
    if any(term in words for term in BAD_LANGUAGE_TERMS):
        return True
    for index in range(len(words)):
        combined = ''
        for word in words[index:index + 5]:
            combined += word
            if combined in BAD_LANGUAGE_TERMS:
                return True
            if not any(term.startswith(combined) for term in BAD_LANGUAGE_TERMS):
                break
    return False

def contains_sensitive_language(message):
    normalized = normalize_chat_text(message)
    words = normalized.split()
    if any(term in words for term in SENSITIVE_LANGUAGE_TERMS):
        return True
    normalized_phrase = f' {normalized} '
    for phrase in SENSITIVE_LANGUAGE_PHRASES:
        if f' {normalize_chat_text(phrase)} ' in normalized_phrase:
            return True
    raw_message = (message or '').lower().translate(LEET_TRANSLATION)
    if any(re.search(pattern, raw_message, flags=re.IGNORECASE) for pattern in SENSITIVE_LANGUAGE_PATTERNS):
        return True
    for index in range(len(words)):
        combined = ''
        for word in words[index:index + 5]:
            combined += word
            if combined in SENSITIVE_LANGUAGE_TERMS:
                return True
            if not any(term.startswith(combined) for term in SENSITIVE_LANGUAGE_TERMS):
                break
    return False

def serialize_chat_message(chat_msg):
    return {
        'id': chat_msg.id,
        'username': chat_msg.user.username if chat_msg.user else 'SYSTEM',
        'message': chat_msg.message,
        'is_system': bool(chat_msg.is_system),
        'is_flagged': bool(getattr(chat_msg, 'is_flagged', False)),
        'flag_reason': getattr(chat_msg, 'flag_reason', None),
        'timestamp': (chat_msg.sent_at or datetime.utcnow()).isoformat()
    }

def serialize_admin_chat_message(chat_msg, admin_username=None):
    room = db.session.get(Room, chat_msg.room_id) if chat_msg.room_id else None
    message_text = chat_msg.message or ''
    mention_text = f'@{admin_username}'.lower() if admin_username else ''
    is_mention = bool(mention_text and mention_text in message_text.lower()) or '@admin' in message_text.lower()
    return {
        'id': chat_msg.id,
        'room_id': chat_msg.room_id,
        'room_code': room.room_code if room else f'Room {chat_msg.room_id}',
        'username': chat_msg.user.username if chat_msg.user else 'System',
        'message': message_text,
        'is_system': bool(chat_msg.is_system),
        'is_flagged': bool(getattr(chat_msg, 'is_flagged', False)),
        'flag_reason': getattr(chat_msg, 'flag_reason', None),
        'is_mention': is_mention,
        'time': chat_msg.sent_at.strftime('%Y-%m-%d %H:%M') if chat_msg.sent_at else ''
    }

def google_oauth_configured():
    return bool(app.config['GOOGLE_CLIENT_ID'] and app.config['GOOGLE_CLIENT_SECRET'])

def complete_login(user):
    session.pop('pending_2fa_user_id', None)
    session.pop('pending_email_otp_user_id', None)
    session.pop('pending_email_otp_hash', None)
    session.pop('pending_email_otp_expires_at', None)
    session.pop('pending_email_verification_user_id', None)
    session.pop('pending_admin_2fa_setup_user_id', None)
    session.permanent = True
    session['user_id'] = user.id
    session['username'] = user.username
    session['role'] = user.role
    session['csrf_token'] = secrets.token_urlsafe(32)


def start_admin_totp_setup(user, reset_secret=False):
    if reset_secret and not user.two_factor_enabled:
        user.two_factor_secret = None
    if not user.two_factor_secret:
        user.two_factor_secret = generate_totp_secret()
        db.session.commit()
    csrf_token = session.get('csrf_token')
    session.clear()
    session['csrf_token'] = csrf_token or secrets.token_urlsafe(32)
    session['pending_admin_2fa_setup_user_id'] = user.id
    session['pending_2fa_user_id'] = user.id
    otpauth_uri = totp_otpauth_uri(user, user.two_factor_secret)
    return {
        'success': False,
        'requires_2fa_setup': True,
        'message': 'Admin authenticator setup is required before entering the admin panel.',
        'secret': user.two_factor_secret,
        'otpauth_uri': otpauth_uri,
        'qr_data_uri': qr_data_uri(otpauth_uri)
    }

def create_admin_email_otp(user):
    code = f'{secrets.randbelow(1000000):06d}'
    session['pending_email_otp_user_id'] = user.id
    session['pending_email_otp_hash'] = generate_password_hash(code)
    session['pending_email_otp_expires_at'] = int(time.time()) + 10 * 60
    return code


def verify_pending_email_otp(user, code):
    if not user or session.get('pending_email_otp_user_id') != user.id:
        return False
    if int(session.get('pending_email_otp_expires_at') or 0) < int(time.time()):
        return False
    return check_password_hash(session.get('pending_email_otp_hash') or '', re.sub(r'\s+', '', str(code or '')))


def send_admin_login_otp(user, code):
    target_email = valid_email(user.email if user else '') or configured_admin_email()
    if not user or not target_email:
        return False
    return send_email(
        target_email,
        'Your UI Battle Arena admin login code',
        (
            f'Hello {user.username},\n\n'
            f'Your admin login code is {code}.\n\n'
            'It expires in 10 minutes. If you did not try to sign in, change your admin password immediately.\n\n'
            'UI Battle Arena'
        )
    )


def start_admin_email_otp_session(user, csrf_token=None):
    if not user or user.role != 'admin':
        return None, 400
    if not email_configured():
        return {'success': False, 'error': smtp_configuration_error()}, 400
    target_email = valid_email(user.email) or configured_admin_email()
    if not target_email:
        return {'success': False, 'error': 'Admin email is missing or invalid.'}, 400
    if rate_limited('admin-email-otp-send', str(user.id), limit=10, window_seconds=15 * 60):
        return {'success': False, 'error': 'Too many admin login code requests. Wait a few minutes and try again.'}, 429
    csrf_token = csrf_token or session.get('csrf_token')
    session.clear()
    session['csrf_token'] = csrf_token or secrets.token_urlsafe(32)
    code = create_admin_email_otp(user)
    try:
        sent = send_admin_login_otp(user, code)
    except Exception:
        app.logger.exception('Admin login code send failed for user %s', user.id)
        sent = False
    if not sent:
        session.clear()
        session['csrf_token'] = csrf_token or secrets.token_urlsafe(32)
        return {'success': False, 'error': 'Could not send admin login code. Check Mailjet/SMTP settings and try again.'}, 500
    return {
        'success': False,
        'requires_2fa': True,
        'email_otp': True,
        'can_use_qr_setup': True,
        'message': 'Admin login code sent to the admin email. You can also use authenticator QR setup as a backup option.'
    }, 200


def begin_admin_email_otp_login(user, csrf_token=None):
    payload, status = start_admin_email_otp_session(user, csrf_token)
    if payload is None:
        return None
    return jsonify(payload), status


def room_invite_url(room):
    return url_for('room_invite', room_code=(room.room_code or '').lstrip('#'), _external=True)


def room_invite_payload(room, message=''):
    challenge_title = room.challenge.title if room and room.challenge else 'UI Battle Arena match'
    return {
        'room_id': room.id,
        'room_code': room.room_code,
        'challenge_title': challenge_title,
        'invite_url': room_invite_url(room),
        'message': message or f'You are invited to join {challenge_title}.'
    }


def send_room_invites(room, message=''):
    if not room:
        return {'sent': 0, 'failed': 0, 'skipped': 0, 'total': 0}
    recipients = User.query.filter_by(role='player').filter(User.email.isnot(None), User.email != '').order_by(User.username.asc()).all()
    sent = failed = skipped = 0
    invite_url = room_invite_url(room)
    challenge_title = room.challenge.title if room.challenge else 'UI Battle Arena match'
    custom_message = (message or '').strip()[:1000]
    for target in recipients:
        body = (
            f'Hello {target.username},\n\n'
            f'You are invited to join this UI Battle Arena match: {challenge_title}.\n\n'
            f'Match room ID: {room.room_code}\n'
            f'Join link: {invite_url}\n\n'
            'The first two eligible players who join will enter as competitors. After the match is full, the same link opens spectator mode.\n'
        )
        if custom_message:
            body += f'\nAdmin message:\n{custom_message}\n'
        body += '\nUI Battle Arena'
        try:
            if send_email(target.email, f'UI Battle Arena match invite: {challenge_title}', body):
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
            app.logger.exception('Room invite email failed for user %s', target.id)
    socketio.emit('room_invite', room_invite_payload(room, custom_message))
    return {'sent': sent, 'failed': failed, 'skipped': skipped, 'total': len(recipients)}


def generate_totp_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')

def _totp_digest(secret, counter):
    clean_secret = re.sub(r'\s+', '', str(secret or '')).upper()
    padded_secret = clean_secret + ('=' * ((8 - len(clean_secret) % 8) % 8))
    key = base64.b32decode(padded_secret, casefold=True)
    msg = struct.pack('>Q', counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    token = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f'{token % 1000000:06d}'

def current_totp(secret, timestamp=None):
    timestamp = int(timestamp or time.time())
    return _totp_digest(secret, timestamp // 30)

def verify_totp(secret, code, window=4):
    if not secret or not code:
        return False
    code = re.sub(r'\s+', '', str(code))
    if not re.fullmatch(r'\d{6}', code):
        return False
    counter = int(time.time()) // 30
    try:
        return any(hmac.compare_digest(_totp_digest(secret, counter + step), code) for step in range(-window, window + 1))
    except (binascii.Error, ValueError):
        return False

def normalize_recovery_code(code):
    return re.sub(r'[^A-Z0-9]', '', str(code or '').upper())

def make_recovery_code():
    raw = secrets.token_hex(6).upper()
    return '-'.join(raw[index:index + 4] for index in range(0, len(raw), 4))

def generate_recovery_codes(count=8):
    codes = [make_recovery_code() for _ in range(count)]
    hashes = [generate_password_hash(normalize_recovery_code(code)) for code in codes]
    return codes, hashes

def get_recovery_hashes(user):
    try:
        hashes = json.loads(user.two_factor_recovery_hashes or '[]')
    except (TypeError, ValueError):
        hashes = []
    return hashes if isinstance(hashes, list) else []

def verify_and_consume_recovery_code(user, code):
    normalized = normalize_recovery_code(code)
    if len(normalized) < 8:
        return False
    hashes = get_recovery_hashes(user)
    for index, recovery_hash in enumerate(hashes):
        if check_password_hash(recovery_hash, normalized):
            del hashes[index]
            user.two_factor_recovery_hashes = json.dumps(hashes)
            return True
    return False

def totp_otpauth_uri(user, secret):
    label = urllib.parse.quote(f'UI Battle Arena:{user.username}')
    issuer = urllib.parse.quote('UI Battle Arena')
    return f'otpauth://totp/{label}?secret={secret}&issuer={issuer}&digits=6&period=30'

def qr_data_uri(value):
    if not qrcode:
        return None
    image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
    stream = io.BytesIO()
    image.save(stream)
    encoded = base64.b64encode(stream.getvalue()).decode('ascii')
    return f'data:image/svg+xml;base64,{encoded}'

def fetch_json_url(url, payload=None, headers=None):
    data = None
    method = 'GET'
    if payload is not None:
        data = urllib.parse.urlencode(payload).encode('utf-8')
        method = 'POST'
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode('utf-8'))

def ensure_schema_upgrades():
    global schema_upgrades_ready
    if schema_upgrades_ready:
        return
    db.create_all()
    user_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(users)")).fetchall()}
    user_additions = {
        'email': 'ALTER TABLE users ADD COLUMN email VARCHAR(255)',
        'auth_provider': "ALTER TABLE users ADD COLUMN auth_provider VARCHAR(20) DEFAULT 'local'",
        'google_sub': 'ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)',
        'two_factor_secret': 'ALTER TABLE users ADD COLUMN two_factor_secret VARCHAR(64)',
        'two_factor_enabled': 'ALTER TABLE users ADD COLUMN two_factor_enabled BOOLEAN DEFAULT 0',
        'two_factor_recovery_hashes': 'ALTER TABLE users ADD COLUMN two_factor_recovery_hashes TEXT',
        'leaderboard_unlocked_at': 'ALTER TABLE users ADD COLUMN leaderboard_unlocked_at DATETIME',
        'leaderboard_awarded': 'ALTER TABLE users ADD COLUMN leaderboard_awarded BOOLEAN DEFAULT 0',
        'leaderboard_awarded_at': 'ALTER TABLE users ADD COLUMN leaderboard_awarded_at DATETIME',
        'leaderboard_awarded_by': 'ALTER TABLE users ADD COLUMN leaderboard_awarded_by INTEGER',
        'leaderboard_award_reason': 'ALTER TABLE users ADD COLUMN leaderboard_award_reason VARCHAR(200)',
        'leaderboard_award_details': 'ALTER TABLE users ADD COLUMN leaderboard_award_details TEXT',
        'leaderboard_award_color': 'ALTER TABLE users ADD COLUMN leaderboard_award_color VARCHAR(20)'
    }
    for column, ddl in user_additions.items():
        if column not in user_columns:
            db.session.execute(text(ddl))

    challenge_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(challenges)")).fetchall()}
    challenge_additions = {
        'challenge_type': "ALTER TABLE challenges ADD COLUMN challenge_type VARCHAR(10) DEFAULT 'image'",
        'target_html': 'ALTER TABLE challenges ADD COLUMN target_html TEXT',
        'target_css': 'ALTER TABLE challenges ADD COLUMN target_css TEXT',
        'target_js': 'ALTER TABLE challenges ADD COLUMN target_js TEXT',
        'starter_html': 'ALTER TABLE challenges ADD COLUMN starter_html TEXT',
        'starter_css': 'ALTER TABLE challenges ADD COLUMN starter_css TEXT',
        'starter_js': 'ALTER TABLE challenges ADD COLUMN starter_js TEXT',
        'html_locked': 'ALTER TABLE challenges ADD COLUMN html_locked BOOLEAN DEFAULT 1'
    }
    for column, ddl in challenge_additions.items():
        if column not in challenge_columns:
            db.session.execute(text(ddl))

    chat_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(chat_messages)")).fetchall()}
    chat_additions = {
        'is_flagged': 'ALTER TABLE chat_messages ADD COLUMN is_flagged BOOLEAN DEFAULT 0',
        'flag_reason': 'ALTER TABLE chat_messages ADD COLUMN flag_reason VARCHAR(160)',
        'flagged_by': 'ALTER TABLE chat_messages ADD COLUMN flagged_by INTEGER'
    }
    for column, ddl in chat_additions.items():
        if column not in chat_columns:
            db.session.execute(text(ddl))

    room_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(rooms)")).fetchall()}
    room_additions = {
        'is_public': 'ALTER TABLE rooms ADD COLUMN is_public BOOLEAN DEFAULT 0',
        'competition_id': 'ALTER TABLE rooms ADD COLUMN competition_id INTEGER',
        'wave_id': 'ALTER TABLE rooms ADD COLUMN wave_id INTEGER'
    }
    for column, ddl in room_additions.items():
        if column not in room_columns:
            db.session.execute(text(ddl))

    submission_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(submissions)")).fetchall()}
    submission_additions = {
        'score_details': 'ALTER TABLE submissions ADD COLUMN score_details TEXT'
    }
    for column, ddl in submission_additions.items():
        if column not in submission_columns:
            db.session.execute(text(ddl))

    tournament_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(tournaments)")).fetchall()}
    tournament_additions = {
        'certificate_settings': 'ALTER TABLE tournaments ADD COLUMN certificate_settings TEXT'
    }
    for column, ddl in tournament_additions.items():
        if column not in tournament_columns:
            db.session.execute(text(ddl))

    award_card_columns = {row[1] for row in db.session.execute(text("PRAGMA table_info(award_cards)")).fetchall()}
    award_card_additions = {
        'certificate_payload': 'ALTER TABLE award_cards ADD COLUMN certificate_payload TEXT'
    }
    for column, ddl in award_card_additions.items():
        if column not in award_card_columns:
            db.session.execute(text(ddl))
    db.session.commit()
    schema_upgrades_ready = True

def submission_score_analysis(submission, challenge=None):
    if not submission or submission.is_forfeit:
        return 0.0, {
            'html_similarity': 0.0,
            'css_similarity': 0.0,
            'style_property_match': 0.0,
            'code_quality': 0.0,
            'scoring_mode': 'forfeit'
        }
    stored_accuracy = max(0.0, min(100.0, float(submission.accuracy or 0)))
    if getattr(submission, 'score_details', None):
        try:
            details = json.loads(submission.score_details)
            if isinstance(details, dict):
                return round(stored_accuracy, 1), details
        except (TypeError, ValueError):
            pass
    challenge = challenge or getattr(submission, 'challenge', None)
    accuracy, details = deterministic_submission_score(
        challenge,
        submission.html_code,
        submission.css_code,
        submission.js_code
    )
    if stored_accuracy and not getattr(submission, 'score_details', None):
        details['scoring_mode'] = 'stored-legacy'
        return round(stored_accuracy, 1), details
    return accuracy, details

def get_best_room_submission(room_id, user_id):
    submissions = Submission.query.filter_by(room_id=room_id, user_id=user_id).all()
    if not submissions:
        return None
    room = db.session.get(Room, room_id)
    challenge = room.challenge if room else None
    for sub in submissions:
        accuracy, _details = submission_score_analysis(sub, challenge)
        if round(float(sub.accuracy or 0), 1) != accuracy:
            sub.accuracy = accuracy
    return max(submissions, key=lambda sub: submission_rank_tuple(sub, challenge))

CSS_SCORE_PROPERTIES = {
    'font-size', 'font-family', 'font-weight', 'line-height', 'letter-spacing',
    'color', 'background', 'background-color', 'display', 'position', 'top',
    'right', 'bottom', 'left', 'width', 'height', 'max-width', 'min-height',
    'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
    'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
    'border', 'border-width', 'border-style', 'border-color', 'border-top',
    'border-right', 'border-bottom', 'border-left', 'border-radius',
    'box-shadow', 'opacity',
    'transform', 'gap', 'align-items', 'justify-content', 'grid-template-columns',
    'grid-template-rows', 'flex-direction', 'overflow', 'object-fit'
}

CSS_SCORE_GROUPS = {
    'Typography': {'font-size', 'font-family', 'font-weight', 'line-height', 'letter-spacing'},
    'Color': {'color', 'background', 'background-color', 'opacity'},
    'Layout': {'display', 'position', 'top', 'right', 'bottom', 'left', 'width', 'height', 'max-width', 'min-height', 'transform'},
    'Spacing': {'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left', 'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left', 'gap'},
    'Shape': {'border', 'border-width', 'border-style', 'border-color', 'border-top', 'border-right', 'border-bottom', 'border-left', 'border-radius', 'box-shadow'},
    'Alignment': {'align-items', 'justify-content', 'grid-template-columns', 'grid-template-rows', 'flex-direction', 'overflow', 'object-fit'}
}

def normalize_code_text(value):
    text_value = str(value or '').lower()
    text_value = re.sub(r'/\*.*?\*/', ' ', text_value, flags=re.S)
    text_value = re.sub(r'<!--.*?-->', ' ', text_value, flags=re.S)
    text_value = re.sub(r'//.*', ' ', text_value)
    return re.sub(r'\s+', ' ', text_value).strip()

def token_similarity(left, right):
    left_tokens = set(re.findall(r'[a-z0-9_-]+', normalize_code_text(left)))
    right_tokens = set(re.findall(r'[a-z0-9_-]+', normalize_code_text(right)))
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

def numeric_value_similarity(left, right):
    left_numbers = [float(num) for num in re.findall(r'-?\d+(?:\.\d+)?', str(left or ''))]
    right_numbers = [float(num) for num in re.findall(r'-?\d+(?:\.\d+)?', str(right or ''))]
    if not left_numbers or not right_numbers:
        return None
    pairs = zip(left_numbers[:4], right_numbers[:4])
    scores = []
    for left_num, right_num in pairs:
        denominator = max(abs(left_num), abs(right_num), 1.0)
        scores.append(max(0.0, 1.0 - (abs(left_num - right_num) / denominator)))
    return sum(scores) / len(scores) if scores else None

def css_value_similarity(player_value, target_value):
    player = normalize_code_text(player_value)
    target = normalize_code_text(target_value)
    if not player or not target:
        return 0.0
    if player == target:
        return 1.0
    token_score = token_similarity(player, target)
    number_score = numeric_value_similarity(player, target)
    if number_score is None:
        return token_score
    return max(token_score * 0.7, (token_score * 0.45) + (number_score * 0.55))

def extract_css_properties(css_text):
    properties = {}
    for name, value in re.findall(r'([a-zA-Z-]+)\s*:\s*([^;{}]+)', str(css_text or '')):
        key = name.strip().lower()
        if key in CSS_SCORE_PROPERTIES:
            properties.setdefault(key, set()).add(normalize_code_text(value))
    return properties

def css_property_similarity(player_css, target_css):
    target_props = extract_css_properties(target_css)
    player_props = extract_css_properties(player_css)
    if not target_props:
        return 0.0
    score = 0
    for prop, target_values in target_props.items():
        player_values = player_props.get(prop, set())
        if not player_values:
            continue
        if target_values & player_values:
            score += 1
        else:
            best = max((css_value_similarity(pv, tv) for pv in player_values for tv in target_values), default=0)
            score += best * 0.75
    return score / len(target_props)

def css_group_similarity(player_css, target_css):
    target_props = extract_css_properties(target_css)
    player_props = extract_css_properties(player_css)
    groups = {}
    for label, properties in CSS_SCORE_GROUPS.items():
        group_targets = {prop: values for prop, values in target_props.items() if prop in properties}
        if not group_targets:
            continue
        score = 0
        for prop, target_values in group_targets.items():
            player_values = player_props.get(prop, set())
            if not player_values:
                continue
            if target_values & player_values:
                score += 1
            else:
                score += max((css_value_similarity(pv, tv) for pv in player_values for tv in target_values), default=0) * 0.75
        groups[label.lower().replace(' ', '_')] = round((score / len(group_targets)) * 100, 1)
    return groups

def safe_visual_hint(value):
    try:
        return max(0.0, min(100.0, float(value))) / 100.0
    except (TypeError, ValueError):
        return None

def calculate_code_quality(html_code, css_code, js_code=''):
    combined = '\n'.join([str(html_code or ''), str(css_code or ''), str(js_code or '')])
    stripped = combined.strip()
    if not stripped:
        return 0.0
    score = 100.0
    lines = [line.rstrip() for line in combined.splitlines() if line.strip()]
    duplicate_ratio = 0 if not lines else 1 - (len(set(lines)) / len(lines))
    score -= min(18, duplicate_ratio * 30)
    score -= min(16, combined.count('!important') * 2)
    score -= min(12, len(re.findall(r'\bconsole\.log\b', combined)) * 3)
    score -= min(14, len([line for line in lines if len(line) > 140]) * 2)
    if '<style' in combined.lower():
        score -= 5
    if len(re.findall(r'<\s*div\b', combined, re.I)) > 18 and not re.search(r'<\s*(main|section|article|header|footer|nav)\b', combined, re.I):
        score -= 8
    if str(css_code or '').count('{') != str(css_code or '').count('}'):
        score -= 14
    if str(html_code or '').count('<') < 2:
        score -= 12
    return round(max(0, min(100, score)), 1)

def deterministic_submission_score(challenge, html_code, css_code, js_code='', visual_hint=None):
    html_code = str(html_code or '')
    css_code = str(css_code or '')
    js_code = str(js_code or '')
    quality = calculate_code_quality(html_code, css_code, js_code)
    target_html = getattr(challenge, 'target_html', '') or ''
    target_css = getattr(challenge, 'target_css', '') or ''
    challenge_type = getattr(challenge, 'challenge_type', 'image') if challenge else 'image'

    html_similarity = token_similarity(html_code, target_html) if target_html else min(1.0, len(normalize_code_text(html_code)) / 260)
    css_similarity = token_similarity(css_code, target_css) if target_css else min(1.0, len(extract_css_properties(css_code)) / 18)
    property_similarity = css_property_similarity(css_code, target_css) if target_css else min(1.0, len(extract_css_properties(css_code)) / 24)
    property_groups = css_group_similarity(css_code, target_css) if target_css else {}
    visual_similarity = safe_visual_hint(visual_hint)
    js_penalty = 0 if not js_code.strip() else min(6, len(js_code.strip()) / 600)

    if challenge_type == 'html' and (target_html or target_css):
        if visual_similarity is not None:
            score = (visual_similarity * 52) + (property_similarity * 25) + (html_similarity * 10) + (css_similarity * 5) + (quality * 0.08) - js_penalty
        else:
            score = (property_similarity * 45) + (html_similarity * 18) + (css_similarity * 17) + (quality * 0.20) - js_penalty
    else:
        structure_score = min(1.0, (len(re.findall(r'<[a-z][\w-]*', html_code, re.I)) / 10))
        style_score = min(1.0, len(extract_css_properties(css_code)) / 20)
        if visual_similarity is not None:
            score = (visual_similarity * 65) + (style_score * 14) + (structure_score * 8) + (quality * 0.13) - js_penalty
        else:
            score = (structure_score * 28) + (style_score * 42) + (css_similarity * 12) + (quality * 0.18) - js_penalty

    details = {
        'html_similarity': round(html_similarity * 100, 1),
        'css_similarity': round(css_similarity * 100, 1),
        'style_property_match': round(property_similarity * 100, 1),
        'visual_match': round((visual_similarity or 0) * 100, 1),
        'code_quality': quality,
        'style_groups': property_groups,
        'scoring_mode': 'visual-output-target' if visual_similarity is not None else ('target-code' if challenge_type == 'html' and (target_html or target_css) else 'visual-code-rubric')
    }
    return round(max(0, min(100, score)), 1), details

def analysis_number(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default

def analysis_metric_plan(details):
    mode = (details or {}).get('scoring_mode') or ''
    if mode == 'visual-output-target':
        return [
            ('visual_match', 'Rendered output', 52, 'The final preview did not visually match the target closely enough. Re-check overall layout, sizing, spacing, colors, borders, shadows, and responsive positioning.'),
            ('style_property_match', 'CSS details', 25, 'Important CSS properties were different from the target. Small details such as border width, border radius, gaps, padding, font weight, and shadows can move the score.'),
            ('html_similarity', 'HTML structure', 10, 'The structure differed from the reference. Use clearer sections, headings, wrappers, and element hierarchy that support the target layout.'),
            ('css_similarity', 'CSS selector/tokens', 5, 'The CSS used a different set of selectors or tokens from the target. This is less important than output, but it can still cost marks.'),
            ('code_quality', 'Clean code', 8, 'Repeated code, unbalanced CSS, very long lines, unnecessary inline styles, console logs, or too much !important reduced the clean-code portion.')
        ]
    if mode == 'target-code':
        return [
            ('style_property_match', 'CSS details', 45, 'Most lost marks came from CSS properties not matching the target closely enough. Tune dimensions, spacing, borders, radius, colors, alignment, and typography.'),
            ('html_similarity', 'HTML structure', 18, 'The HTML hierarchy did not follow the target closely. Match the important sections and semantic structure.'),
            ('css_similarity', 'CSS selector/tokens', 17, 'The CSS tokens differed from the target. Align key selectors and style values where they affect the same visible pieces.'),
            ('code_quality', 'Clean code', 20, 'Cleaner, balanced, less repetitive code would protect this part of the score.')
        ]
    return [
        ('visual_match', 'Rendered output', 65, 'The output did not visually line up with the target. Focus first on what the viewer sees.'),
        ('style_property_match', 'CSS details', 14, 'Add and tune the missing visual CSS details.'),
        ('html_similarity', 'HTML structure', 8, 'Use enough structure to reproduce the target reliably.'),
        ('code_quality', 'Clean code', 13, 'Cleaner code would recover part of the score.')
    ]

def build_submission_analysis(submission, challenge, opponent_submission=None):
    if not submission:
        return None
    accuracy, details = submission_score_analysis(submission, challenge)
    plan = analysis_metric_plan(details)
    score_cards = []
    for key, label, weight, issue in plan:
        value = analysis_number(details.get(key))
        lost = round(max(0, (100 - value) / 100 * weight), 1)
        if lost <= 0.2:
            status = 'Strong'
            coaching = f'{label} was close to the target, so this area did not cost many marks.'
        elif value < 55:
            status = 'Needs work'
            coaching = issue
        else:
            status = 'Close'
            coaching = f'{label} was partly correct. Tightening this area could add about {lost}% to the score line.'
        score_cards.append({
            'key': key,
            'label': label,
            'value': round(value, 1),
            'weight': weight,
            'lost': lost,
            'status': status,
            'coaching': coaching
        })
    score_cards = sorted(score_cards, key=lambda item: item['lost'], reverse=True)

    suggestions = []
    for card in score_cards[:3]:
        if card['lost'] > 0.5:
            suggestions.append(f"{card['label']}: {card['coaching']} This part carried about {card['weight']}% in this match and you left roughly {card['lost']}% there.")
    groups = details.get('style_groups') or {}
    weak_groups = sorted(
        [(label.replace('_', ' '), analysis_number(value)) for label, value in groups.items()],
        key=lambda item: item[1]
    )
    if weak_groups and weak_groups[0][1] < 75:
        readable = ', '.join(f'{label} ({round(value, 1)}%)' for label, value in weak_groups[:3])
        suggestions.append(f'Your weakest visual categories were {readable}. Fixing these usually means checking spacing, dimensions, alignment, borders, and typography against the target one piece at a time.')
    if not suggestions:
        suggestions.append('Strong submission. The remaining marks were likely small visual differences such as tiny spacing, sizing, or polish details.')

    comparison = None
    if opponent_submission:
        opponent_accuracy, opponent_details = submission_score_analysis(opponent_submission, challenge)
        margin = round(opponent_accuracy - accuracy, 1)
        deltas = []
        for key, label, weight, _issue in plan:
            own_value = analysis_number(details.get(key))
            opponent_value = analysis_number(opponent_details.get(key))
            diff = round(opponent_value - own_value, 1)
            impact = round(max(0, diff) / 100 * weight, 1)
            if abs(diff) >= 1:
                deltas.append({
                    'label': label,
                    'diff': diff,
                    'impact': impact,
                    'opponent_value': round(opponent_value, 1),
                    'own_value': round(own_value, 1)
                })
        deltas = sorted(deltas, key=lambda item: item['impact'], reverse=True)
        opponent_name = opponent_submission.user.username if opponent_submission.user else 'the other player'
        if margin > 0:
            lead_reasons = [item for item in deltas if item['impact'] > 0][:3]
            if lead_reasons:
                reason_text = '; '.join(
                    f"{item['label']} was {item['opponent_value']}% vs your {item['own_value']}%, worth about {item['impact']}% of the gap"
                    for item in lead_reasons
                )
                summary = f'{opponent_name} finished {margin}% ahead. The biggest differences were: {reason_text}.'
            else:
                summary = f'{opponent_name} finished {margin}% ahead mainly through small combined differences across the rubric.'
        elif margin < 0:
            summary = f'You finished {abs(margin)}% ahead of {opponent_name}. Your stronger areas protected the lead, but the weak areas below are still where extra marks were available.'
        else:
            summary = f'You tied with {opponent_name}. The next match may swing on small details because each challenge can weight output and style details differently.'
        comparison = {
            'opponent_name': opponent_name,
            'margin': margin,
            'summary': summary,
            'deltas': deltas[:4]
        }

    total_lost_estimate = round(sum(card['lost'] for card in score_cards), 1)
    top_gain = score_cards[0]['lost'] if score_cards else 0
    summary = (
        f'You scored {accuracy}%. The clearest next improvement is {score_cards[0]["label"].lower()}, '
        f'where about {top_gain}% was still available in this match.'
        if score_cards and top_gain > 0.5
        else f'You scored {accuracy}%. This was a strong attempt; remaining marks were mostly fine details.'
    )
    return {
        'accuracy': accuracy,
        'details': details,
        'suggestions': suggestions,
        'score_cards': score_cards,
        'comparison': comparison,
        'summary': summary,
        'total_lost_estimate': total_lost_estimate,
        'scoring_note': 'These percentages explain this match only. Admin targets and challenge types can change how marks are distributed next time.'
    }

def get_submission_quality(submission):
    if not submission or submission.is_forfeit:
        return 0.0
    return calculate_code_quality(submission.html_code, submission.css_code, submission.js_code)

def submission_rank_tuple(submission, challenge=None):
    if not submission or submission.is_forfeit:
        return (0.0, 0.0, 0.0, 0.0)
    accuracy, details = submission_score_analysis(submission, challenge)
    return (
        accuracy,
        details.get('code_quality', get_submission_quality(submission)),
        1.0 if submission.is_final else 0.0,
        datetime_sort_value(submission.submitted_at)
    )

def room_score_payload(room):
    if not room:
        return []
    rows = []
    for player in [room.player1, room.player2]:
        if not player:
            continue
        sub = get_best_room_submission(room.id, player.id)
        accuracy, details = submission_score_analysis(sub, room.challenge) if sub else (0.0, {})
        rows.append({
            'user_id': player.id,
            'username': player.username,
            'accuracy': accuracy,
            'code_quality': details.get('code_quality', 0.0),
            'score_details': details,
            'is_forfeit': bool(sub.is_forfeit) if sub else False
        })
    return rows

def get_room_winner_id(room):
    if not room or not (room.player1_id or room.player2_id):
        return None

    p1_sub = get_best_room_submission(room.id, room.player1_id) if room.player1_id else None
    p2_sub = get_best_room_submission(room.id, room.player2_id) if room.player2_id else None
    if not p1_sub and not p2_sub:
        return None

    if room.player1_id and not room.player2_id:
        return room.player1_id if p1_sub and not p1_sub.is_forfeit else None
    if room.player2_id and not room.player1_id:
        return room.player2_id if p2_sub and not p2_sub.is_forfeit else None
    if p1_sub and p1_sub.is_forfeit and (not p2_sub or not p2_sub.is_forfeit):
        return room.player2_id
    if p2_sub and p2_sub.is_forfeit and (not p1_sub or not p1_sub.is_forfeit):
        return room.player1_id
    if p1_sub and p1_sub.is_forfeit and p2_sub and p2_sub.is_forfeit:
        return None

    p1_rank = submission_rank_tuple(p1_sub)
    p2_rank = submission_rank_tuple(p2_sub)
    if p1_rank[:2] == p2_rank[:2]:
        return None
    return room.player1_id if p1_rank[:2] > p2_rank[:2] else room.player2_id

def datetime_sort_value(value):
    if not value:
        return 0
    if value.tzinfo:
        return value.timestamp()
    return value.replace(tzinfo=timezone.utc).timestamp()

def get_user_match_events(user_id):
    rooms = Room.query.filter((Room.player1_id == user_id) | (Room.player2_id == user_id)).all()
    room_ids = {room.id for room in rooms}
    submitted_room_ids = {
        room_id for (room_id,) in db.session.query(Submission.room_id).filter_by(user_id=user_id).distinct().all()
        if room_id is not None
    }
    for room_id in submitted_room_ids - room_ids:
        room = db.session.get(Room, room_id)
        if room:
            rooms.append(room)

    events = []
    for room in rooms:
        own_sub = get_best_room_submission(room.id, user_id)
        winner_id = get_room_winner_id(room)
        opponent_id = room.player2_id if room.player1_id == user_id else room.player1_id
        opponent = db.session.get(User, opponent_id) if opponent_id else None
        completed_at = room.ended_at or (own_sub.submitted_at if own_sub else room.created_at)

        if winner_id == user_id:
            result = 'win'
        elif winner_id:
            result = 'loss'
        elif own_sub:
            result = 'draw' if opponent_id else ('win' if own_sub.accuracy >= 50 and not own_sub.is_forfeit else 'loss')
        else:
            result = 'pending'

        events.append({
            'room': room,
            'submission': own_sub,
            'opponent': opponent,
            'result': result,
            'completed_at': completed_at or datetime.min
        })

    return sorted(events, key=lambda item: datetime_sort_value(item['completed_at']), reverse=True)

def calculate_player_record(user):
    events = [event for event in get_user_match_events(user.id) if event['result'] != 'pending']
    wins = sum(1 for event in events if event['result'] == 'win')
    losses = sum(1 for event in events if event['result'] == 'loss')
    draws = sum(1 for event in events if event['result'] == 'draw')
    submissions = [event['submission'] for event in events if event['submission'] and not event['submission'].is_forfeit]
    best_accuracy = max((sub.accuracy for sub in submissions), default=0)
    avg_accuracy = round(sum(sub.accuracy for sub in submissions) / len(submissions), 1) if submissions else 0

    current_streak = 0
    for event in events:
        if event['result'] == 'win':
            current_streak += 1
        else:
            break

    best_streak = 0
    running = 0
    for event in reversed(events):
        if event['result'] == 'win':
            running += 1
            best_streak = max(best_streak, running)
        else:
            running = 0

    matches_played = len(events)
    win_rate = round((wins / matches_played) * 100, 1) if matches_played else 0
    power_score = round(
        (wins * 120)
        + (best_streak * 35)
        + (current_streak * 20)
        + (avg_accuracy * 1.8)
        + (best_accuracy * 1.2)
        + (matches_played * 8)
        - (losses * 12),
        1
    )

    return {
        'matches_played': matches_played,
        'wins': wins,
        'losses': losses,
        'draws': draws,
        'win_rate': win_rate,
        'avg_accuracy': avg_accuracy,
        'best_accuracy': round(best_accuracy, 1),
        'current_streak': current_streak,
        'best_streak': best_streak,
        'power_score': max(power_score, 0),
        'events': events
    }

def sync_user_competition_state(user):
    record = calculate_player_record(user)
    user.matches_played = record['matches_played']
    user.total_wins = record['wins']
    user.best_accuracy = record['best_accuracy']
    if record['best_streak'] >= LEADERBOARD_STREAK_TARGET and not user.leaderboard_unlocked_at:
        user.leaderboard_unlocked_at = datetime.now(timezone.utc)
    return record

def finalize_room_results(room):
    if not room:
        return
    final_submissions = Submission.query.filter_by(room_id=room.id).all()
    for sub in final_submissions:
        sub.is_final = True
    if room.player1:
        sync_user_competition_state(room.player1)
    if room.player2:
        sync_user_competition_state(room.player2)
    sync_tournament_match_for_room(room)

def user_has_leaderboard_access(user, record=None):
    record = record or calculate_player_record(user)
    return bool(user.leaderboard_awarded or user.leaderboard_unlocked_at or record['best_streak'] >= LEADERBOARD_STREAK_TARGET)

def build_leaderboard_rows():
    rows = []
    for player in User.query.filter_by(role='player').all():
        record = sync_user_competition_state(player)
        rows.append({
            'user': player,
            'record': record,
            'leaderboard_unlocked': user_has_leaderboard_access(player, record),
            'unlock_reason': 'Admin award' if player.leaderboard_awarded else (
                f"{record['best_streak']} win streak" if record['best_streak'] >= LEADERBOARD_STREAK_TARGET else 'Locked'
            )
        })
    db.session.commit()
    return sorted(rows, key=lambda row: (row['record']['power_score'], row['record']['win_rate'], row['record']['best_accuracy']), reverse=True)

def build_leaderboard_award_card(user, row, rank):
    if not user or not row or not row.get('leaderboard_unlocked'):
        return None
    record = row['record']
    events = record.get('events', [])
    challenge_names = []
    for event in events:
        room = event.get('room')
        title = room.challenge.title if room and room.challenge else None
        if title and title not in challenge_names:
            challenge_names.append(title)
    tournament_entries = TournamentParticipant.query.filter_by(user_id=user.id).order_by(TournamentParticipant.created_at.desc()).limit(4).all()
    tournament_names = [
        entry.tournament.name for entry in tournament_entries
        if entry.tournament and entry.tournament.name
    ]
    if user.leaderboard_awarded:
        reason = user.leaderboard_award_reason or 'Awarded manually by an admin'
        details = user.leaderboard_award_details or 'Admin recognized this player for leaderboard access.'
        award_type = 'Admin Award'
        award_date = user.leaderboard_awarded_at or datetime.now(timezone.utc)
    else:
        reason = f"Earned automatically with a best streak of {record['best_streak']} wins"
        details = (
            f"Qualified through real match performance: {record['wins']} wins, "
            f"{record['matches_played']} matches played, {record['best_accuracy']}% best accuracy, "
            f"and {round(record['power_score'], 1)} power score."
        )
        award_type = 'Performance Award'
        award_date = user.leaderboard_unlocked_at or datetime.now(timezone.utc)
    participation = ', '.join(challenge_names[:4]) if challenge_names else 'No completed challenge records yet'
    tournaments = ', '.join(tournament_names[:4]) if tournament_names else 'No tournament entries yet'
    return {
        'username': user.username,
        'rank': rank,
        'award_type': award_type,
        'reason': reason,
        'details': details,
        'participation': participation,
        'tournaments': tournaments,
        'power_score': round(record['power_score'], 1),
        'wins': record['wins'],
        'matches_played': record['matches_played'],
        'best_accuracy': record['best_accuracy'],
        'best_streak': record['best_streak'],
        'date': award_date,
        'card_id': f"LB-{user.id:04d}-{datetime_sort_value(award_date):.0f}",
        'color': user.leaderboard_award_color or '#d97706'
    }

def build_profile_achievements(user, record, rank=None, award_card=None):
    profile = get_profile_view_data(user.id)
    matches_played = int(record.get('matches_played') or 0)
    wins = int(record.get('wins') or 0)
    best_accuracy = float(record.get('best_accuracy') or 0)
    best_streak = int(record.get('best_streak') or 0)
    items = [
        {'title': 'First Match', 'description': 'Completed the first arena match.', 'icon': 'fa-flag-checkered', 'unlocked': matches_played >= 1},
        {'title': 'Perfect Score', 'description': 'Reached 100% accuracy in a challenge.', 'icon': 'fa-star', 'unlocked': best_accuracy >= 99.9},
        {'title': 'Win Streak', 'description': 'Built a 3 match winning streak.', 'icon': 'fa-fire', 'unlocked': best_streak >= 3},
        {'title': 'Veteran Player', 'description': 'Played at least 10 matches.', 'icon': 'fa-shield-halved', 'unlocked': matches_played >= 10},
        {'title': 'Leaderboard Elite', 'description': 'Unlocked or received leaderboard recognition.', 'icon': 'fa-ranking-star', 'unlocked': bool(user_has_leaderboard_access(user, record))},
        {'title': 'Profile Avatar Card', 'description': 'Added a custom profile avatar.', 'icon': 'fa-id-card', 'unlocked': bool(profile.get('avatar_url'))},
    ]
    return {
        'achievement_items': items,
        'unlocked_count': sum(1 for item in items if item['unlocked']),
        'award_card': award_card,
        'rank': rank,
        'avatar_url': profile.get('avatar_url'),
        'bio': profile.get('bio', ''),
        'wins': wins,
        'matches_played': matches_played,
        'best_accuracy': best_accuracy,
        'best_streak': best_streak
    }

TOURNAMENT_SIZES = {4, 8, 16, 32, 64, 128}
ROUND_NAMES_BY_SIZE = {
    32: 'Round of 32',
    16: 'Round of 16',
    8: 'Quarter Finals',
    4: 'Semi Finals',
    2: 'Finals'
}

def tournament_round_name(player_count):
    return ROUND_NAMES_BY_SIZE.get(player_count, f'Round of {player_count}')

def parse_int_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [item for item in re.split(r'[\s,]+', value) if item.strip()]
    try:
        return [int(item) for item in value]
    except (TypeError, ValueError):
        return []

def parse_positive_int(value, default=0, minimum=0, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number

def parse_bool_value(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}

def competition_stage_label(value):
    return str(value or 'registration').replace('_', ' ').title()

def challenge_usage_to_format(value):
    usage = value or 'single_room'
    return {
        'challenge_only': 'challenge_only',
        'single_room': 'single_room',
        'bulk_rooms': 'bulk_rooms',
        'auto_pair_live': 'auto_pair_live',
        'qualification': 'qualification',
        'bracket': 'bracket',
        'qualifier_bracket': 'qualifier_bracket'
    }.get(usage, 'single_room')

def next_power_of_two(value):
    number = max(2, int(value or 2))
    power = 1
    while power < number:
        power *= 2
    return power

def create_competition_record(name, challenge_id=None, created_by=None, **options):
    competition = Competition(
        name=(name or 'Untitled Competition').strip()[:160],
        format=options.get('format') or 'single_room',
        stage=options.get('stage') or 'registration',
        status=options.get('status') or options.get('stage') or 'registration',
        challenge_id=challenge_id,
        max_participants=parse_positive_int(options.get('max_participants'), 2, 1, 5000),
        room_mode=options.get('room_mode') or '1v1',
        players_per_wave=parse_positive_int(options.get('players_per_wave'), 100, 2, 5000),
        room_visibility=options.get('room_visibility') or 'private',
        start_at=(options.get('start_at') or '').strip()[:80] or None,
        end_at=(options.get('end_at') or '').strip()[:80] or None,
        auto_start=bool(options.get('auto_start')),
        auto_submit=options.get('auto_submit', True) is not False,
        allowed_attempts=options.get('allowed_attempts') or 'one',
        tie_break_rule=options.get('tie_break_rule') or 'higher_score_then_time',
        advance_rule=options.get('advance_rule') or 'top_32',
        fair_play_strictness=options.get('fair_play_strictness') or 'normal',
        notes=(options.get('notes') or '').strip() or None,
        created_by=created_by
    )
    db.session.add(competition)
    db.session.flush()
    return competition

def create_wave_record(competition, name, challenge_id=None, **options):
    wave = CompetitionWave(
        competition_id=competition.id,
        name=(name or f'Wave {len(competition.waves) + 1}').strip()[:100],
        status=options.get('status') or 'scheduled',
        challenge_id=challenge_id or competition.challenge_id,
        start_at=(options.get('start_at') or '').strip()[:80] or None,
        end_at=(options.get('end_at') or '').strip()[:80] or None,
        players_expected=parse_positive_int(options.get('players_expected'), 0, 0, 5000)
    )
    db.session.add(wave)
    db.session.flush()
    return wave

def parse_admin_assignment_lines(raw_value):
    assignments = []
    for line in str(raw_value or '').splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split(':')]
        if not parts:
            continue
        admin_id = parse_positive_int(parts[0], 0, 1)
        if not admin_id:
            continue
        role = (parts[1] if len(parts) > 1 and parts[1] else 'room_admin')[:40]
        range_start = None
        range_end = None
        if len(parts) > 2 and parts[2]:
            match = re.match(r'^\s*(\d+)\s*(?:-|\.\.)\s*(\d+)\s*$', parts[2])
            if match:
                range_start = parse_positive_int(match.group(1), None, 1)
                range_end = parse_positive_int(match.group(2), None, 1)
            else:
                single = parse_positive_int(parts[2], 0, 1)
                range_start = single or None
                range_end = single or None
        notes = ':'.join(parts[3:]).strip() if len(parts) > 3 else ''
        assignments.append({
            'admin_id': admin_id,
            'role': role,
            'room_range_start': range_start,
            'room_range_end': range_end,
            'notes': notes[:500] or None
        })
    return assignments

def add_competition_assignments(competition, assignments, wave=None):
    added = []
    if not competition:
        return added
    for item in assignments:
        admin = db.session.get(User, item.get('admin_id'))
        if not admin or admin.role != 'admin':
            continue
        assignment = CompetitionAdminAssignment(
            competition_id=competition.id,
            wave_id=wave.id if wave else None,
            admin_id=admin.id,
            role=item.get('role') or 'room_admin',
            room_range_start=item.get('room_range_start'),
            room_range_end=item.get('room_range_end'),
            notes=item.get('notes')
        )
        db.session.add(assignment)
        added.append(assignment)
    return added

def rooms_for_assignment_scope(competition_id=None, wave_id=None, room_id=None, range_start=None, range_end=None):
    if room_id:
        room = db.session.get(Room, room_id)
        return [room] if room else []
    query = Room.query
    if competition_id:
        query = query.filter_by(competition_id=competition_id)
    if wave_id:
        query = query.filter_by(wave_id=wave_id)
    rooms = query.order_by(Room.created_at.asc(), Room.id.asc()).all()
    start = range_start or 1
    end = range_end or len(rooms)
    return [
        room for index, room in enumerate(rooms, start=1)
        if start <= index <= end
    ]

def serialize_admin_task(task):
    if not task:
        return {}
    assigned_rooms = rooms_for_assignment_scope(
        competition_id=task.competition_id,
        wave_id=task.wave_id,
        room_id=task.room_id,
        range_start=task.room_range_start,
        range_end=task.room_range_end
    )
    return {
        'id': task.id,
        'title': task.title,
        'description': task.description or '',
        'task_type': task.task_type,
        'priority': task.priority,
        'status': task.status,
        'competition_id': task.competition_id,
        'competition_name': task.competition.name if task.competition else '',
        'wave_id': task.wave_id,
        'wave_name': task.wave.name if task.wave else '',
        'room_id': task.room_id,
        'room_code': task.room.room_code if task.room else '',
        'room_range_start': task.room_range_start,
        'room_range_end': task.room_range_end,
        'room_count': len(assigned_rooms),
        'assigned_admin_id': task.assigned_admin_id,
        'assigned_admin_name': task.assigned_admin.username if task.assigned_admin else '',
        'created_by': task.created_by,
        'creator_name': task.creator.username if task.creator else '',
        'due_at': task.due_at or '',
        'created_at': task.created_at.isoformat() if task.created_at else '',
        'acknowledged': bool(task.acknowledged_at),
        'completed': bool(task.completed_at)
    }

def create_competition_room(challenge_id, competition=None, wave=None, player1_id=None, player2_id=None, is_public=False, status='waiting'):
    room = Room(
        room_code=generate_room_code(),
        challenge_id=challenge_id,
        status=status,
        player1_id=player1_id,
        player2_id=player2_id,
        is_public=is_public,
        competition_id=competition.id if competition else None,
        wave_id=wave.id if wave else None
    )
    db.session.add(room)
    return room

def is_auto_pair_competition(competition):
    return bool(competition and competition.format == 'auto_pair_live')

def is_auto_pair_room(room):
    competition = db.session.get(Competition, room.competition_id) if room and room.competition_id else None
    return bool(is_auto_pair_competition(competition))

def competition_player_ids(competition_id):
    ids = set()
    if not competition_id:
        return ids
    rooms = Room.query.filter_by(competition_id=competition_id).all()
    for room in rooms:
        if room.player1_id:
            ids.add(room.player1_id)
        if room.player2_id:
            ids.add(room.player2_id)
    return ids

def auto_pair_competition_codes(competition_id):
    if not competition_id:
        return set()
    return {
        (code or '').strip().upper()
        for (code,) in db.session.query(Room.room_code).filter_by(competition_id=competition_id).all()
        if code
    }

def set_auto_pair_competition_live(competition, wave=None):
    if not is_auto_pair_competition(competition):
        return
    competition.status = 'live'
    competition.stage = competition.stage or 'qualification'
    if wave:
        wave.status = 'live'

def room_player_payload(room, username=None, message=None):
    return {
        'room_id': room.id if room else None,
        'player1': room.player1.username if room and room.player1 else None,
        'player2': room.player2.username if room and room.player2 else None,
        'username': username,
        'message': message
    }

def emit_room_players(room, username=None, message=None):
    if not room:
        return
    payload = room_player_payload(room, username=username, message=message)
    socketio.emit('player_joined', payload, room=str(room.id))
    socketio.emit('player_list_update', payload, room=str(room.id))

def start_room_match(room, started_by=None):
    if not room or not room.challenge or room.status == 'ended':
        return False
    room.status = 'running'
    if started_by:
        room.started_by = started_by
    tournament_match = TournamentMatch.query.filter_by(room_id=room.id).first()
    if tournament_match and tournament_match.status == 'waiting':
        tournament_match.status = 'live'
    db.session.commit()
    start_room_timer_if_needed(room)
    return True

def find_or_create_auto_pair_room(source_room, user):
    competition = db.session.get(Competition, source_room.competition_id) if source_room and source_room.competition_id else None
    if not is_auto_pair_competition(competition):
        return source_room

    existing = Room.query.filter(
        Room.competition_id == competition.id,
        Room.status != 'ended',
        ((Room.player1_id == user.id) | (Room.player2_id == user.id))
    ).order_by(Room.created_at.desc(), Room.id.desc()).first()
    if existing:
        return existing

    current_players = competition_player_ids(competition.id)
    max_participants = max(1, int(competition.max_participants or 1))
    if len(current_players) >= max_participants:
        return None

    waiting_room = Room.query.filter(
        Room.competition_id == competition.id,
        Room.status == 'waiting',
        Room.player1_id.isnot(None),
        Room.player2_id.is_(None),
        Room.player1_id != user.id
    ).order_by(Room.created_at.asc(), Room.id.asc()).first()
    if waiting_room:
        return waiting_room

    empty_room = Room.query.filter(
        Room.competition_id == competition.id,
        Room.status == 'waiting',
        Room.player1_id.is_(None),
        Room.player2_id.is_(None)
    ).order_by(Room.created_at.asc(), Room.id.asc()).first()
    if empty_room:
        return empty_room

    wave = db.session.get(CompetitionWave, source_room.wave_id) if source_room and source_room.wave_id else None
    room = create_competition_room(
        competition.challenge_id,
        competition=competition,
        wave=wave,
        is_public=(competition.room_visibility == 'public'),
        status='waiting'
    )
    if wave:
        wave.rooms_created = (wave.rooms_created or 0) + 1
    db.session.flush()
    return room

def pair_players_for_rooms(players, pairing_method='ordered'):
    ordered_players = list(players or [])
    if pairing_method == 'seeded':
        ordered_players = []
        left = 0
        right = len(players) - 1
        while left <= right:
            ordered_players.append(players[left])
            if left != right:
                ordered_players.append(players[right])
            left += 1
            right -= 1
    return [
        (ordered_players[index], ordered_players[index + 1])
        for index in range(0, len(ordered_players) - 1, 2)
    ]

def build_my_assigned_rooms(admin_id):
    assignments = CompetitionAdminAssignment.query.filter_by(admin_id=admin_id).all()
    room_ids = []
    for assignment in assignments:
        query = Room.query.filter_by(competition_id=assignment.competition_id)
        if assignment.wave_id:
            query = query.filter_by(wave_id=assignment.wave_id)
        rooms = query.order_by(Room.created_at.asc(), Room.id.asc()).all()
        start = assignment.room_range_start or 1
        end = assignment.room_range_end or len(rooms)
        for index, room in enumerate(rooms, start=1):
            if start <= index <= end:
                room_ids.append(room.id)
    tasks = AdminTask.query.filter(
        AdminTask.assigned_admin_id == admin_id,
        AdminTask.status.in_(['open', 'acknowledged', 'active'])
    ).all()
    for task in tasks:
        for room in rooms_for_assignment_scope(
            competition_id=task.competition_id,
            wave_id=task.wave_id,
            room_id=task.room_id,
            range_start=task.room_range_start,
            range_end=task.room_range_end
        ):
            room_ids.append(room.id)
    if not room_ids:
        return []
    return Room.query.filter(Room.id.in_(sorted(set(room_ids)))).order_by(Room.created_at.desc()).all()

def build_admin_assignment_warnings(admin_id):
    watched_room_ids = {
        int(info.get('room_id'))
        for info in connected_users.values()
        if info.get('user_id') == admin_id and info.get('role') == 'admin' and info.get('room_id')
    }
    warnings = []
    assignments = CompetitionAdminAssignment.query.filter_by(admin_id=admin_id).all()
    for assignment in assignments:
        start = assignment.room_range_start or 1
        rooms = rooms_for_assignment_scope(assignment.competition_id, assignment.wave_id)
        end = assignment.room_range_end or len(rooms)
        assigned = [
            room for index, room in enumerate(rooms, start=1)
            if start <= index <= end and room.status in {'waiting', 'running', 'paused'}
        ]
        if assigned and not any(room.id in watched_room_ids for room in assigned):
            competition = db.session.get(Competition, assignment.competition_id)
            warnings.append({
                'assignment': assignment,
                'competition': competition,
                'room_count': len(assigned),
                'range': f'{start}-{end}',
                'message': f'You are assigned to {len(assigned)} active room(s) in range {start}-{end}, but you are not watching any of them right now.'
            })
    tasks = AdminTask.query.filter(
        AdminTask.assigned_admin_id == admin_id,
        AdminTask.status.in_(['open', 'acknowledged', 'active'])
    ).order_by(AdminTask.created_at.asc()).all()
    now_label = datetime.now().strftime('%Y-%m-%dT%H:%M')
    for task in tasks:
        task_rooms = [
            room for room in rooms_for_assignment_scope(
                competition_id=task.competition_id,
                wave_id=task.wave_id,
                room_id=task.room_id,
                range_start=task.room_range_start,
                range_end=task.room_range_end
            )
            if room.status in {'waiting', 'running', 'paused'}
        ]
        if task.status == 'open':
            warnings.append({
                'task': task,
                'competition': task.competition,
                'room_count': len(task_rooms),
                'range': f'{task.room_range_start or 1}-{task.room_range_end or len(task_rooms) or 1}',
                'message': f'You have not acknowledged task "{task.title}".'
            })
        if task.due_at and task.due_at < now_label and task.status != 'completed':
            warnings.append({
                'task': task,
                'competition': task.competition,
                'room_count': len(task_rooms),
                'range': f'{task.room_range_start or 1}-{task.room_range_end or len(task_rooms) or 1}',
                'message': f'Task "{task.title}" is overdue.'
            })
        if task_rooms and not any(room.id in watched_room_ids for room in task_rooms):
            warnings.append({
                'task': task,
                'competition': task.competition,
                'room_count': len(task_rooms),
                'range': f'{task.room_range_start or 1}-{task.room_range_end or len(task_rooms)}',
                'message': f'Task "{task.title}" covers {len(task_rooms)} active room(s), but you are not watching them.'
            })
    return warnings

def build_assignment_center_warnings():
    warnings = []
    assigned_competition_ids = {
        item.competition_id
        for item in CompetitionAdminAssignment.query.all()
        if item.competition_id
    }
    for competition in Competition.query.order_by(Competition.created_at.desc()).all():
        active_room_count = Room.query.filter(
            Room.competition_id == competition.id,
            Room.status.in_(['waiting', 'running', 'paused'])
        ).count()
        if active_room_count and competition.id not in assigned_competition_ids:
            warnings.append({
                'level': 'warning',
                'message': f'{competition.name} has {active_room_count} active room(s) with no admin assignment.'
            })
    now_label = datetime.now().strftime('%Y-%m-%dT%H:%M')
    for task in AdminTask.query.filter(AdminTask.status != 'completed').order_by(AdminTask.created_at.desc()).limit(80).all():
        if not task.assigned_admin_id:
            warnings.append({'level': 'warning', 'message': f'Task "{task.title}" has no assigned admin.'})
        if task.due_at and task.due_at < now_label:
            warnings.append({'level': 'danger', 'message': f'Task "{task.title}" is overdue.'})
    return warnings[:20]

def qualification_rows(competition_id=None, wave_id=None, limit=None):
    query = Room.query
    if competition_id:
        query = query.filter_by(competition_id=competition_id)
    if wave_id:
        query = query.filter_by(wave_id=wave_id)
    rooms = query.all()
    room_ids = [room.id for room in rooms]
    room_by_id = {room.id: room for room in rooms}
    player_ids = set()
    for room in rooms:
        if room.player1_id:
            player_ids.add(room.player1_id)
        if room.player2_id:
            player_ids.add(room.player2_id)
    submissions = Submission.query.filter(Submission.room_id.in_(room_ids)).all() if room_ids else []
    best_by_player = {}
    for sub in submissions:
        if not sub.user_id:
            continue
        player_ids.add(sub.user_id)
        current = best_by_player.get(sub.user_id)
        room = room_by_id.get(sub.room_id)
        if not current or submission_rank_tuple(sub, room.challenge if room else None) > submission_rank_tuple(current, room.challenge if room else None):
            best_by_player[sub.user_id] = sub
    disputes = DisputeCase.query
    if competition_id:
        disputes = disputes.filter_by(competition_id=competition_id)
    if wave_id:
        disputes = disputes.filter_by(wave_id=wave_id)
    warning_counts = {}
    disqualified = set()
    for dispute in disputes.all():
        if dispute.player_id:
            warning_counts[dispute.player_id] = warning_counts.get(dispute.player_id, 0) + 1
            if dispute.type == 'disqualification' or dispute.status == 'disqualified':
                disqualified.add(dispute.player_id)
    rows = []
    for player_id in player_ids:
        player = db.session.get(User, player_id)
        if not player:
            continue
        sub = best_by_player.get(player_id)
        room = room_by_id.get(sub.room_id) if sub else None
        accuracy, _details = submission_score_analysis(sub, room.challenge if room else None) if sub else (0.0, {})
        submitted_at = sub.submitted_at if sub else None
        rows.append({
            'user': player,
            'score': round(accuracy, 1),
            'completed': bool(sub and not sub.is_forfeit),
            'submitted_at': submitted_at,
            'submitted_at_value': datetime_sort_value(submitted_at),
            'fair_play_warnings': warning_counts.get(player_id, 0),
            'disqualified': player_id in disqualified or bool(sub and sub.is_forfeit),
            'room': room
        })
    rows.sort(key=lambda row: (
        not row['disqualified'],
        row['completed'],
        row['score'],
        -row['fair_play_warnings'],
        -row['submitted_at_value']
    ), reverse=True)
    for index, row in enumerate(rows, start=1):
        row['rank'] = index
    return rows[:limit] if limit else rows

def serialize_competition(competition):
    if not competition:
        return None
    rooms = Room.query.filter_by(competition_id=competition.id).all()
    disputes = DisputeCase.query.filter_by(competition_id=competition.id).all()
    waves = CompetitionWave.query.filter_by(competition_id=competition.id).order_by(CompetitionWave.created_at.asc()).all()
    assignments = CompetitionAdminAssignment.query.filter_by(competition_id=competition.id).order_by(CompetitionAdminAssignment.created_at.asc()).all()
    return {
        'id': competition.id,
        'name': competition.name,
        'format': competition.format,
        'stage': competition.stage,
        'status': competition.status,
        'challenge': competition.challenge.title if competition.challenge else None,
        'challenge_id': competition.challenge_id,
        'max_participants': competition.max_participants,
        'room_mode': competition.room_mode,
        'players_per_wave': competition.players_per_wave,
        'room_visibility': competition.room_visibility,
        'start_at': competition.start_at,
        'end_at': competition.end_at,
        'auto_start': bool(competition.auto_start),
        'auto_submit': bool(competition.auto_submit),
        'allowed_attempts': competition.allowed_attempts,
        'tie_break_rule': competition.tie_break_rule,
        'advance_rule': competition.advance_rule,
        'fair_play_strictness': competition.fair_play_strictness,
        'room_count': len(rooms),
        'dispute_count': len([case for case in disputes if case.status == 'open']),
        'waves': [
            {
                'id': wave.id,
                'name': wave.name,
                'status': wave.status,
                'start_at': wave.start_at,
                'end_at': wave.end_at,
                'players_expected': wave.players_expected,
                'rooms_created': wave.rooms_created
            }
            for wave in waves
        ],
        'assignments': [
            {
                'id': item.id,
                'admin_id': item.admin_id,
                'admin': item.admin.username if item.admin else 'Unknown admin',
                'role': item.role,
                'wave_id': item.wave_id,
                'wave': item.wave.name if item.wave else 'All waves',
                'room_range_start': item.room_range_start,
                'room_range_end': item.room_range_end,
                'notes': item.notes
            }
            for item in assignments
        ]
    }

def get_player_room_score(room_id, user_id):
    sub = get_best_room_submission(room_id, user_id)
    if not sub or sub.is_forfeit:
        return 0.0
    room = db.session.get(Room, room_id)
    accuracy, _details = submission_score_analysis(sub, room.challenge if room else None)
    return accuracy

def get_participant(tournament_id, user_id):
    return TournamentParticipant.query.filter_by(tournament_id=tournament_id, user_id=user_id).first()

def create_tournament_from_players(name, size, challenge_id, ordered_users, auto_advance=True, competition=None, created_by=None):
    tournament = Tournament(
        name=name,
        size=size,
        challenge_id=challenge_id,
        status='live',
        auto_advance=auto_advance,
        created_by=created_by,
        started_at=datetime.now(timezone.utc)
    )
    db.session.add(tournament)
    db.session.flush()

    for seed, player in enumerate(ordered_users, start=1):
        db.session.add(TournamentParticipant(
            tournament_id=tournament.id,
            user_id=player.id,
            seed=seed,
            status='active',
            position='Participant'
        ))

    seeded = []
    left = 0
    right = len(ordered_users) - 1
    while left <= right:
        seeded.append(ordered_users[left])
        if left != right:
            seeded.append(ordered_users[right])
        left += 1
        right -= 1

    round_name = tournament_round_name(size)
    for index in range(0, len(seeded), 2):
        create_tournament_match(
            tournament,
            1,
            round_name,
            (index // 2) + 1,
            seeded[index].id,
            seeded[index + 1].id,
            competition=competition
        )

    if competition:
        competition.tournament_id = tournament.id
        competition.status = 'bracket'
        competition.stage = 'bracket'
    return tournament

def certificate_type_for_position(position):
    if position == 'Champion':
        return 'champion'
    if position == 'Runner-up':
        return 'runner-up'
    if position == 'Semi-finalist':
        return 'semi-finalist'
    return 'participant'

def certificate_id_for(tournament_id, user_id):
    return f"UIBA-{tournament_id:04d}-{user_id:04d}-{secrets.token_hex(3).upper()}"

def create_tournament_room(tournament, player1_id=None, player2_id=None, competition=None, wave=None):
    room = Room(
        room_code=generate_room_code(),
        challenge_id=tournament.challenge_id,
        status='waiting',
        player1_id=player1_id,
        player2_id=player2_id,
        is_public=False,
        competition_id=competition.id if competition else None,
        wave_id=wave.id if wave else None
    )
    db.session.add(room)
    db.session.flush()
    return room

def create_tournament_match(tournament, round_number, round_name, match_number, player1_id, player2_id, competition=None, wave=None):
    room = create_tournament_room(tournament, player1_id, player2_id, competition=competition, wave=wave)
    match = TournamentMatch(
        tournament_id=tournament.id,
        round_number=round_number,
        round_name=round_name,
        match_number=match_number,
        room_id=room.id,
        player1_id=player1_id,
        player2_id=player2_id,
        status='waiting'
    )
    db.session.add(match)
    db.session.flush()
    return match

def log_admin_action(admin_id, action_type, reason, tournament_id=None, player_id=None, tournament_match_id=None, admin_note=None):
    action = AdminAction(
        admin_id=admin_id,
        action_type=action_type,
        reason=(reason or '').strip()[:200] or 'No reason provided',
        admin_note=(admin_note or '').strip() or None,
        tournament_id=tournament_id,
        tournament_match_id=tournament_match_id,
        player_id=player_id
    )
    db.session.add(action)
    return action

def serialize_tournament_match(match):
    room = match.room
    p1_score = get_player_room_score(room.id, match.player1_id) if room and match.player1_id else 0
    p2_score = get_player_room_score(room.id, match.player2_id) if room and match.player2_id else 0
    return {
        'id': match.id,
        'round_number': match.round_number,
        'round_name': match.round_name,
        'match_number': match.match_number,
        'status': match.status,
        'room_id': match.room_id,
        'room_code': room.room_code if room and room.is_public else None,
        'player1': match.player1.username if match.player1 else None,
        'player1_id': match.player1_id,
        'player1_score': p1_score,
        'player2': match.player2.username if match.player2 else None,
        'player2_id': match.player2_id,
        'player2_score': p2_score,
        'winner': match.winner.username if match.winner else None,
        'winner_id': match.winner_id,
        'manual_override': bool(match.is_manual_override)
    }

def serialize_tournament(tournament):
    matches = TournamentMatch.query.filter_by(tournament_id=tournament.id).order_by(
        TournamentMatch.round_number.asc(),
        TournamentMatch.match_number.asc()
    ).all()
    rounds = []
    for match in matches:
        if not rounds or rounds[-1]['round_number'] != match.round_number:
            rounds.append({'round_number': match.round_number, 'name': match.round_name, 'matches': []})
        rounds[-1]['matches'].append(serialize_tournament_match(match))

    participants = TournamentParticipant.query.filter_by(tournament_id=tournament.id).order_by(
        TournamentParticipant.seed.asc()
    ).all()
    participant_rows = [{
        'id': participant.id,
        'user_id': participant.user_id,
        'username': participant.user.username if participant.user else 'Player',
        'seed': participant.seed,
        'status': participant.status,
        'position': participant.position,
        'final_score': round(participant.final_score or 0, 1),
        'matches_played': participant.matches_played or 0,
        'certificate_id': participant.certificate_id,
        'reason': participant.reason,
        'admin_note': participant.admin_note
    } for participant in participants]
    try:
        certificate_settings = json.loads(tournament.certificate_settings or '{}')
    except (TypeError, json.JSONDecodeError):
        certificate_settings = {}

    return {
        'id': tournament.id,
        'name': tournament.name,
        'size': tournament.size,
        'status': tournament.status,
        'auto_advance': bool(tournament.auto_advance),
        'challenge': tournament.challenge.title if tournament.challenge else None,
        'created_at': tournament.created_at.isoformat() if tournament.created_at else None,
        'created_at_label': tournament.created_at.strftime('%Y-%m-%d') if tournament.created_at else '',
        'ended_at': tournament.ended_at.isoformat() if tournament.ended_at else None,
        'ended_at_label': tournament.ended_at.strftime('%Y-%m-%d') if tournament.ended_at else '',
        'certificate_settings': certificate_settings,
        'rounds': rounds,
        'participants': participant_rows
    }

def update_participant_from_result(tournament_id, user_id, score, status=None, position=None):
    participant = get_participant(tournament_id, user_id)
    if not participant:
        return
    participant.final_score = max(float(participant.final_score or 0), float(score or 0))
    participant.matches_played = MatchResult.query.join(TournamentMatch).filter(
        TournamentMatch.tournament_id == tournament_id,
        MatchResult.player_id == user_id
    ).count()
    if status:
        participant.status = status
    if position:
        participant.position = position

def save_match_result(match, player_id, score, is_winner, source='auto'):
    result = MatchResult.query.filter_by(tournament_match_id=match.id, player_id=player_id).first()
    if not result:
        result = MatchResult(
            tournament_match_id=match.id,
            room_id=match.room_id,
            player_id=player_id
        )
        db.session.add(result)
    result.score = round(float(score or 0), 1)
    result.is_winner = bool(is_winner)
    result.source = source
    result.created_at = datetime.now(timezone.utc)
    return result

def complete_tournament_match(match, winner_id, source='auto'):
    if not match or not winner_id:
        return False
    player_ids = [pid for pid in [match.player1_id, match.player2_id] if pid]
    if winner_id not in player_ids:
        return False
    scores = {pid: get_player_room_score(match.room_id, pid) for pid in player_ids}
    for pid in player_ids:
        save_match_result(match, pid, scores[pid], pid == winner_id, source)
    loser_ids = [pid for pid in player_ids if pid != winner_id]
    match.winner_id = winner_id
    match.status = 'completed'
    match.completed_at = datetime.now(timezone.utc)
    if source == 'manual':
        match.is_manual_override = True
    update_participant_from_result(match.tournament_id, winner_id, scores.get(winner_id, 0), status='active')
    for loser_id in loser_ids:
        update_participant_from_result(match.tournament_id, loser_id, scores.get(loser_id, 0), status='eliminated', position=match.round_name)
    maybe_advance_tournament(match.tournament)
    return True

def sync_tournament_match_for_room(room):
    match = TournamentMatch.query.filter_by(room_id=room.id).first()
    if not match or match.status in {'completed', 'disqualified'} or match.is_manual_override:
        return
    if not match.tournament or not match.tournament.auto_advance:
        return
    if room.status != 'ended':
        return
    player_ids = [pid for pid in [match.player1_id, match.player2_id] if pid]
    if len(player_ids) < 2:
        return
    winner_id = get_room_winner_id(room)
    if not winner_id:
        match.status = 'completed'
        return
    complete_tournament_match(match, winner_id, 'auto')

def maybe_advance_tournament(tournament):
    if not tournament:
        return
    current_round = db.session.query(func.max(TournamentMatch.round_number)).filter_by(tournament_id=tournament.id).scalar()
    current_matches = TournamentMatch.query.filter_by(tournament_id=tournament.id, round_number=current_round).all()
    if not current_matches or any(match.status != 'completed' or not match.winner_id for match in current_matches):
        socketio.emit('tournament_bracket_update', {'tournament': serialize_tournament(tournament)}, room=f"tournament_{tournament.id}")
        return

    winners = [match.winner_id for match in sorted(current_matches, key=lambda item: item.match_number)]
    if len(winners) == 1:
        champion_id = winners[0]
        tournament.status = 'completed'
        tournament.ended_at = datetime.now(timezone.utc)
        for participant in tournament.participants:
            if participant.user_id == champion_id:
                participant.status = 'champion'
                participant.position = 'Champion'
            elif participant.position == 'Finals':
                participant.position = 'Runner-up'
            elif participant.position == 'Semi Finals':
                participant.position = 'Semi-finalist'
            else:
                participant.position = participant.position or 'Participant'
            if not participant.certificate_id:
                participant.certificate_id = certificate_id_for(tournament.id, participant.user_id)
        socketio.emit('tournament_completed', {'tournament_id': tournament.id, 'winner_id': champion_id}, room=f"tournament_{tournament.id}")
        return

    next_round_number = current_round + 1
    round_name = tournament_round_name(len(winners))
    existing_next = TournamentMatch.query.filter_by(tournament_id=tournament.id, round_number=next_round_number).count()
    if existing_next:
        return
    for index in range(0, len(winners), 2):
        create_tournament_match(
            tournament,
            next_round_number,
            round_name,
            (index // 2) + 1,
            winners[index],
            winners[index + 1] if index + 1 < len(winners) else None
        )
    tournament.status = 'live'
    socketio.emit('tournament_advancement', {'tournament': serialize_tournament(tournament)}, room=f"tournament_{tournament.id}")

def update_user_stats(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return
    sync_user_competition_state(user)
    db.session.commit()

def profile_payload(user):
    profiles = load_profile_store()
    profile = profiles.get(str(user.id), {})
    data = user.to_dict()
    data['email'] = user.email or ''
    data['email_verified'] = bool(profile.get('email_verified'))
    data['bio'] = profile.get('bio', '')
    data['avatar_url'] = url_for('static', filename='uploads/' + profile['avatar_filename']) if profile.get('avatar_filename') else None
    return data

def load_profile_store():
    try:
        if os.path.exists(PROFILE_STORE):
            with open(PROFILE_STORE, 'r', encoding='utf-8') as handle:
                return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return {}

def save_profile_store(profiles):
    with open(PROFILE_STORE, 'w', encoding='utf-8') as handle:
        json.dump(profiles, handle, indent=2)

def get_certificate_template_settings():
    profiles = load_profile_store()
    saved = profiles.get('__certificate_template__', {})
    return normalize_certificate_settings(saved if isinstance(saved, dict) else {})

def save_certificate_template_settings(settings):
    profiles = load_profile_store()
    profiles['__certificate_template__'] = settings
    save_profile_store(profiles)

def load_password_reset_store():
    return load_profile_store().get('__password_resets__', {})

def save_password_reset_store(reset_store):
    profiles = load_profile_store()
    profiles['__password_resets__'] = reset_store
    save_profile_store(profiles)

def create_password_reset_code(user):
    code = f'{secrets.randbelow(1000000):06d}'
    reset_store = load_password_reset_store()
    reset_store[str(user.id)] = {
        'code_hash': generate_password_hash(code),
        'expires_at': int(time.time()) + 15 * 60,
        'created_at': int(time.time())
    }
    save_password_reset_store(reset_store)
    return code

def verify_password_reset_code(user, code):
    reset_store = load_password_reset_store()
    item = reset_store.get(str(user.id))
    if not item or int(item.get('expires_at') or 0) < int(time.time()):
        return False
    if not check_password_hash(item.get('code_hash') or '', re.sub(r'\s+', '', str(code or ''))):
        return False
    reset_store.pop(str(user.id), None)
    save_password_reset_store(reset_store)
    return True

def send_password_reset_email(user, code):
    return send_email(
        user.email,
        'UI Battle Arena password reset code',
        f'Your UI Battle Arena password reset code is {code}.\n\n'
        'It expires in 15 minutes. If you did not request this, ignore this email.'
    )

def is_email_verified(user):
    if not user or not user.email:
        return bool(user and user.role == 'player')
    return bool(load_profile_store().get(str(user.id), {}).get('email_verified'))

def create_email_verification_code(user):
    code = f'{secrets.randbelow(1000000):06d}'
    profiles, profile = get_profile_record(user.id)
    profile['email_verification_hash'] = generate_password_hash(code)
    profile['email_verification_expires_at'] = int(time.time()) + 15 * 60
    profile['email_verified'] = False
    save_profile_store(profiles)
    return code

def verify_email_code(user, code):
    profiles, profile = get_profile_record(user.id)
    if int(profile.get('email_verification_expires_at') or 0) < int(time.time()):
        return False
    if not check_password_hash(profile.get('email_verification_hash') or '', re.sub(r'\s+', '', str(code or ''))):
        return False
    profile['email_verified'] = True
    profile.pop('email_verification_hash', None)
    profile.pop('email_verification_expires_at', None)
    save_profile_store(profiles)
    return True

def send_email_verification(user):
    if not user or not user.email:
        return False
    code = create_email_verification_code(user)
    return send_email(
        user.email,
        'Verify your UI Battle Arena email',
        f'Your UI Battle Arena email verification code is {code}.\n\nIt expires in 15 minutes.'
    )

def begin_email_verification_login(user, message='Verification code sent to your email. Enter it to continue.'):
    if not user or not user.email:
        return jsonify({'success': False, 'error': 'This account has no email address to verify.'}), 400
    if not email_configured():
        return jsonify({'success': False, 'error': smtp_configuration_error()}), 400
    if rate_limited('email-verification-send', str(user.id), limit=10, window_seconds=15 * 60):
        return rate_limit_response('Too many verification code requests. Wait a few minutes and try again.')
    try:
        sent = send_email_verification(user)
    except Exception:
        app.logger.exception('Email verification send failed for user %s', user.id)
        sent = False
    if not sent:
        return jsonify({'success': False, 'error': 'Could not send verification code. Check Mailjet/SMTP settings and try again.'}), 500
    csrf_token = session.get('csrf_token')
    session.clear()
    session['csrf_token'] = csrf_token or secrets.token_urlsafe(32)
    session['pending_email_verification_user_id'] = user.id
    return jsonify({
        'success': False,
        'requires_2fa': True,
        'email_verification': True,
        'message': message
    })

def notify_users_by_email(users, subject, body, only_verified=True):
    sent = 0
    for target in users:
        if not target or not target.email:
            continue
        if only_verified and not is_email_verified(target):
            continue
        try:
            if send_email(target.email, subject, body):
                sent += 1
        except Exception:
            app.logger.exception('Email notification failed for user %s', target.id)
    return sent

def get_profile_record(user_id):
    profiles = load_profile_store()
    return profiles, profiles.setdefault(str(user_id), {'bio': '', 'avatar_filename': None})

ARENA_CONTACT_PHONE = '+254791305329'
ARENA_CONTACT_EMAILS = ['uibattlearena@gmail.com', 'oxygenvessels@gmail.com']

DEFAULT_SITE_CONTENT = {
    'about': {
        'hero_title': 'UI Battle Arena',
        'hero_subtitle': 'A live coding arena where students recreate real interfaces, compete fairly, and improve through output-based scoring.',
        'body': (
            'UI Battle Arena is built for practical frontend practice. Students join live rooms, rebuild a target interface with HTML, CSS, and JavaScript, and receive a score based on the rendered output, visual closeness, CSS details, and clean implementation.\n\n'
            'The arena supports one-on-one battles, spectators, tournaments, certificates, profile awards, admin moderation, room chat, camera checks, and live scoreboards. The goal is not to force every student to write the same code. A student can use Bootstrap, custom CSS, or another reasonable approach as long as the final output matches the target.\n\n'
            'Admins can create challenges, monitor rooms, review messages, manage tournaments, publish public site pages, send maintenance notices, and keep student progress visible and reliable.'
        ),
        'contact_email': ARENA_CONTACT_EMAILS[0],
        'nav_label': 'About',
        'visible': True,
        'placements': ['footer'],
        'layout_style': 'standard',
        'carousel_mode': 'infinite',
        'media_effects': ['scroll', 'hover'],
        'text_effect': 'fade',
        'contact_items': [],
        'links': [],
        'images': [],
        'videos': []
    },
    'support': {
        'hero_title': 'Support',
        'hero_subtitle': 'Get help with login access, match rooms, scoring reviews, certificates, media permissions, and tournament setup.',
        'body': (
            'Use support when something blocks your participation or needs organizer attention. Helpful details include your username, room code, opponent name, browser, device, and a short explanation of what happened.\n\n'
            'Common support cases include account login trouble, email verification, camera or microphone permissions, joining a match, a score that does not look correct, missing certificates, tournament placement questions, and broken page content.\n\n'
            'For urgent arena issues, use the Report page. For suggestions or general improvements, use Feedback.'
        ),
        'contact_email': ARENA_CONTACT_EMAILS[0],
        'nav_label': 'Support',
        'visible': True,
        'placements': ['footer'],
        'layout_style': 'contact',
        'text_effect': 'fade',
        'contact_items': [
            {'label': 'UI Battle Arena email', 'value': ARENA_CONTACT_EMAILS[0], 'kind': 'email', 'url': f'mailto:{ARENA_CONTACT_EMAILS[0]}'},
            {'label': 'Oxygen Vessels email', 'value': ARENA_CONTACT_EMAILS[1], 'kind': 'email', 'url': f'mailto:{ARENA_CONTACT_EMAILS[1]}'},
            {'label': 'WhatsApp / phone support', 'value': ARENA_CONTACT_PHONE, 'kind': 'whatsapp', 'url': 'https://wa.me/254791305329'}
        ],
        'links': [
            {'label': 'Feedback', 'url': '/feedback'},
            {'label': 'Report a problem', 'url': '/report'},
            {'label': 'Dashboard', 'url': '/dashboard'}
        ],
        'images': [],
        'videos': []
    },
    'terms': {
        'hero_title': 'Terms and Conditions',
        'hero_subtitle': 'Fair play, respectful chat, and responsible use keep the arena trustworthy.',
        'body': (
            'By using UI Battle Arena, you agree to compete honestly, respect other users, and follow admin instructions during rooms, tournaments, and public chat.\n\n'
            'Fair play means submitting your own work, avoiding harmful scripts, not attacking the platform, and not trying to manipulate score storage, timers, camera checks, chat, or leaderboard data. You may use normal frontend tools and frameworks when a challenge allows it, but your marks come from how closely the final output matches the target and how cleanly the submission behaves.\n\n'
            'During arena matches, players MUST NOT RIGHT CLICK OR THEY ARE DISQUALIFIED. Players must not right-click, open Inspect, view page source, use developer tools, or use browser inspection shortcuts to look for hints in the target or page code. Those actions are prohibited for players because they can reveal implementation clues that should be earned through visual analysis.\n\n'
            'Respectful conduct is required. Harassment, threats, abusive language, impersonation, spam, cheating, and unsafe content may lead to warnings, room removal, disqualification, account restrictions, or data reset by an admin.\n\n'
            'Admins may review feedback, reports, match records, submissions, scores, certificates, media settings, and chat messages to operate the arena. Maintenance may temporarily interrupt access when updates or resets are needed.\n\n'
            'For questions about these terms, contact the arena team.'
        ),
        'contact_email': ARENA_CONTACT_EMAILS[0],
        'nav_label': 'Terms',
        'visible': True,
        'placements': ['footer'],
        'layout_style': 'document',
        'text_effect': 'fade',
        'contact_items': [],
        'links': [],
        'images': [],
        'videos': []
    },
    'contact': {
        'hero_title': 'Contact',
        'hero_subtitle': 'Reach the UI Battle Arena team for support, tournaments, scoring reviews, and urgent room issues.',
        'body': (
            'Use these contacts for account access, match support, score reviews, tournament coordination, certificates, site content, sponsorship, or partnership questions.\n\n'
            'When reporting a live match issue, include the room code, your username, the opponent username, and what you expected to happen.'
        ),
        'contact_email': ARENA_CONTACT_EMAILS[0],
        'nav_label': 'Contact',
        'visible': True,
        'placements': ['footer'],
        'layout_style': 'contact',
        'text_effect': 'slide',
        'contact_items': [
            {'label': 'UI Battle Arena', 'value': ARENA_CONTACT_EMAILS[0], 'kind': 'email', 'url': f'mailto:{ARENA_CONTACT_EMAILS[0]}'},
            {'label': 'Oxygen Vessels', 'value': ARENA_CONTACT_EMAILS[1], 'kind': 'email', 'url': f'mailto:{ARENA_CONTACT_EMAILS[1]}'},
            {'label': 'Phone / WhatsApp', 'value': ARENA_CONTACT_PHONE, 'kind': 'whatsapp', 'url': 'https://wa.me/254791305329'}
        ],
        'links': [
            {'label': 'Feedback', 'url': '/feedback'},
            {'label': 'Report a problem', 'url': '/report'},
            {'label': 'Help Center', 'url': '/help'}
        ],
        'images': [],
        'videos': []
    },
    'help': {
        'hero_title': 'Help Center',
        'hero_subtitle': 'Quick guidance for joining rooms, submitting code, and understanding results.',
        'body': (
            'Joining a match: log in, open the dashboard, join an available room or invite link, and wait for the admin or room state to start the challenge. Allow camera and microphone when required by your organizer.\n\n'
            'Building your answer: use the editor to write HTML, CSS, and JavaScript. Your code does not need to be identical to another student or to the admin source. What matters is the final rendered output, including layout, spacing, colors, typography, borders, radius, and interaction behavior.\n\n'
            'Submitting: use Submit & Check before time runs out. The arena saves your trusted score and score details so progress remains stable after refresh. If your screen freezes or you lose connection, rejoin the room and submit again if the match is still active.\n\n'
            'Fair play: players MUST NOT RIGHT CLICK OR THEY ARE DISQUALIFIED. Players must not use Inspect, view page source, or use developer-tool shortcuts during arena matches. The target should be studied visually, not by reading page code or hidden hints.\n\n'
            'Understanding scores: the score compares the output against the target and also checks important CSS groups such as typography, color, layout, spacing, shape, and alignment. Small details like borders, shadows, and radius can move your percentage.\n\n'
            'Need help: send Feedback for suggestions and non-urgent issues. Use Report for urgent scoring, safety, access, or tournament problems.'
        ),
        'contact_email': ARENA_CONTACT_EMAILS[0],
        'nav_label': 'Help',
        'visible': True,
        'placements': ['footer'],
        'layout_style': 'help',
        'text_effect': 'fade',
        'contact_items': [],
        'links': [
            {'label': 'Editor Shortcuts', 'url': '/shortcuts'},
            {'label': 'Dashboard', 'url': '/dashboard'},
            {'label': 'Leaderboard', 'url': '/leaderboard'},
            {'label': 'Support', 'url': '/support'}
        ],
        'images': [],
        'videos': []
    },
    'competition_guide': {
        'hero_title': 'Competition Guide',
        'hero_subtitle': 'Run large contests by placing an organizer layer above many simultaneous 1v1 arena rooms.',
        'body': (
            'Official rule: A competition may contain many simultaneous 1v1 arena rooms. Each arena room has exactly two active players. For large competitions, players first compete in qualification waves. The highest-ranked players advance to a knockout bracket. Admins are assigned to supervise groups of rooms, review disputes, and confirm winners.\n\n'
            'How it works: one arena match remains 2 players only. A bracket round creates one room per pair. For 32 players, the round of 32 creates 16 rooms at the same time, the round of 16 creates 8 rooms, quarterfinals create 4 rooms, semifinals create 2 rooms, and the final creates 1 room.\n\n'
            'For 1000 players: do not run one giant room or one pair after another. Use qualification waves first. Example: register 1000 students, split them into waves of about 100, run many rooms or score-based attempts in parallel, rank by score, completion, time, and fair-play status, then move the top 32 or 64 into the official knockout bracket.\n\n'
            'Recommended execution: create the qualification challenge, register students, split them into waves, create rooms in bulk, start each wave, let auto-scoring rank first, send disputed scores and cheating alerts to review, publish the qualifier leaderboard, create the final bracket, run every bracket round in parallel, and have senior admins watch the final.\n\n'
            'Admin roles: the tournament director starts rounds and makes final decisions. Room admins supervise groups of rooms. Fair play admins review right-click, inspect, camera, microphone, and suspicious behavior alerts. Scoring admins handle close matches and manual overrides. Support admins solve login, wrong-room, device, and network problems. Certificate admins confirm names, winners, and awards.\n\n'
            'Practical staffing: one experienced room admin can watch about 5 to 20 rooms depending on screen setup and strictness. For 1000 students, plan for about 10 to 30 admins or helpers if live supervision is serious.\n\n'
            'Features to add next: large tournament mode, qualifier plus bracket competitions, automatic pairing, wave management, admin-to-room assignment, supervisor dashboards, bulk room creation, qualification leaderboard, dispute queue, and contest stage statuses such as Registration, Qualification, Review, Bracket, Finals, and Completed.'
        ),
        'contact_email': ARENA_CONTACT_EMAILS[0],
        'nav_label': 'Competition Guide',
        'visible': True,
        'placements': ['public', 'dashboard', 'arena', 'profile', 'footer'],
        'layout_style': 'help',
        'text_effect': 'fade',
        'contact_items': [],
        'links': [
            {'label': 'Create Tournament', 'url': '/tournament'},
            {'label': 'Admin Console', 'url': '/admin'},
            {'label': 'Help Center', 'url': '/help'},
            {'label': 'Report a Problem', 'url': '/report'}
        ],
        'images': [],
        'videos': []
    },
    'feedback': {
        'hero_title': 'Feedback',
        'hero_subtitle': 'Tell the organizers what is broken, confusing, or worth improving.',
        'body': (
            'Use this form for suggestions, confusing workflows, page content corrections, scoring concerns, or ideas that would make the arena better for students.\n\n'
            'Every feedback message is saved in the admin panel and emailed to the arena team. Include a room code when your feedback is about a specific match.'
        ),
        'contact_email': ARENA_CONTACT_EMAILS[0],
        'nav_label': 'Feedback',
        'visible': True,
        'placements': ['footer'],
        'layout_style': 'feedback',
        'text_effect': 'scale',
        'contact_items': [],
        'links': [],
        'images': [],
        'videos': []
    },
    'report': {
        'hero_title': 'Report a Problem',
        'hero_subtitle': 'Send urgent match, scoring, safety, or access issues to the arena admins.',
        'body': (
            'Use this page for problems that need admin review: unfair scores, room access issues, harassment, harmful chat, broken pages, missing tournament results, certificate mistakes, or suspicious behavior.\n\n'
            'Reports are saved in the admin panel and emailed to the arena team. Include the room code, usernames, time of the issue, and what happened.'
        ),
        'contact_email': ARENA_CONTACT_EMAILS[0],
        'nav_label': 'Report',
        'visible': True,
        'placements': ['footer'],
        'layout_style': 'feedback',
        'text_effect': 'slide',
        'contact_items': [],
        'links': [
            {'label': 'Help Center', 'url': '/help'},
            {'label': 'Contact', 'url': '/contact'}
        ],
        'images': [],
        'videos': []
    },
    'maintenance_notice': {
        'enabled': False,
        'title': 'Scheduled maintenance',
        'message': 'UI Battle Arena may be paused for updates, score improvements, content changes, or database maintenance. Save any work you need before the maintenance window and return after the release time.',
        'maintenance_at': '',
        'release_at': '',
        'email_users': False
    }
}

def get_site_content():
    profiles = load_profile_store()
    saved = profiles.get('__site_content__', {})
    content = json.loads(json.dumps(DEFAULT_SITE_CONTENT))
    if isinstance(saved, dict):
        for key, value in saved.items():
            if isinstance(value, dict) and isinstance(content.get(key), dict):
                content[key].update(value)
            else:
                content[key] = value
    return content

def save_site_content(content):
    profiles = load_profile_store()
    profiles['__site_content__'] = content
    save_profile_store(profiles)

def refresh_builtin_site_content():
    profiles = load_profile_store()
    saved = profiles.get('__site_content__')
    if not isinstance(saved, dict):
        return
    changed = False
    old_fragments = (
        'support@example.com',
        '+1 000 000 0000',
        'A live coding arena for fair UI challenges',
        'Contact the organizer if you cannot join a room',
        'Do not cheat, harass other users',
        'Use the contacts below for account access',
        'Join an active room from the dashboard',
        'Send match issues, UI suggestions',
        'Use this page for problems that need admin review'
    )
    for section in SITE_PAGE_KEYS:
        current = saved.get(section)
        default = DEFAULT_SITE_CONTENT.get(section)
        if not isinstance(current, dict) or not isinstance(default, dict):
            continue
        current_text = json.dumps(current, sort_keys=True)
        should_refresh = any(fragment in current_text for fragment in old_fragments)
        should_refresh = should_refresh or not str(current.get('body') or '').strip()
        if should_refresh:
            merged = json.loads(json.dumps(default))
            for media_key in ['images', 'videos']:
                if current.get(media_key):
                    merged[media_key] = current.get(media_key)
            saved[section] = merged
            changed = True
    notice = saved.get('maintenance_notice')
    if isinstance(notice, dict) and (
        not str(notice.get('message') or '').strip()
        or 'The arena will be updated soon' in str(notice.get('message') or '')
    ):
        saved['maintenance_notice'] = json.loads(json.dumps(DEFAULT_SITE_CONTENT['maintenance_notice']))
        changed = True
    required_policy = 'During arena matches, players MUST NOT RIGHT CLICK OR THEY ARE DISQUALIFIED. Players must not right-click, open Inspect, view page source, use developer tools, or use browser inspection shortcuts to look for hints in the target or page code.'
    terms = saved.get('terms')
    if isinstance(terms, dict) and required_policy not in str(terms.get('body') or ''):
        terms['body'] = (str(terms.get('body') or DEFAULT_SITE_CONTENT['terms']['body']).rstrip() + '\n\n' + required_policy)
        changed = True
    help_policy = 'Fair play: players MUST NOT RIGHT CLICK OR THEY ARE DISQUALIFIED. Players must not use Inspect, view page source, or use developer-tool shortcuts during arena matches. The target should be studied visually, not by reading page code or hidden hints.'
    help_page = saved.get('help')
    if isinstance(help_page, dict) and help_policy not in str(help_page.get('body') or ''):
        help_page['body'] = (str(help_page.get('body') or DEFAULT_SITE_CONTENT['help']['body']).rstrip() + '\n\n' + help_policy)
        changed = True
    if changed:
        profiles['__site_content__'] = saved
        save_profile_store(profiles)

SITE_PAGE_KEYS = ['about', 'support', 'terms', 'contact', 'help', 'competition_guide', 'feedback', 'report']
SITE_PAGE_PLACEMENTS = ['public', 'dashboard', 'arena', 'profile', 'footer']

def site_page_url(page_key):
    endpoint = {
        'about': 'about_page',
        'support': 'support_page',
        'terms': 'terms_page',
        'contact': 'contact_page',
        'help': 'help_page',
        'competition_guide': 'competition_guide_page',
        'feedback': 'feedback_page',
        'report': 'report_page'
    }.get(page_key)
    return url_for(endpoint) if endpoint else '#'

def contact_href(item):
    item = item if isinstance(item, dict) else {}
    url = str(item.get('url') or '').strip()
    value = str(item.get('value') or '').strip()
    kind = str(item.get('kind') or '').strip().lower()
    target = url or value
    if not target:
        return '#'
    if re.match(r'^(mailto:|tel:|https?://|/)', target, re.I):
        return target
    if kind == 'email' or valid_email(target):
        return f'mailto:{target}'
    phone_digits = re.sub(r'\D+', '', target)
    if kind in {'phone', 'whatsapp'} and phone_digits:
        return f'https://wa.me/{phone_digits}' if kind == 'whatsapp' else f'tel:+{phone_digits}'
    return target

def email_href(value):
    email = str(value or '').strip()
    if not email:
        return '#'
    return email if email.lower().startswith('mailto:') else f'mailto:{email}'

def site_mail_recipients(preferred=None):
    recipients = []
    for email in [preferred, *ARENA_CONTACT_EMAILS, configured_admin_email()]:
        clean = valid_email(email)
        if clean and clean not in recipients:
            recipients.append(clean)
    return recipients

def load_feedback_messages(limit=250):
    profiles = load_profile_store()
    rows = profiles.setdefault('__feedback_messages__', [])
    changed = False
    for row in rows:
        if isinstance(row, dict) and not row.get('id'):
            row['id'] = uuid.uuid4().hex
            changed = True
        if isinstance(row, dict) and 'replies' not in row:
            row['replies'] = []
            changed = True
    if changed:
        profiles['__feedback_messages__'] = rows[:250]
        save_profile_store(profiles)
    return rows[:limit]

def save_feedback_message(row):
    profiles = load_profile_store()
    rows = profiles.setdefault('__feedback_messages__', [])
    rows.insert(0, row)
    profiles['__feedback_messages__'] = rows[:250]
    save_profile_store(profiles)
    return row

def update_feedback_message(message_id, updater):
    profiles = load_profile_store()
    rows = profiles.setdefault('__feedback_messages__', [])
    for row in rows:
        if isinstance(row, dict) and row.get('id') == message_id:
            updater(row)
            profiles['__feedback_messages__'] = rows[:250]
            save_profile_store(profiles)
            return row
    return None

def visible_site_pages(surface='footer'):
    content = get_site_content()
    rows = []
    for key in SITE_PAGE_KEYS:
        page = content.get(key, {})
        placements = page.get('placements') if isinstance(page.get('placements'), list) else []
        if page.get('visible', True) and (surface in placements or 'all' in placements):
            rows.append({
                'key': key,
                'label': page.get('nav_label') or page.get('hero_title') or key.title(),
                'url': site_page_url(key)
            })
    return rows

def normalize_site_content_payload(data):
    current = get_site_content()
    for section in SITE_PAGE_KEYS:
        source = data.get(section) if isinstance(data.get(section), dict) else {}
        target = current.setdefault(section, {})
        for key in ['hero_title', 'hero_subtitle', 'body', 'contact_email', 'carousel_mode', 'text_effect', 'nav_label', 'layout_style']:
            if key in source:
                target[key] = str(source.get(key) or '')[:5000]
        if 'visible' in source:
            target['visible'] = bool(source.get('visible'))
        placements = source.get('placements')
        if isinstance(placements, list):
            allowed = set(SITE_PAGE_PLACEMENTS + ['all'])
            target['placements'] = [str(item) for item in placements if str(item) in allowed][:8]
        effects = source.get('media_effects')
        if isinstance(effects, list):
            target['media_effects'] = [str(item)[:40] for item in effects if str(item).strip()][:8]
        for media_key in ['images', 'videos', 'links', 'contact_items']:
            items = source.get(media_key)
            if isinstance(items, list):
                target[media_key] = [
                    {
                        'label': str(item.get('label') or '')[:120],
                        'value': str(item.get('value') or '')[:240],
                        'kind': str(item.get('kind') or '')[:40],
                        'url': str(item.get('url') or '')[:1000],
                        'caption': str(item.get('caption') or '')[:240],
                        'effect': str(item.get('effect') or '')[:40],
                        'start_time': str(item.get('start_time') or '')[:40],
                        'duration': str(item.get('duration') or '')[:40]
                    }
                    for item in items if isinstance(item, dict) and (str(item.get('url') or '').strip() or str(item.get('value') or '').strip())
                ][:12]
    notice = data.get('maintenance_notice') if isinstance(data.get('maintenance_notice'), dict) else {}
    current['maintenance_notice'] = {
        'enabled': bool(notice.get('enabled')),
        'title': str(notice.get('title') or 'Scheduled maintenance')[:160],
        'message': str(notice.get('message') or '')[:1500],
        'maintenance_at': str(notice.get('maintenance_at') or '')[:80],
        'release_at': str(notice.get('release_at') or '')[:80],
        'email_users': bool(notice.get('email_users'))
    }
    return current

def get_profile_view_data(user_id):
    profile = load_profile_store().get(str(user_id), {})
    avatar_filename = profile.get('avatar_filename')
    return {
        'bio': profile.get('bio', ''),
        'avatar_url': url_for('static', filename='uploads/' + avatar_filename) if avatar_filename else None
    }

def remove_profile_record(user_id):
    profiles = load_profile_store()
    if str(user_id) in profiles:
        profiles.pop(str(user_id), None)
        save_profile_store(profiles)

def remove_upload_file(filename):
    if not filename:
        return False
    upload_root = os.path.abspath(app.config['UPLOAD_FOLDER'])
    upload_path = os.path.abspath(os.path.join(upload_root, filename))
    if not upload_path.startswith(upload_root) or not os.path.exists(upload_path):
        return False
    try:
        os.remove(upload_path)
        return True
    except OSError:
        return False

def clear_created_platform_data():
    admin_ids = {user.id for user in User.query.filter_by(role='admin').all()}
    profiles = load_profile_store()
    deleted_user_ids = {user.id for user in User.query.filter(User.role != 'admin').all()}
    protected_uploads = {
        profile.get('avatar_filename')
        for user_id, profile in profiles.items()
        if user_id.isdigit() and int(user_id) in admin_ids and profile.get('avatar_filename')
    }
    upload_filenames = {
        challenge.target_image_path
        for challenge in Challenge.query.all()
        if challenge.target_image_path
    }
    upload_filenames.update(
        profile.get('avatar_filename')
        for user_id, profile in profiles.items()
        if user_id.isdigit() and int(user_id) in deleted_user_ids and profile.get('avatar_filename')
    )
    upload_filenames = {name for name in upload_filenames if name and name not in protected_uploads}

    User.query.filter_by(role='admin').update({
        User.matches_played: 0,
        User.best_accuracy: 0,
        User.total_wins: 0,
        User.leaderboard_unlocked_at: None,
        User.leaderboard_awarded: False,
        User.leaderboard_awarded_at: None,
        User.leaderboard_awarded_by: None,
        User.leaderboard_award_reason: None,
        User.leaderboard_award_details: None,
        User.leaderboard_award_color: None
    }, synchronize_session=False)

    counts = {
        'admin_actions': AdminAction.query.delete(synchronize_session=False),
        'match_results': MatchResult.query.delete(synchronize_session=False),
        'tournament_participants': TournamentParticipant.query.delete(synchronize_session=False),
        'tournament_matches': TournamentMatch.query.delete(synchronize_session=False),
        'admin_tasks': AdminTask.query.delete(synchronize_session=False),
        'competition_admin_assignments': CompetitionAdminAssignment.query.delete(synchronize_session=False),
        'dispute_cases': DisputeCase.query.delete(synchronize_session=False),
        'competition_waves': CompetitionWave.query.delete(synchronize_session=False),
        'award_cards': AwardCard.query.delete(synchronize_session=False),
        'submissions': Submission.query.delete(synchronize_session=False),
        'chat_messages': ChatMessage.query.delete(synchronize_session=False),
        'room_access': RoomAccess.query.delete(synchronize_session=False),
        'rooms': Room.query.delete(synchronize_session=False),
        'competitions': Competition.query.delete(synchronize_session=False),
        'tournaments': Tournament.query.delete(synchronize_session=False),
        'challenges': Challenge.query.delete(synchronize_session=False),
        'students': User.query.filter(User.role != 'admin').delete(synchronize_session=False)
    }

    save_profile_store({
        user_id: profile
        for user_id, profile in profiles.items()
        if user_id.isdigit() and int(user_id) in admin_ids
    })

    room_timers.clear()
    room_preview_data.clear()
    room_spectators.clear()
    room_typing_users.clear()

    db.session.commit()
    counts['uploaded_files'] = sum(1 for filename in upload_filenames if remove_upload_file(filename))
    return counts

def sync_users_by_id(user_ids):
    for user_id in {uid for uid in user_ids if uid}:
        user = db.session.get(User, user_id)
        if user:
            sync_user_competition_state(user)

def delete_room_data(room):
    affected_user_ids = {room.player1_id, room.player2_id}
    RoomAccess.query.filter_by(room_id=room.id).delete(synchronize_session=False)
    MatchResult.query.filter_by(room_id=room.id).delete(synchronize_session=False)
    Submission.query.filter_by(room_id=room.id).delete()
    ChatMessage.query.filter_by(room_id=room.id).delete()
    DisputeCase.query.filter_by(room_id=room.id).delete(synchronize_session=False)
    AdminTask.query.filter_by(room_id=room.id).update(
        {'room_id': None, 'status': 'open'},
        synchronize_session=False
    )
    TournamentMatch.query.filter_by(room_id=room.id).update(
        {'room_id': None, 'status': 'waiting'},
        synchronize_session=False
    )
    room_timers.pop(room.id, None)
    room_preview_data.pop(room.id, None)
    room_spectators.pop(room.id, None)
    db.session.delete(room)
    return affected_user_ids

@app.context_processor
def inject_current_profile():
    context = {
        'csrf_token': get_csrf_token(),
        'visible_site_pages': visible_site_pages,
        'contact_href': contact_href,
        'email_href': email_href
    }
    user_id = session.get('user_id')
    if not user_id:
        return context
    profile = load_profile_store().get(str(user_id), {})
    avatar_filename = profile.get('avatar_filename')
    context['current_profile'] = {
        'bio': profile.get('bio', ''),
        'email_verified': bool(profile.get('email_verified')),
        'avatar_url': url_for('static', filename='uploads/' + avatar_filename) if avatar_filename else None
    }
    return context

@app.before_request
def ensure_runtime_schema():
    ensure_schema_upgrades()
    csrf_response = verify_csrf_request()
    if csrf_response:
        return csrf_response

def run_room_timer(room_id):
    with app.app_context():
        while room_timers.get(room_id, 0) > 0:
            room = db.session.get(Room, room_id)
            if not room or room.status == 'ended':
                break
            if room.status == 'paused':
                time.sleep(1)
                continue
            socketio.emit('timer_tick', {'remaining': room_timers[room_id]}, room=str(room_id))
            if room_timers.get(room_id, 0) > 0:
                room_timers[room_id] -= 1
            time.sleep(1)
        
        room = db.session.get(Room, room_id)
        if room and room.status == 'running':
            room.status = 'ended'
            room.ended_at = datetime.now(timezone.utc)
            finalize_room_results(room)
            db.session.commit()
    socketio.emit('challenge_ended', {'room_id': room_id}, room=str(room_id))

def start_room_timer_if_needed(room):
    if not room or not room.challenge:
        return
    if room.id not in room_timers or room_timers.get(room.id, 0) <= 0:
        room_timers[room.id] = room.challenge.time_limit
    socketio.emit('challenge_started', {
        'room_id': room.id,
        'time_limit': room.challenge.time_limit,
        'challenge_title': room.challenge.title
    }, room=str(room.id))
    thread = threading.Thread(target=run_room_timer, args=(room.id,))
    thread.daemon = True
    thread.start()

def emit_challenge_paused(room):
    if not room:
        return
    socketio.emit('challenge_paused', {
        'room_id': room.id,
        'remaining': room_timers.get(room.id, 0),
        'message': 'Match paused by admin'
    }, room=str(room.id))

def emit_challenge_resumed(room):
    if not room:
        return
    challenge = room.challenge
    socketio.emit('challenge_resumed', {
        'room_id': room.id,
        'remaining': room_timers.get(room.id, 0),
        'challenge_type': challenge.challenge_type if challenge else None,
        'html_locked': bool(challenge.html_locked) if challenge else False
    }, room=str(room.id))

def broadcast_leaderboard(room_id):
    submissions = Submission.query.filter_by(room_id=room_id, is_final=False).all()
    submission_dict = {}
    for sub in submissions:
        if sub.user and sub.user.role == 'player':
            username = sub.user.username
            if username not in submission_dict or sub.accuracy > submission_dict[username]['accuracy']:
                submission_dict[username] = {'accuracy': sub.accuracy, 'username': username}
    
    players = sorted(submission_dict.values(), key=lambda x: x['accuracy'], reverse=True)
    for i, p in enumerate(players):
        p['rank'] = i + 1
        p['accuracy'] = round(p['accuracy'], 1)
    
    socketio.emit('leaderboard_update', {'players': players[:10]}, room=str(room_id))

# ========== AUTH ROUTES ==========
@app.route('/')
def login_page():
    return render_template(
        'login.html',
        challenge_count=Challenge.query.filter_by(is_active=True).count(),
        google_oauth_enabled=google_oauth_configured(),
        pending_two_factor=bool(session.get('pending_2fa_user_id') or session.get('pending_email_otp_user_id') or session.get('pending_email_verification_user_id')),
        pending_email_code=bool(session.get('pending_email_otp_user_id') or session.get('pending_email_verification_user_id')),
        pending_can_use_qr_setup=bool(session.get('pending_email_otp_user_id'))
    )

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    
    user = find_login_user(username)
    password_ok = bool(user and user.check_password(password))
    if not password_ok and rate_limited('login', username or client_rate_identity(), limit=8, window_seconds=15 * 60):
        return rate_limit_response()

    if password_ok:
        if not admin_login_uses_email(user, username):
            return jsonify({'success': False, 'error': 'Admin login requires the admin email address'}), 401
        if user.role == 'admin':
            bind_admin_login_email(user, username)
            email_otp_response = begin_admin_email_otp_login(user)
            if email_otp_response:
                return email_otp_response
            if user.two_factor_enabled:
                csrf_token = session.get('csrf_token')
                session.clear()
                session['csrf_token'] = csrf_token or secrets.token_urlsafe(32)
                session['pending_2fa_user_id'] = user.id
                return jsonify({'success': False, 'requires_2fa': True, 'message': 'Enter your admin authenticator or recovery code.'})
            return jsonify(start_admin_totp_setup(user))
        if user.two_factor_enabled:
            csrf_token = session.get('csrf_token')
            session.clear()
            session['csrf_token'] = csrf_token or secrets.token_urlsafe(32)
            session['pending_2fa_user_id'] = user.id
            return jsonify({'success': False, 'requires_2fa': True, 'message': 'Enter your two-step verification code.'})
        if not is_email_verified(user):
            return begin_email_verification_login(user)
        complete_login(user)
        return jsonify({'success': True, 'role': user.role})
    return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

@app.route('/auth/2fa/verify-login', methods=['POST'])
def verify_login_2fa():
    data = request.get_json() or {}
    email_otp_user_id = session.get('pending_email_otp_user_id')
    email_verification_user_id = session.get('pending_email_verification_user_id')
    user_id = session.get('pending_2fa_user_id') or email_otp_user_id or email_verification_user_id
    if rate_limited('2fa-login', str(user_id or client_rate_identity()), limit=6, window_seconds=10 * 60):
        return rate_limit_response('Too many verification attempts. Wait a few minutes and try again.')
    user = db.session.get(User, user_id) if user_id else None
    if not user:
        return jsonify({'success': False, 'error': 'Login session expired. Sign in again.'}), 401
    code = data.get('code')
    if email_verification_user_id:
        if verify_email_code(user, code):
            complete_login(user)
            return jsonify({'success': True, 'role': user.role})
        return jsonify({'success': False, 'error': 'Invalid or expired email verification code'}), 401
    if email_otp_user_id and verify_pending_email_otp(user, code):
        complete_login(user)
        return jsonify({'success': True, 'role': user.role})
    used_recovery_code = False
    if not verify_totp(user.two_factor_secret, code):
        used_recovery_code = verify_and_consume_recovery_code(user, code)
        if not used_recovery_code:
            if email_otp_user_id:
                return jsonify({'success': False, 'error': 'Invalid email, authenticator, or recovery code'}), 401
            return jsonify({'success': False, 'error': 'Invalid verification or recovery code'}), 401
        db.session.commit()
    complete_login(user)
    response = {'success': True, 'role': user.role}
    if used_recovery_code:
        response['message'] = 'Recovery code accepted. Generate a new set from Account security soon.'
    return jsonify(response)


@app.route('/auth/2fa/resend-login-code', methods=['POST'])
def resend_login_2fa_code():
    email_verification_user_id = session.get('pending_email_verification_user_id')
    user_id = session.get('pending_email_otp_user_id') or email_verification_user_id
    user = db.session.get(User, user_id) if user_id else None
    if not user:
        return jsonify({'success': False, 'error': 'Login session expired. Sign in again.'}), 401
    if email_verification_user_id:
        if rate_limited('email-verification-send', str(user.id), limit=10, window_seconds=15 * 60):
            return rate_limit_response('Too many verification code requests. Wait a few minutes and try again.')
        try:
            sent = send_email_verification(user)
        except Exception:
            app.logger.exception('Email verification resend failed for user %s', user.id)
            sent = False
        if not sent:
            return jsonify({'success': False, 'error': 'Could not send verification code. Check Mailjet/SMTP settings and try again.'}), 500
        return jsonify({'success': True, 'message': 'New verification code sent. Check your inbox and spam folder.'})
    if rate_limited('admin-email-otp-send', str(user.id), limit=10, window_seconds=15 * 60):
        return rate_limit_response('Too many admin login code requests. Wait a few minutes and try again.')
    code = create_admin_email_otp(user)
    try:
        sent = send_admin_login_otp(user, code)
    except Exception:
        app.logger.exception('Admin login code resend failed for user %s', user.id)
        sent = False
    if not sent:
        return jsonify({'success': False, 'error': 'Could not send admin login code. Check email settings.'}), 500
    return jsonify({'success': True, 'message': 'New admin login code sent. Check your inbox and spam folder.'})


@app.route('/auth/admin/2fa/start-login-setup', methods=['POST'])
def start_admin_2fa_setup_during_login():
    user_id = session.get('pending_email_otp_user_id') or session.get('pending_admin_2fa_setup_user_id')
    if rate_limited('admin-2fa-setup-start', str(user_id or client_rate_identity()), limit=6, window_seconds=10 * 60):
        return rate_limit_response('Too many setup attempts. Wait a few minutes and try again.')
    user = db.session.get(User, user_id) if user_id else None
    if not user or user.role != 'admin':
        return jsonify({'success': False, 'error': 'Admin setup session expired. Sign in again.'}), 401
    data = request.get_json(silent=True) or {}
    return jsonify(start_admin_totp_setup(user, reset_secret=bool(data.get('reset_secret'))))


@app.route('/auth/admin/2fa/enable-login', methods=['POST'])
def enable_admin_2fa_during_login():
    user_id = session.get('pending_admin_2fa_setup_user_id')
    if rate_limited('admin-2fa-setup-login', str(user_id or client_rate_identity()), limit=6, window_seconds=10 * 60):
        return rate_limit_response('Too many setup attempts. Wait a few minutes and try again.')
    user = db.session.get(User, user_id) if user_id else None
    if not user or user.role != 'admin':
        return jsonify({'success': False, 'error': 'Admin setup session expired. Sign in again.'}), 401
    data = request.get_json(silent=True) or {}
    if not verify_totp(user.two_factor_secret, data.get('code')):
        return jsonify({'success': False, 'error': 'Invalid authenticator code'}), 400
    recovery_codes, recovery_hashes = generate_recovery_codes()
    user.two_factor_enabled = True
    user.two_factor_recovery_hashes = json.dumps(recovery_hashes)
    db.session.commit()
    complete_login(user)
    return jsonify({
        'success': True,
        'role': user.role,
        'message': 'Admin authenticator security is enabled. Save your recovery codes.',
        'recovery_codes': recovery_codes
    })

@app.route('/auth/password-reset/request', methods=['POST'])
def request_password_reset():
    data = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or '').strip()
    normalized_identifier = identifier.lower()
    if rate_limited('password-reset-request', normalized_identifier or client_rate_identity(), limit=5, window_seconds=15 * 60):
        return rate_limit_response()
    if not email_configured():
        return jsonify({'success': False, 'email_sent': False, 'error': smtp_configuration_error()}), 400
    user = User.query.filter(
        (User.username == identifier) | (User.email == normalized_identifier)
    ).first() if identifier else None

    if user and user.email:
        try:
            code = create_password_reset_code(user)
            if send_password_reset_email(user, code):
                return jsonify({
                    'success': True,
                    'email_sent': True,
                    'message': 'Reset code sent. Check your inbox and spam folder.'
                })
        except Exception:
            app.logger.exception('Password reset email failed for user %s', user.id)
            return jsonify({'success': False, 'email_sent': False, 'error': 'Could not send the reset email. Check SMTP settings and try again.'}), 500

    return jsonify({
        'success': True,
        'email_sent': False,
        'message': 'If that account exists and has a recovery email, a reset code has been sent.'
    })

@app.route('/auth/password-reset/complete', methods=['POST'])
def complete_password_reset():
    data = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or '').strip()
    reset_code = data.get('reset_code') or ''
    recovery_code = data.get('recovery_code') or ''
    new_password = data.get('new_password') or ''
    confirm_password = data.get('confirm_password') or ''

    if rate_limited('password-reset-complete', identifier or client_rate_identity(), limit=8, window_seconds=15 * 60):
        return rate_limit_response()

    user = User.query.filter(
        (User.username == identifier) | (User.email == identifier.lower())
    ).first() if identifier else None
    if not user:
        return jsonify({'success': False, 'error': 'Invalid reset details'}), 400
    if new_password != confirm_password:
        return jsonify({'success': False, 'error': 'New passwords do not match'}), 400
    if not password_is_strong(new_password):
        return jsonify({'success': False, 'error': 'Use at least 12 characters with uppercase, lowercase, and a number'}), 400

    reset_ok = verify_password_reset_code(user, reset_code) if reset_code else False
    recovery_ok = verify_and_consume_recovery_code(user, recovery_code) if recovery_code else False
    if not reset_ok and not recovery_ok:
        return jsonify({'success': False, 'error': 'Enter a valid email reset code or saved 2FA recovery code'}), 400

    user.set_password(new_password)
    db.session.commit()
    session.clear()
    return jsonify({'success': True, 'message': 'Password reset. Sign in with the new password.'})

@app.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    email = valid_email(data.get('email'))
    password = data.get('password')

    if rate_limited('register', client_rate_identity(), limit=10, window_seconds=60 * 60):
        return rate_limit_response()
    if not username or not email or not password:
        return jsonify({'success': False, 'error': 'Name, email, and password are required'}), 400
    if email is None:
        return jsonify({'success': False, 'error': 'Enter a valid email address'}), 400
    if not password_is_strong(password):
        return jsonify({'success': False, 'error': 'Use at least 12 characters with uppercase, lowercase, and a number'}), 400
    
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Username already exists'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'error': 'Email already exists'}), 400
    if not email_configured():
        return jsonify({'success': False, 'error': smtp_configuration_error()}), 400
    
    user = User(username=username, email=email, role='player')
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return begin_email_verification_login(user, 'Account created. Enter the email verification code to continue.')

@app.route('/auth/google')
def google_login():
    if not google_oauth_configured():
        return redirect(url_for('login_page'))
    state = secrets.token_urlsafe(24)
    session['google_oauth_state'] = state
    params = {
        'client_id': app.config['GOOGLE_CLIENT_ID'],
        'redirect_uri': url_for('google_callback', _external=True),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account'
    }
    return redirect(f"{app.config['GOOGLE_DISCOVERY_AUTH_URL']}?{urllib.parse.urlencode(params)}")

@app.route('/auth/google/callback')
def google_callback():
    if not google_oauth_configured():
        return redirect(url_for('login_page'))
    if request.args.get('state') != session.pop('google_oauth_state', None):
        return redirect(url_for('login_page'))
    code = request.args.get('code')
    if not code:
        return redirect(url_for('login_page'))

    try:
        token_data = fetch_json_url(app.config['GOOGLE_TOKEN_URL'], {
            'code': code,
            'client_id': app.config['GOOGLE_CLIENT_ID'],
            'client_secret': app.config['GOOGLE_CLIENT_SECRET'],
            'redirect_uri': url_for('google_callback', _external=True),
            'grant_type': 'authorization_code'
        })
        access_token = token_data.get('access_token')
        if not access_token:
            raise ValueError('Missing access token')
        google_user = fetch_json_url(
            app.config['GOOGLE_USERINFO_URL'],
            headers={'Authorization': f'Bearer {access_token}'}
        )
    except Exception:
        app.logger.exception('Google OAuth failed')
        return redirect(url_for('login_page'))

    google_sub = google_user.get('sub')
    email = (google_user.get('email') or '').lower()
    if not google_sub or not email:
        return redirect(url_for('login_page'))

    user = User.query.filter_by(google_sub=google_sub).first()
    if not user:
        user = User.query.filter_by(email=email).first()
    if not user:
        base_name = re.sub(r'[^a-zA-Z0-9_]', '', (google_user.get('name') or email.split('@')[0]))[:32] or 'player'
        username = base_name
        suffix = 1
        while User.query.filter_by(username=username).first():
            suffix += 1
            username = f'{base_name}{suffix}'
        user = User(username=username, email=email, role='player', auth_provider='google', google_sub=google_sub)
        user.set_password(secrets.token_urlsafe(32))
        db.session.add(user)
    else:
        user.email = user.email or email
        user.google_sub = user.google_sub or google_sub
        if user.auth_provider == 'local':
            user.auth_provider = 'local+google'
    db.session.commit()
    profiles, profile = get_profile_record(user.id)
    profile['email_verified'] = True
    profile.pop('email_verification_hash', None)
    profile.pop('email_verification_expires_at', None)
    save_profile_store(profiles)

    if user.role == 'admin':
        payload, status = start_admin_email_otp_session(user)
        if payload and status == 200:
            return redirect(url_for('login_page', two_factor='1', admin_email_code='1'))
        app.logger.warning('Admin Google login email verification could not start for user %s: %s', user.id, payload)
        return redirect(url_for('login_page'))

    if user.two_factor_enabled:
        session.clear()
        session['pending_2fa_user_id'] = user.id
        return redirect(url_for('login_page', two_factor='1'))
    complete_login(user)
    return redirect(url_for('admin_panel' if user.role == 'admin' else 'dashboard'))

@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/maintenance')
def maintenance_page():
    return render_template('maintenance.html', site_content=get_site_content())

@app.route('/about')
def about_page():
    return render_template('site_page.html', page_key='about', site_content=get_site_content())

@app.route('/support')
def support_page():
    return render_template('site_page.html', page_key='support', site_content=get_site_content())

@app.route('/terms')
def terms_page():
    return render_template('site_page.html', page_key='terms', site_content=get_site_content())

@app.route('/contact')
def contact_page():
    return render_template('site_page.html', page_key='contact', site_content=get_site_content())

@app.route('/help')
def help_page():
    return render_template('site_page.html', page_key='help', site_content=get_site_content())

@app.route('/competition-guide')
def competition_guide_page():
    return render_template('site_page.html', page_key='competition_guide', site_content=get_site_content())

@app.route('/admin/competition-guide')
@admin_required
def admin_competition_guide():
    user = get_current_user()
    return render_template('admin_competition_guide.html', user=user)

@app.route('/shortcuts')
def shortcuts_page():
    shortcut_groups = [
        {
            'title': 'Build Snippets',
            'icon': 'fa-wand-magic-sparkles',
            'rows': [
                ('! or html:5 + Enter/Tab', 'Insert a full HTML5 document shell.'),
                ('div.card, #app, a.btn + Enter/Tab', 'Expand simple HTML class and id abbreviations.'),
                ('ul>li*3, nav>ul>li*4 + Enter/Tab', 'Create repeated nested HTML structures.'),
                ('card, hero, grid, form, modal, table, video', 'Drop common UI starter blocks into HTML.'),
                ('m10, p16, w100p, d:f, grid2, pos:a, shadow', 'Expand quick CSS utility snippets.')
            ]
        },
        {
            'title': 'Editing',
            'icon': 'fa-pen-to-square',
            'rows': [
                ('Ctrl+Space', 'Open autocomplete suggestions.'),
                ('Ctrl+F', 'Find text in the current editor.'),
                ('Ctrl+H', 'Replace the next matching text.'),
                ('Ctrl+/', 'Toggle a line comment.'),
                ('Shift+Alt+A', 'Toggle a block comment when the language supports it.'),
                ('Ctrl+L', 'Select the current line.'),
                ('Ctrl+D', 'Select the next matching word or selection.'),
                ('Ctrl+Shift+L', 'Select all matches in the current editor.'),
                ('Ctrl+G', 'Jump to a line number.')
            ]
        },
        {
            'title': 'Lines and Layout',
            'icon': 'fa-grip-lines',
            'rows': [
                ('Alt+Up / Alt+Down', 'Move the current line up or down.'),
                ('Shift+Alt+Up / Shift+Alt+Down', 'Duplicate the current line.'),
                ('Ctrl+Shift+K', 'Delete the current line.'),
                ('Ctrl+[ / Ctrl+]', 'Outdent or indent selected code.'),
                ('Shift+Alt+F', 'Format indentation.'),
                ('Alt+Z', 'Toggle line wrapping.'),
                ('Ctrl+Alt+Up / Ctrl+Alt+Down', 'Add another cursor above or below.')
            ]
        },
        {
            'title': 'Arena Actions',
            'icon': 'fa-crosshairs',
            'rows': [
                ('Ctrl+1 / Ctrl+2 / Ctrl+3', 'Switch between HTML, CSS, and JavaScript.'),
                ('Ctrl+`', 'Cycle to the next editor tab.'),
                ('Ctrl+S', 'Save locally and refresh the preview.'),
                ('Shift+Enter', 'Refresh the live preview.'),
                ('Ctrl+Enter', 'Submit and check your score.'),
                ('Ctrl+Alt+R', 'Reset to the starter code after confirmation.'),
                ('Alt+C in CSS', 'Open the color picker near the cursor.')
            ]
        },
        {
            'title': 'VS Code Memory',
            'icon': 'fa-code',
            'rows': [
                ('Ctrl+K Ctrl+S', 'VS Code opens Keyboard Shortcuts. In the arena, use this page as the reference.'),
                ('Ctrl+Shift+P', 'VS Code opens the Command Palette. Arena keeps match actions visible instead.'),
                ('Ctrl+P', 'VS Code opens Quick Open. Arena uses fixed HTML, CSS, and JS tabs.'),
                ('F5', 'VS Code starts debugging when a debugger is available. Arena debugging tools stay disabled for fair play.')
            ]
        }
    ]
    sources = [
        {'label': 'VS Code keyboard shortcuts', 'url': 'https://code.visualstudio.com/docs/getstarted/keybindings'},
        {'label': 'VS Code default keybindings', 'url': 'https://code.visualstudio.com/docs/reference/default-keybindings'}
    ]
    return render_template('shortcuts.html', shortcut_groups=shortcut_groups, sources=sources, site_content=get_site_content())

@app.route('/helpline')
def helpline_page():
    return redirect(url_for('contact_page'))

def store_and_notify_site_message(kind, data):
    kind = kind if kind in {'feedback', 'report', 'mail'} else 'feedback'
    message = str(data.get('message') or '').strip()
    if not message:
        return {'success': False, 'error': f'{kind.title()} message is required'}, 400

    row = {
        'id': uuid.uuid4().hex,
        'type': kind,
        'name': str(data.get('name') or session.get('username') or 'Visitor')[:120],
        'email': str(data.get('email') or '')[:180],
        'subject': str(data.get('subject') or f'UI Battle Arena {kind}')[:160],
        'message': message[:2000],
        'room_code': str(data.get('room_code') or '')[:80],
        'target_email': str(data.get('target_email') or '')[:180],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'replies': []
    }
    save_feedback_message(row)

    subject = f"UI Battle Arena {kind}: {row['name']}"
    body = (
        f"Type: {kind.title()}\n"
        f"Name: {row['name']}\n"
        f"Email: {row['email'] or 'Not provided'}\n"
        f"Room code: {row['room_code'] or 'Not provided'}\n"
        f"Subject: {row['subject']}\n"
        f"Sent at: {row['created_at']}\n\n"
        f"Message:\n{row['message']}"
    )
    recipients = site_mail_recipients(row.get('target_email'))
    email_sent = 0
    if recipients and email_configured():
        email_sent = notify_users_by_email(
            [type('Recipient', (), {'id': index, 'email': email})() for index, email in enumerate(recipients, start=1)],
            subject,
            body,
            only_verified=False
        )
    return {
        'success': True,
        'message': f"{kind.title()} sent to admins",
        'email_sent': email_sent
    }, 200

@app.route('/site-mail', methods=['POST'])
def site_mail_page():
    data = request.get_json(silent=True) or request.form or {}
    sender_email = valid_email(data.get('email'))
    if not sender_email:
        return jsonify({'success': False, 'error': 'Enter a valid email address so admins can reply.'}), 400
    if rate_limited('site-mail', sender_email or client_rate_identity(), limit=5, window_seconds=30 * 60):
        return rate_limit_response('Too many mail messages. Wait a while before sending another.')
    payload, status = store_and_notify_site_message('mail', {
        **dict(data),
        'email': sender_email,
        'subject': str(data.get('subject') or 'Support request')[:160]
    })
    if status == 200:
        payload['message'] = 'Message sent to the arena inbox.'
    return jsonify(payload), status

@app.route('/feedback', methods=['GET', 'POST'])
def feedback_page():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form or {}
        payload, status = store_and_notify_site_message('feedback', data)
        return jsonify(payload), status
    return render_template('site_page.html', page_key='feedback', site_content=get_site_content())

@app.route('/report', methods=['GET', 'POST'])
def report_page():
    if request.method == 'POST':
        data = request.get_json(silent=True) or request.form or {}
        data = dict(data)
        payload, status = store_and_notify_site_message('report', data)
        return jsonify(payload), status
    return render_template('site_page.html', page_key='report', site_content=get_site_content())

# ========== DASHBOARD ==========
@app.route('/dashboard')
@login_required
def dashboard():
    ensure_schema_upgrades()
    user = get_current_user()
    rooms = Room.query.filter(Room.status != 'ended').order_by(Room.created_at.desc()).all()
    leaderboard_rows = build_leaderboard_rows()
    top_players = [row['user'] for row in leaderboard_rows[:10]]
    recent_matches = Submission.query.filter_by(user_id=user.id).order_by(Submission.submitted_at.desc()).limit(5).all()
    
    room_data = []
    for room in rooms:
        challenge = room.challenge
        room_data.append({
            'id': room.id,
            'room_code': room.room_code if room.is_public else None,
            'is_public': bool(room.is_public),
            'challenge_title': challenge.title if challenge else 'Unknown',
            'challenge_type': challenge.challenge_type if challenge else 'image',
            'difficulty': challenge.difficulty if challenge else 'Medium',
            'status': room.status,
            'player1': room.player1.username if room.player1 else 'Open',
            'player2': room.player2.username if room.player2 else 'Open'
        })
    
    rank = next((i+1 for i, row in enumerate(leaderboard_rows) if row['user'].id == user.id), None)
    current_record = next((row['record'] for row in leaderboard_rows if row['user'].id == user.id), calculate_player_record(user))
    
    return render_template('dashboard.html', 
                         user=user, 
                         rooms=room_data,
                         top_players=top_players,
                         recent_matches=recent_matches,
                         active_rooms_count=len(rooms),
                         total_challenges=Challenge.query.filter_by(is_active=True).count(),
                         total_players=User.query.filter_by(role='player').count(),
                         global_rank=rank,
                         leaderboard_unlocked=user_has_leaderboard_access(user, current_record))

# ========== ADMIN ROUTES ==========
@app.route('/admin')
@admin_required
def admin_panel():
    ensure_schema_upgrades()
    user = get_current_user()
    rooms = Room.query.order_by(Room.created_at.desc()).all()
    challenges = Challenge.query.filter_by(is_active=True).all()
    all_challenges = Challenge.query.all()
    leaderboard_rows = build_leaderboard_rows()
    players = User.query.order_by(User.username.asc()).all()
    tournaments = Tournament.query.order_by(Tournament.created_at.desc()).all()
    completed_tournaments = [t for t in tournaments if t.status == 'completed']
    competitions = Competition.query.order_by(Competition.created_at.desc()).all()
    competition_data = [serialize_competition(competition) for competition in competitions]
    competition_room_counts = {
        competition.id: Room.query.filter_by(competition_id=competition.id).count()
        for competition in competitions
    }
    competition_leaderboards = {
        competition.id: qualification_rows(competition_id=competition.id, limit=10)
        for competition in competitions
    }
    my_assigned_rooms = build_my_assigned_rooms(user.id)
    my_assignment_warnings = build_admin_assignment_warnings(user.id)
    assignment_center_warnings = build_assignment_center_warnings()
    admin_tasks = AdminTask.query.order_by(AdminTask.created_at.desc()).limit(200).all()
    my_admin_tasks = AdminTask.query.filter_by(assigned_admin_id=user.id).order_by(AdminTask.created_at.desc()).limit(80).all()
    open_disputes = DisputeCase.query.filter(DisputeCase.status.in_(['open', 'review'])).order_by(DisputeCase.created_at.desc()).limit(80).all()
    admin_users = User.query.filter_by(role='admin').order_by(User.username.asc()).all()
    watched_rooms_by_admin = {}
    for info in connected_users.values():
        if info.get('role') == 'admin' and info.get('user_id') and info.get('room_id'):
            watched_rooms_by_admin.setdefault(int(info['user_id']), set()).add(int(info['room_id']))
    admin_status_rows = []
    for admin_user in admin_users:
        active_task_count = AdminTask.query.filter(
            AdminTask.assigned_admin_id == admin_user.id,
            AdminTask.status.in_(['open', 'acknowledged', 'active'])
        ).count()
        watched = sorted(watched_rooms_by_admin.get(admin_user.id, set()))
        admin_status_rows.append({
            'user': admin_user,
            'online': bool(watched),
            'watched_room_ids': watched,
            'watched_count': len(watched),
            'active_task_count': active_task_count
        })

    total_matches = Submission.query.count()
    avg_accuracy = db.session.query(func.avg(Submission.accuracy)).scalar() or 0
    avg_accuracy = round(avg_accuracy, 1)
    active_players = User.query.filter_by(role='player').count()
    top_player = leaderboard_rows[0]['user'] if leaderboard_rows else None
    highest_score = leaderboard_rows[0]['record']['power_score'] if leaderboard_rows else 0
    
    recent_messages = ChatMessage.query.order_by(ChatMessage.sent_at.desc()).limit(6).all()
    moderation_messages_raw = ChatMessage.query.order_by(ChatMessage.sent_at.desc()).limit(80).all()
    moderation_messages = [
        serialize_admin_chat_message(msg, user.username)
        for msg in moderation_messages_raw
    ]
    moderation_flagged_count = sum(1 for msg in moderation_messages if msg['is_flagged'])
    moderation_mentions_count = sum(1 for msg in moderation_messages if msg['is_mention'])
    recent_activities = [
        {
            'username': msg.user.username if msg.user else 'System',
            'action': msg.message,
            'time': msg.sent_at.strftime('%H:%M') if msg.sent_at else ''
        }
        for msg in recent_messages
    ]
    
    spectators_by_room = {
        room.id: sorted(list(room_spectators.get(room.id, set())))
        for room in rooms
    }
    feedback_messages = load_feedback_messages()
    
    return render_template('admin.html',
                         user=user, 
                         rooms=rooms, 
                         challenges=challenges,
                         all_challenges=all_challenges,
                         players=players,
                         players_sorted=[row['user'] for row in leaderboard_rows],
                         spectators_by_room=spectators_by_room,
                         total_matches=total_matches,
                         avg_accuracy=avg_accuracy,
                         active_players=active_players,
                         top_player=top_player,
                         highest_score=highest_score,
                         leaderboard_rows=leaderboard_rows,
                         leaderboard_streak_target=LEADERBOARD_STREAK_TARGET,
                         recent_activities=recent_activities,
                         moderation_messages=moderation_messages,
                         moderation_flagged_count=moderation_flagged_count,
                         moderation_mentions_count=moderation_mentions_count,
                         feedback_messages=feedback_messages,
                         tournaments=tournaments,
                         completed_tournaments=completed_tournaments,
                         competitions=competitions,
                         competition_data=competition_data,
                         competition_room_counts=competition_room_counts,
                         competition_leaderboards=competition_leaderboards,
                         my_assigned_rooms=my_assigned_rooms,
                         my_assignment_warnings=my_assignment_warnings,
                         assignment_center_warnings=assignment_center_warnings,
                         admin_tasks=admin_tasks,
                         my_admin_tasks=my_admin_tasks,
                         admin_task_rows=[serialize_admin_task(task) for task in admin_tasks],
                         my_admin_task_rows=[serialize_admin_task(task) for task in my_admin_tasks],
                         admin_status_rows=admin_status_rows,
                         open_disputes=open_disputes,
                         admin_users=admin_users,
                         site_content=get_site_content(),
                         certificate_template=get_certificate_template_settings(),
                         tournament_sizes=sorted(TOURNAMENT_SIZES))

@app.route('/admin/site-content', methods=['GET', 'POST'])
@admin_required
def admin_site_content():
    if request.method == 'GET':
        return jsonify({'success': True, 'site_content': get_site_content()})

    data = request.get_json(silent=True) or {}
    content = normalize_site_content_payload(data)
    save_site_content(content)

    notice = content.get('maintenance_notice', {})
    if notice.get('enabled'):
        payload = {
            'title': notice.get('title') or 'Scheduled maintenance',
            'message': notice.get('message') or '',
            'maintenance_at': notice.get('maintenance_at') or '',
            'release_at': notice.get('release_at') or ''
        }
        socketio.emit('maintenance_notice', payload)
        if notice.get('email_users') and email_configured():
            recipients = User.query.filter(User.email.isnot(None), User.email != '').all()
            notify_users_by_email(
                recipients,
                payload['title'],
                (
                    f"{payload['message']}\n\n"
                    f"Maintenance: {payload['maintenance_at'] or 'To be announced'}\n"
                    f"Update release: {payload['release_at'] or 'To be announced'}\n\n"
                    "Please download any assets you need before the maintenance window."
                ),
                only_verified=False
            )
    return jsonify({'success': True, 'site_content': content})

@app.route('/admin/site-content/upload', methods=['POST'])
@admin_required
def admin_site_content_upload():
    files = request.files.getlist('files')
    if not files:
        return jsonify({'success': False, 'error': 'Choose one or more media files'}), 400

    upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'site_content')
    os.makedirs(upload_dir, exist_ok=True)
    saved = []
    for media_file in files:
        if not media_file or not media_file.filename:
            continue
        if not allowed_site_media_file(media_file.filename):
            return jsonify({'success': False, 'error': f'Unsupported media file: {media_file.filename}'}), 400
        ext = secure_filename(media_file.filename).rsplit('.', 1)[1].lower()
        filename = f"site_{uuid.uuid4().hex}.{ext}"
        media_file.save(os.path.join(upload_dir, filename))
        saved.append({
            'url': url_for('static', filename=f'uploads/site_content/{filename}'),
            'filename': filename,
            'type': 'video' if ext in {'mp4', 'webm', 'mov'} else 'image'
        })

    if not saved:
        return jsonify({'success': False, 'error': 'No valid files were uploaded'}), 400
    return jsonify({'success': True, 'files': saved})

@app.route('/admin/certificate-template', methods=['GET', 'POST'])
@admin_required
def admin_certificate_template():
    if request.method == 'GET':
        return jsonify({'success': True, 'certificate_template': get_certificate_template_settings()})

    data = request.get_json(silent=True) or {}
    settings = normalize_certificate_settings(data)
    save_certificate_template_settings(settings)
    return jsonify({'success': True, 'certificate_template': settings})

@app.route('/admin/spectators')
@admin_required
def admin_spectators():
    user = get_current_user()
    rooms = Room.query.order_by(Room.created_at.desc()).all()
    spectators_by_room = {
        room.id: sorted(list(room_spectators.get(room.id, set())))
        for room in rooms
    }
    return render_template('spectators.html',
                           user=user,
                           rooms=rooms,
                           spectators_by_room=spectators_by_room)

@app.route('/admin/broadcast', methods=['POST'])
@admin_required
def admin_broadcast():
    data = request.get_json() or {}
    message = data.get('message', '')
    room_id = data.get('room_id')
    if room_id:
        socketio.emit('system_announcement', {'message': message}, room=str(room_id))
    else:
        for room in Room.query.all():
            socketio.emit('system_announcement', {'message': message}, room=str(room.id))
    return jsonify({'success': True})

@app.route('/admin/broadcast-email', methods=['POST'])
@admin_required
def admin_broadcast_email():
    if not email_configured():
        return jsonify({'success': False, 'error': smtp_configuration_error()}), 400
    if rate_limited('admin-broadcast-email', str(session.get('user_id')), limit=5, window_seconds=60 * 60):
        return rate_limit_response('Too many bulk email broadcasts. Wait a while before sending another.')

    data = request.get_json(silent=True) or {}
    subject = (data.get('subject') or 'UI Battle Arena notification').strip()[:160]
    message = (data.get('message') or '').strip()[:3000]
    only_players = bool(data.get('only_players', False))
    only_verified = bool(data.get('only_verified', False))
    also_web = data.get('also_web', True) is not False

    if not message:
        return jsonify({'success': False, 'error': 'Email message is required'}), 400

    query = User.query.filter(User.email.isnot(None), User.email != '')
    if only_players:
        query = query.filter_by(role='player')
    recipients = query.order_by(User.username.asc()).all()

    sent = 0
    skipped = 0
    failed = 0
    for target in recipients:
        if only_verified and not is_email_verified(target):
            skipped += 1
            continue
        body = f'Hello {target.username},\n\n{message}\n\nUI Battle Arena'
        try:
            if send_email(target.email, subject, body):
                sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1
            app.logger.exception('Bulk email notification failed for user %s', target.id)

    if also_web:
        announcement = message[:500]
        for room in Room.query.filter(Room.status != 'ended').all():
            socketio.emit('system_announcement', {'message': announcement}, room=str(room.id))

    return jsonify({
        'success': True,
        'sent': sent,
        'failed': failed,
        'skipped': skipped,
        'total_recipients': len(recipients),
        'message': f'Email broadcast sent to {sent} user(s).'
    })

@app.route('/admin/player/create', methods=['POST'])
@admin_required
def admin_create_player():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    email_raw = (data.get('email') or '').strip()
    email = valid_email(email_raw) if email_raw else None
    password = data.get('password') or ''
    role = 'admin' if data.get('role') == 'admin' else 'player'
    mark_verified = bool(data.get('email_verified', True))
    generated_password = False

    if not username:
        return jsonify({'success': False, 'error': 'Player name is required'}), 400
    if email_raw and email is None:
        return jsonify({'success': False, 'error': 'Enter a valid email address or leave it blank'}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Username already exists'}), 400
    if email and User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'error': 'Email already exists'}), 400

    if not password:
        password = f"Temp-{secrets.token_urlsafe(10)}-A1"
        generated_password = True
    elif not password_is_strong(password):
        return jsonify({'success': False, 'error': 'Use at least 12 characters with uppercase, lowercase, and a number'}), 400

    new_user = User(username=username, email=email, role=role)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    if email and mark_verified:
        profiles = load_profile_store()
        profile = profiles.setdefault(str(new_user.id), {})
        profile['email_verified'] = True
        profile.pop('email_verification_hash', None)
        profile.pop('email_verification_expires_at', None)
        save_profile_store(profiles)

    return jsonify({
        'success': True,
        'user': new_user.to_dict(),
        'email': new_user.email or '',
        'generated_password': generated_password,
        'temporary_password': password if generated_password else '',
        'message': f'{role.title()} {username} created.'
    })

@app.route('/admin/chat/<int:message_id>/flag', methods=['POST'])
@admin_required
def admin_flag_chat_message(message_id):
    ensure_schema_upgrades()
    admin = get_current_user()
    chat_msg = db.session.get(ChatMessage, message_id)
    if not chat_msg or chat_msg.is_system:
        return jsonify({'success': False, 'error': 'Message not found'}), 404

    reason = (request.json or {}).get('reason') or 'Flagged by admin as harmful'
    reason = reason.strip()[:160]
    chat_msg.is_flagged = True
    chat_msg.flag_reason = reason
    chat_msg.flagged_by = admin.id
    db.session.commit()

    socketio.emit('chat_message_flagged', {
        'id': chat_msg.id,
        'is_flagged': True,
        'flag_reason': reason
    }, room=str(chat_msg.room_id))
    socketio.emit('chat_flag_notice', {
        'message_id': chat_msg.id,
        'message': f'Admin flagged a chat message from {chat_msg.user.username if chat_msg.user else "a user"}.'
    }, room=str(chat_msg.room_id))

    return jsonify({'success': True, 'message': serialize_admin_chat_message(chat_msg, admin.username)})

@app.route('/admin/chat/messages')
@admin_required
def admin_chat_messages():
    ensure_schema_upgrades()
    admin = get_current_user()
    messages = ChatMessage.query.order_by(ChatMessage.sent_at.desc()).limit(120).all()
    payload = [serialize_admin_chat_message(msg, admin.username) for msg in messages]
    return jsonify({
        'success': True,
        'messages': payload,
        'flagged_count': sum(1 for msg in payload if msg['is_flagged']),
        'mentions_count': sum(1 for msg in payload if msg['is_mention'])
    })

@app.route('/admin/chat/<int:message_id>/reply', methods=['POST'])
@admin_required
def admin_reply_chat_message(message_id):
    ensure_schema_upgrades()
    admin = get_current_user()
    source_msg = db.session.get(ChatMessage, message_id)
    if not source_msg:
        return jsonify({'success': False, 'error': 'Message not found'}), 404

    body = (request.json or {}).get('message') or ''
    body = body.strip()[:500]
    if not body:
        return jsonify({'success': False, 'error': 'Reply cannot be empty'}), 400

    target_username = source_msg.user.username if source_msg.user else 'room'
    reply_text = body if body.lower().startswith('@') else f'@{target_username} {body}'
    reply = ChatMessage(
        room_id=source_msg.room_id,
        user_id=admin.id,
        message=reply_text,
        is_system=False
    )
    db.session.add(reply)
    db.session.commit()
    socketio.emit('chat_message', serialize_chat_message(reply), room=str(source_msg.room_id))
    socketio.emit('admin_chat_message', serialize_admin_chat_message(reply, admin.username))

    return jsonify({'success': True, 'message': serialize_admin_chat_message(reply, admin.username)})

@app.route('/admin/user/<int:user_id>/stats')
@admin_required
def admin_user_stats(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    record = sync_user_competition_state(user)
    db.session.commit()
    return jsonify({
        'success': True,
        'username': user.username,
        'role': user.role,
        'matches_played': record['matches_played'],
        'best_accuracy': record['best_accuracy'],
        'total_wins': record['wins'],
        'win_rate': record['win_rate'],
        'current_streak': record['current_streak'],
        'best_streak': record['best_streak'],
        'power_score': record['power_score'],
        'leaderboard_unlocked': user_has_leaderboard_access(user, record),
        'leaderboard_awarded': bool(user.leaderboard_awarded),
        'joined_date': user.created_at.strftime('%Y-%m-%d') if user.created_at else 'Unknown'
    })

@app.route('/admin/user/<int:user_id>/matches')
@admin_required
def admin_user_matches(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    matches = []
    for event in get_user_match_events(user.id)[:20]:
        sub = event['submission']
        challenge = event['room'].challenge if event['room'] else (sub.challenge if sub else None)
        matches.append({
            'date': event['completed_at'].strftime('%Y-%m-%d %H:%M') if event['completed_at'] else 'Unknown',
            'challenge': challenge.title if challenge else 'Unknown',
            'accuracy': round(sub.accuracy, 1) if sub else 0,
            'result': event['result'].title(),
            'is_winner': event['result'] == 'win'
        })

    return jsonify({'success': True, 'matches': matches})

@app.route('/admin/user/<int:user_id>/leaderboard-award', methods=['POST'])
@admin_required
def admin_user_leaderboard_award(user_id):
    user = db.session.get(User, user_id)
    admin = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    data = request.get_json() or {}
    award = bool(data.get('award', True))
    reason = (data.get('reason') or '').strip()
    details = (data.get('details') or '').strip()
    color = (data.get('color') or '#d97706').strip()
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        color = '#d97706'
    user.leaderboard_awarded = award
    user.leaderboard_awarded_at = datetime.now(timezone.utc) if award else None
    user.leaderboard_awarded_by = admin.id if award and admin else None
    user.leaderboard_award_reason = reason[:200] if award and reason else None
    user.leaderboard_award_details = details if award and details else None
    user.leaderboard_award_color = color if award else None
    record = sync_user_competition_state(user)
    db.session.commit()

    return jsonify({
        'success': True,
        'username': user.username,
        'leaderboard_unlocked': user_has_leaderboard_access(user, record),
        'leaderboard_awarded': bool(user.leaderboard_awarded),
        'power_score': record['power_score'],
        'award_reason': user.leaderboard_award_reason,
        'award_details': user.leaderboard_award_details,
        'award_color': user.leaderboard_award_color
    })

@app.route('/admin/user/<int:user_id>/award-card')
@admin_required
def admin_award_card_page(user_id):
    target_user = db.session.get(User, user_id)
    if not target_user:
        return redirect(url_for('admin_panel'))
    if target_user.role == 'admin':
        return redirect(url_for('admin_panel'))
    existing_cards = AwardCard.query.filter_by(user_id=user_id).order_by(AwardCard.created_at.desc()).all()
    return render_template(
        'award_designer.html',
        user=get_current_user(),
        target_user=target_user,
        cards=[serialize_award_card(card) for card in existing_cards],
        card_templates=CARD_TEMPLATES,
        avatar_templates=AVATAR_TEMPLATES,
        admin_mode=True
    )

@app.route('/admin/user/<int:user_id>/award-card', methods=['POST'])
@admin_required
def admin_save_award_card(user_id):
    target_user = db.session.get(User, user_id)
    admin = get_current_user()
    if not target_user:
        return jsonify({'success': False, 'error': 'Student not found'}), 404
    if target_user.role == 'admin':
        return jsonify({'success': False, 'error': 'Cards can only be awarded to students'}), 400

    data = request.get_json(silent=True) or {}
    template = get_card_template(data.get('card_template'))
    avatar = get_avatar_template(data.get('avatar_template'))
    title = (data.get('title') or 'Loyalty Recognition Card').strip()[:140]
    message = (data.get('message') or 'Recognized for strong effort, consistency, and positive contribution.').strip()[:800]
    reason = (data.get('reason') or 'Excellent performance').strip()[:200]
    shape = data.get('shape') if data.get('shape') in {'rounded', 'ticket', 'hex', 'wave', 'sharp'} else template['shape']
    avatar_shape = data.get('avatar_shape') if data.get('avatar_shape') in {'circle', 'shield', 'blob', 'square', 'hex'} else avatar['shape']
    layout = data.get('layout') if data.get('layout') in {'classic', 'badge', 'split', 'diagonal'} else template['layout']

    card = AwardCard(
        user_id=target_user.id,
        awarded_by=admin.id,
        title=title,
        reason=reason,
        message=message,
        card_template=template['id'],
        avatar_template=avatar['id'],
        accent_icon=data.get('accent_icon') or template['icon'],
        avatar_label=(data.get('avatar_label') or target_user.username).strip()[:80],
        primary_color=clean_hex_color(data.get('primary_color'), template['primary']),
        secondary_color=clean_hex_color(data.get('secondary_color'), template['secondary']),
        shape=shape,
        avatar_shape=avatar_shape,
        layout=layout
    )
    db.session.add(card)
    db.session.commit()
    return jsonify({'success': True, 'card': serialize_award_card(card)})


@app.route('/admin/user/<int:user_id>/certificate-card', methods=['POST'])
@admin_required
def admin_send_certificate_card(user_id):
    target_user = db.session.get(User, user_id)
    admin = get_current_user()
    if not target_user:
        return jsonify({'success': False, 'error': 'Student not found'}), 404
    if target_user.role == 'admin':
        return jsonify({'success': False, 'error': 'Certificates can only be sent to students'}), 400

    data = request.get_json(silent=True) or {}
    cert = get_certificate_template_settings()
    posted_template = data.get('certificate_template')
    cert = normalize_certificate_settings(posted_template if isinstance(posted_template, dict) else {}, cert)
    title = (data.get('title') or cert.get('certificate_title') or 'Certificate of Merit').strip()[:140]
    reason = (data.get('reason') or cert.get('award_line') or 'Official certificate recognition').strip()[:200]
    message = (data.get('message') or cert.get('regards_text') or 'Recognized by an administrator for official arena achievement.').strip()[:800]
    color = clean_hex_color(data.get('color'), cert.get('accent_color') or '#b91c1c')
    competition = (cert.get('competition_name') or '').strip()
    category = (cert.get('category') or '').strip()
    held_at = (cert.get('held_at') or '').strip()
    award_date = (cert.get('award_date') or datetime.now().strftime('%d %b %Y')).strip()
    details = message
    meta_bits = [item for item in [competition, category, held_at, award_date] if item]
    if meta_bits:
        details = f"{message}\n\n" + " | ".join(meta_bits)
    certificate_payload = {
        **cert,
        'recipient_name': target_user.username,
        'certificate_title': title,
        'award_line': reason,
        'regards_text': message,
        'accent_color': color,
        'award_date': award_date
    }

    card = AwardCard(
        user_id=target_user.id,
        awarded_by=admin.id,
        title=title,
        reason=reason,
        message=details[:800],
        card_template='leadership',
        avatar_template='shield',
        accent_icon='fa-certificate',
        avatar_label=target_user.username,
        primary_color=color,
        secondary_color='#111827',
        shape='ticket',
        avatar_shape='shield',
        layout='classic',
        certificate_payload=json.dumps(certificate_payload)
    )
    target_user.leaderboard_awarded = True
    target_user.leaderboard_awarded_at = datetime.now(timezone.utc)
    target_user.leaderboard_awarded_by = admin.id if admin else None
    target_user.leaderboard_award_reason = title[:200]
    target_user.leaderboard_award_details = details
    target_user.leaderboard_award_color = color
    db.session.add(card)
    db.session.commit()
    return jsonify({'success': True, 'card': serialize_award_card(card)})

@app.route('/admin/user/<int:user_id>/email', methods=['POST'])
@admin_required
def admin_email_user(user_id):
    target_user = db.session.get(User, user_id)
    if not target_user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    if not target_user.email:
        return jsonify({'success': False, 'error': 'This user does not have an email address'}), 400
    if not email_configured():
        return jsonify({'success': False, 'error': smtp_configuration_error()}), 400
    data = request.get_json(silent=True) or {}
    subject = (data.get('subject') or 'UI Battle Arena update').strip()[:160]
    message = (data.get('message') or '').strip()[:2000]
    if not message:
        return jsonify({'success': False, 'error': 'Email message is required'}), 400
    sent = send_email(
        target_user.email,
        subject,
        f'Hello {target_user.username},\n\n{message}\n\nUI Battle Arena'
    )
    return jsonify({'success': bool(sent)})

@app.route('/admin/site-mail/<message_id>/reply', methods=['POST'])
@admin_required
def admin_reply_site_mail(message_id):
    if not email_configured():
        return jsonify({'success': False, 'error': smtp_configuration_error()}), 400
    if rate_limited('admin-site-mail-reply', str(session.get('user_id')), limit=30, window_seconds=60 * 60):
        return rate_limit_response('Too many replies. Wait a while before sending another.')

    data = request.get_json(silent=True) or {}
    subject = (data.get('subject') or 'Re: UI Battle Arena support').strip()[:160]
    message = (data.get('message') or '').strip()[:3000]
    if not message:
        return jsonify({'success': False, 'error': 'Reply message is required'}), 400

    sent_state = {'sent': False, 'target': None}
    admin = get_current_user()

    def updater(row):
        target = valid_email(row.get('email'))
        if not target:
            return
        sent = send_email(
            target,
            subject,
            (
                f"Hello {row.get('name') or 'there'},\n\n"
                f"{message}\n\n"
                "UI Battle Arena Support"
            )
        )
        sent_state['sent'] = bool(sent)
        sent_state['target'] = target
        replies = row.setdefault('replies', [])
        replies.append({
            'id': uuid.uuid4().hex,
            'admin': admin.username if admin else 'Admin',
            'subject': subject,
            'message': message,
            'sent': bool(sent),
            'sent_at': datetime.now(timezone.utc).isoformat()
        })
        row['last_reply_at'] = replies[-1]['sent_at']

    row = update_feedback_message(message_id, updater)
    if not row:
        return jsonify({'success': False, 'error': 'Inbox message not found'}), 404
    if not sent_state['target']:
        return jsonify({'success': False, 'error': 'This message has no valid reply email.'}), 400
    if not sent_state['sent']:
        return jsonify({'success': False, 'error': 'Reply saved, but email could not be sent. Check email settings.'}), 500
    return jsonify({'success': True, 'message': f"Reply sent to {sent_state['target']}"})

@app.route('/admin/export-data')
@admin_required
def export_data():
    user_data = [u.to_dict() for u in User.query.all()]
    room_data = [
        {
            'id': r.id,
            'room_code': r.room_code,
            'status': r.status,
            'player1': r.player1.username if r.player1 else None,
            'player2': r.player2.username if r.player2 else None,
            'challenge': r.challenge.title if r.challenge else None,
            'competition_id': r.competition_id,
            'wave_id': r.wave_id
        }
        for r in Room.query.all()
    ]
    challenge_data = [
        {
            'id': c.id,
            'title': c.title,
            'type': c.challenge_type,
            'difficulty': c.difficulty,
            'time_limit': c.time_limit,
            'active': c.is_active
        }
        for c in Challenge.query.all()
    ]
    tournament_data = [
        serialize_tournament(tournament)
        for tournament in Tournament.query.order_by(Tournament.created_at.desc()).all()
    ]
    competition_data = [
        serialize_competition(competition)
        for competition in Competition.query.order_by(Competition.created_at.desc()).all()
    ]
    admin_actions = [
        {
            'id': action.id,
            'tournament_id': action.tournament_id,
            'tournament_match_id': action.tournament_match_id,
            'admin': action.admin.username if action.admin else None,
            'player': action.player.username if action.player else None,
            'action_type': action.action_type,
            'reason': action.reason,
            'admin_note': action.admin_note,
            'timestamp': action.timestamp.isoformat() if action.timestamp else None
        }
        for action in AdminAction.query.order_by(AdminAction.timestamp.desc()).all()
    ]
    return jsonify({'users': user_data, 'rooms': room_data, 'challenges': challenge_data, 'competitions': competition_data, 'tournaments': tournament_data, 'admin_actions': admin_actions})

@app.route('/admin/maintenance/clear-data', methods=['POST'])
@admin_required
def admin_clear_created_data():
    try:
        ensure_schema_upgrades()
        data = request.get_json(silent=True) or {}
        if data.get('confirm') != 'CLEAR':
            return jsonify({'success': False, 'error': 'Type CLEAR to confirm the reset'}), 400

        socketio.emit('maintenance_reset', {
            'message': 'The arena was reset by an admin. Please sign in again.'
        })
        counts = clear_created_platform_data()
        session['role'] = 'admin'
        return jsonify({'success': True, 'counts': counts})
    except Exception as exc:
        db.session.rollback()
        app.logger.exception('Failed to clear created platform data')
        return jsonify({
            'success': False,
            'error': f'Clear data failed on the server: {exc.__class__.__name__}'
        }), 500

@app.route('/admin/create_challenge', methods=['POST'])
@admin_required
def create_challenge():
    challenge_type = request.form.get('challenge_type', 'image')
    room_visibility = request.form.get('room_visibility', 'private')
    room_is_public = room_visibility == 'public'
    share_with_email = request.form.get('share_with_email') == 'true'
    launch_mode = request.form.get('launch_mode', 'single_room')
    pairing_method = request.form.get('pairing_method', 'ordered')
    stage_type = request.form.get('stage_type', 'practice')
    wave_name = (request.form.get('wave_name') or '').strip()[:80]
    advance_rule = (request.form.get('advance_rule') or '').strip()[:120]
    competition_name = (request.form.get('competition_name') or '').strip()[:160]
    max_participants = parse_positive_int(request.form.get('max_participants'), 2, 1, 5000)
    room_mode = request.form.get('room_mode', '1v1')
    rooms_to_create = parse_positive_int(request.form.get('rooms_to_create'), 1, 0, 2500)
    players_per_wave = parse_positive_int(request.form.get('players_per_wave'), 100, 1, 5000)
    start_at = (request.form.get('start_at') or '').strip()[:80]
    end_at = (request.form.get('end_at') or '').strip()[:80]
    auto_start = parse_bool_value(request.form.get('auto_start'))
    auto_submit = parse_bool_value(request.form.get('auto_submit'), True)
    allowed_attempts = request.form.get('allowed_attempts', 'one')
    tie_break_rule = request.form.get('tie_break_rule', 'higher_score_then_time')
    fair_play_strictness = request.form.get('fair_play_strictness', 'normal')
    assignment_lines = request.form.get('admin_assignments', '')
    title = (request.form.get('title') or '').strip()
    difficulty = request.form.get('difficulty') or 'Medium'
    try:
        time_limit = int(request.form.get('time_limit', 120))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Invalid time limit'}), 400
    description = request.form.get('description', '')

    if challenge_type not in {'image', 'html'}:
        return jsonify({'success': False, 'error': 'Invalid challenge type'}), 400
    if launch_mode not in {'challenge_only', 'single_room', 'bulk_rooms', 'auto_pair_live', 'qualification', 'bracket', 'qualifier_bracket'}:
        return jsonify({'success': False, 'error': 'Invalid launch mode'}), 400
    if not title:
        return jsonify({'success': False, 'error': 'Challenge name is required'}), 400
    if share_with_email and launch_mode == 'single_room' and not email_configured():
        return jsonify({'success': False, 'error': smtp_configuration_error()}), 400
    needs_participants = launch_mode in {'bulk_rooms', 'qualification', 'qualifier_bracket', 'bracket'}
    if needs_participants:
        participant_ids = list(dict.fromkeys(parse_int_list(request.form.getlist('participant_ids') or request.form.get('participant_ids'))))
        if len(participant_ids) < 2:
            return jsonify({'success': False, 'error': 'Select at least two players for this competition mode'}), 400
        if launch_mode != 'bracket' and room_mode == '1v1' and len(participant_ids) % 2 != 0:
            return jsonify({'success': False, 'error': 'Bulk 1v1 rooms need an even number of players'}), 400
        participant_users = User.query.filter(User.id.in_(participant_ids), User.role == 'player').all()
        if len(participant_users) != len(participant_ids):
            return jsonify({'success': False, 'error': 'All competition participants must be player accounts'}), 400
        participant_users_by_id = {player.id: player for player in participant_users}
        ordered_bulk_players = [participant_users_by_id[player_id] for player_id in participant_ids]
    else:
        ordered_bulk_players = []

    if launch_mode == 'bracket':
        bracket_size = next_power_of_two(len(ordered_bulk_players))
        if bracket_size != len(ordered_bulk_players) or bracket_size not in TOURNAMENT_SIZES:
            return jsonify({'success': False, 'error': 'Bracket mode needs exactly 4, 8, 16, 32, 64, or 128 selected players'}), 400

    if stage_type:
        stage_note = f"\n\nCompetition setup: {stage_type.replace('_', ' ').title()}."
        if wave_name:
            stage_note += f" Wave/group: {wave_name}."
        if advance_rule:
            stage_note += f" Advance rule: {advance_rule}."
        if stage_note not in description:
            description = f"{description}{stage_note}"
    
    new_challenge = Challenge(
        title=title,
        description=description,
        difficulty=difficulty,
        time_limit=time_limit,
        challenge_type=challenge_type,
        created_by=session['user_id'],
        is_active=True
    )
    
    if challenge_type == 'image':
        if 'target_image' not in request.files:
            return jsonify({'success': False, 'error': 'No image uploaded'}), 400
        
        file = request.files['target_image']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if file and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            img = Image.open(file)
            img.save(filepath)
            
            new_challenge.target_image_path = filename
            new_challenge.html_locked = False
    else:
        target_html = (request.form.get('target_html') or '').strip()
        target_css = request.form.get('target_css', '')
        target_js = request.form.get('target_js', '')
        starter_html = (request.form.get('starter_html') or '').strip()
        starter_css = request.form.get('starter_css', '')
        starter_js = request.form.get('starter_js', '')
        html_locked = request.form.get('html_locked') == 'true'

        if not target_html:
            return jsonify({'success': False, 'error': 'Target HTML is required'}), 400
        
        new_challenge.target_html = target_html
        new_challenge.target_css = target_css
        new_challenge.target_js = target_js
        new_challenge.starter_html = starter_html
        new_challenge.starter_css = starter_css
        new_challenge.starter_js = starter_js
        new_challenge.html_locked = html_locked
    
    db.session.add(new_challenge)
    db.session.flush()

    competition = None
    wave = None
    should_create_competition = launch_mode not in {'single_room', 'challenge_only'} or bool(competition_name)
    if should_create_competition:
        competition = create_competition_record(
            competition_name or f'{title} Competition',
            challenge_id=new_challenge.id,
            created_by=session['user_id'],
            format=challenge_usage_to_format(launch_mode),
            stage=stage_type or 'practice',
            status='scheduled' if launch_mode in {'qualification', 'qualifier_bracket', 'bulk_rooms', 'auto_pair_live'} else (stage_type or 'practice'),
            max_participants=max_participants,
            room_mode=room_mode,
            players_per_wave=players_per_wave,
            room_visibility=room_visibility,
            start_at=start_at,
            end_at=end_at,
            auto_start=auto_start,
            auto_submit=auto_submit,
            allowed_attempts=allowed_attempts,
            tie_break_rule=tie_break_rule,
            advance_rule=advance_rule or 'top_32',
            fair_play_strictness=fair_play_strictness
        )
        if launch_mode in {'bulk_rooms', 'auto_pair_live', 'qualification', 'qualifier_bracket'}:
            wave = create_wave_record(
                competition,
                wave_name or 'Wave A',
                challenge_id=new_challenge.id,
                status='live' if auto_start and launch_mode != 'auto_pair_live' else 'scheduled',
                start_at=start_at,
                end_at=end_at,
                players_expected=len(ordered_bulk_players) if ordered_bulk_players else max_participants
            )
        add_competition_assignments(competition, parse_admin_assignment_lines(assignment_lines), wave=wave)

    rooms_created = []
    new_room = None
    tournament = None
    if launch_mode == 'single_room':
        new_room = create_competition_room(
            new_challenge.id,
            competition=competition,
            status='running' if auto_start else 'waiting',
            is_public=room_is_public
        )
        rooms_created.append(new_room)
    elif launch_mode == 'auto_pair_live':
        new_room = create_competition_room(
            new_challenge.id,
            competition=competition,
            wave=wave,
            status='waiting',
            is_public=room_is_public
        )
        rooms_created.append(new_room)
        if wave:
            wave.rooms_created = 1
        if auto_start:
            set_auto_pair_competition_live(competition, wave=wave)
    elif launch_mode in {'bulk_rooms', 'qualification', 'qualifier_bracket'}:
        if room_mode == 'solo':
            for player in ordered_bulk_players:
                room = create_competition_room(
                    new_challenge.id,
                    competition=competition,
                    wave=wave,
                    player1_id=player.id,
                    status='running' if auto_start else 'waiting',
                    is_public=room_is_public
                )
                rooms_created.append(room)
        else:
            for left_player, right_player in pair_players_for_rooms(ordered_bulk_players, pairing_method):
                room = create_competition_room(
                    new_challenge.id,
                    competition=competition,
                    wave=wave,
                    player1_id=left_player.id,
                    player2_id=right_player.id,
                    status='running' if auto_start else 'waiting',
                    is_public=room_is_public
                )
                rooms_created.append(room)
        if wave:
            wave.rooms_created = len(rooms_created)
        new_room = rooms_created[0] if rooms_created else None
    elif launch_mode == 'bracket':
        tournament = create_tournament_from_players(
            competition_name or f'{title} Bracket',
            len(ordered_bulk_players),
            new_challenge.id,
            ordered_bulk_players,
            auto_advance=True,
            competition=competition,
            created_by=session['user_id']
        )
        rooms_created = Room.query.join(TournamentMatch, TournamentMatch.room_id == Room.id).filter(TournamentMatch.tournament_id == tournament.id).all()
        new_room = rooms_created[0] if rooms_created else None
    elif launch_mode == 'challenge_only':
        new_room = None

    db.session.commit()
    if auto_start and rooms_created:
        for room in rooms_created:
            start_room_timer_if_needed(room)

    invite_stats = {'sent': 0, 'failed': 0, 'skipped': 0, 'total': 0}
    if share_with_email and new_room and launch_mode == 'single_room':
        invite_stats = send_room_invites(new_room, request.form.get('invite_message') or '')
    
    return jsonify({
        'success': True,
        'challenge_id': new_challenge.id,
        'launch_mode': launch_mode,
        'room_code': new_room.room_code if new_room else None,
        'room_id': new_room.id if new_room else None,
        'rooms_created': len(rooms_created),
        'room_codes': [room.room_code for room in rooms_created[:20]],
        'competition_id': competition.id if competition else None,
        'tournament_id': tournament.id if tournament else None,
        'is_public': bool(new_room.is_public) if new_room else room_is_public,
        'challenge_type': challenge_type,
        'invite_url': room_invite_url(new_room) if new_room else None,
        'invite_stats': invite_stats
    })

@app.route('/admin/room/<int:room_id>/action', methods=['POST'])
@admin_required
def room_action(room_id):
    action = request.json.get('action')
    room = db.session.get(Room, room_id)
    
    if not room:
        return jsonify({'success': False, 'error': 'Room not found'}), 404
    
    if action == 'start':
        if room.status == 'waiting' or room.status == 'paused':
            competition = db.session.get(Competition, room.competition_id) if room.competition_id else None
            if is_auto_pair_competition(competition) and not (room.player1_id and room.player2_id):
                wave = db.session.get(CompetitionWave, room.wave_id) if room.wave_id else None
                set_auto_pair_competition_live(competition, wave=wave)
                room.status = 'waiting'
                room.started_by = session['user_id']
                db.session.commit()
                socketio.emit('system_announcement', {
                    'message': 'Auto-pair competition is live. Players will be matched in pairs and each room starts when both players arrive.'
                }, room=str(room_id))
            else:
                start_room_match(room, started_by=session['user_id'])
    elif action == 'pause':
        if room.status == 'running':
            room.status = 'paused'
            db.session.commit()
            emit_challenge_paused(room)
    elif action == 'resume':
        if room.status == 'paused':
            room.status = 'running'
            db.session.commit()
            emit_challenge_resumed(room)
    elif action == 'add_time':
        seconds = int((request.json or {}).get('seconds', 30))
        room_timers[room_id] = room_timers.get(room_id, room.challenge.time_limit if room.challenge else 0) + seconds
        socketio.emit('timer_tick', {'remaining': room_timers[room_id]}, room=str(room_id))
    elif action == 'end':
        room.status = 'ended'
        room.ended_at = datetime.now(timezone.utc)
        finalize_room_results(room)
        db.session.commit()
        room_timers[room_id] = 0
        socketio.emit('challenge_ended', {'room_id': room_id}, room=str(room_id))
    elif action == 'reset':
        Submission.query.filter_by(room_id=room_id).delete()
        room.status = 'waiting'
        room.player1_id = None
        room.player2_id = None
        room.ended_at = None
        db.session.commit()
        room_timers[room_id] = 0
    elif action == 'make_public':
        room.is_public = True
        db.session.commit()
    elif action == 'make_private':
        room.is_public = False
        db.session.commit()
    
    return jsonify({'success': True, 'is_public': bool(room.is_public)})

@app.route('/admin/kick', methods=['POST'])
@admin_required
def kick_player():
    data = request.json
    username = data.get('username')
    room_id = data.get('room_id')
    
    room = db.session.get(Room, room_id)
    kicked = False
    target_user = User.query.filter_by(username=username).first()
    if room:
        if room.player1 and room.player1.username == username:
            room.player1_id = None
            kicked = True
        elif room.player2 and room.player2.username == username:
            room.player2_id = None
            kicked = True
        if target_user:
            record_room_access(room, target_user, 'player', status='suspended', granted_by=session.get('user_id'), reason='Removed by admin')
    
    if room_id in room_spectators and username in room_spectators[room_id]:
        room_spectators[room_id].discard(username)
        if not room_spectators[room_id]:
            del room_spectators[room_id]
        emit_spectator_list(room_id)
        kicked = True
    
    if room and kicked:
        db.session.commit()
    
    socketio.emit('kicked', {'message': 'You were removed by the admin'}, room=f"user_{username}")
    return jsonify({'success': True, 'removed': kicked})

@app.route('/admin/room/<int:room_id>/grant-player', methods=['POST'])
@admin_required
def admin_grant_room_player(room_id):
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    room = db.session.get(Room, room_id)
    user = User.query.filter_by(username=username).first()
    if not room or not user:
        return jsonify({'success': False, 'error': 'Room or user not found'}), 404
    if user.role == 'admin':
        return jsonify({'success': False, 'error': 'Admins already have room access'}), 400
    if room.status != 'waiting':
        return jsonify({'success': False, 'error': 'Player access can only be granted before the match starts'}), 400
    if room.player1_id and room.player2_id and user.id not in {room.player1_id, room.player2_id}:
        return jsonify({'success': False, 'error': 'This room already has two players'}), 400

    if room.player1_id == user.id or room.player2_id == user.id:
        role = 'player1' if room.player1_id == user.id else 'player2'
    elif not room.player1_id:
        room.player1_id = user.id
        role = 'player1'
    elif not room.player2_id:
        room.player2_id = user.id
        role = 'player2'
    else:
        return jsonify({'success': False, 'error': 'This room is full'}), 400

    record_room_access(room, user, 'player', status='active', granted_by=session.get('user_id'), reason='Player access granted by admin')
    if room.id in room_spectators and username in room_spectators[room.id]:
        room_spectators[room.id].discard(username)
        if not room_spectators[room.id]:
            del room_spectators[room.id]
        emit_spectator_list(room.id)
    db.session.commit()
    emit_room_players(room, username=username, message=f'{username} was granted player access by admin.')
    socketio.emit('room_access_granted', {
        'room_id': room.id,
        'role': role,
        'redirect': url_for('arena', room_id=room.id)
    }, room=f"user_{username}")
    return jsonify({'success': True, 'role': role})

@app.route('/admin/tournament/create', methods=['POST'])
@admin_required
def admin_create_tournament():
    data = request.get_json(silent=True) or request.form
    name = (data.get('name') or '').strip()
    try:
        size = int(data.get('size', 8))
        challenge_id = int(data.get('challenge_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Invalid tournament size or challenge'}), 400

    participant_ids = data.get('participant_ids', [])
    if isinstance(participant_ids, str):
        participant_ids = [value for value in participant_ids.split(',') if value.strip()]
    try:
        participant_ids = [int(pid) for pid in participant_ids]
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Invalid participant list'}), 400

    if size not in TOURNAMENT_SIZES:
        return jsonify({'success': False, 'error': 'Tournament size must be 4, 8, 16, 32, 64, or 128'}), 400
    if not name:
        return jsonify({'success': False, 'error': 'Tournament name is required'}), 400
    if len(set(participant_ids)) != size:
        return jsonify({'success': False, 'error': f'Select exactly {size} unique players'}), 400
    challenge = db.session.get(Challenge, challenge_id)
    if not challenge or not challenge.is_active:
        return jsonify({'success': False, 'error': 'Active challenge not found'}), 404

    users = User.query.filter(User.id.in_(participant_ids), User.role == 'player').all()
    if len(users) != size:
        return jsonify({'success': False, 'error': 'All participants must be player accounts'}), 400

    ordered_users = sorted(users, key=lambda player: participant_ids.index(player.id))
    auto_value = data.get('auto_advance', True)
    auto_advance = auto_value if isinstance(auto_value, bool) else str(auto_value).lower() != 'false'
    tournament = Tournament(
        name=name,
        size=size,
        challenge_id=challenge_id,
        status='live',
        auto_advance=auto_advance,
        created_by=session['user_id'],
        started_at=datetime.now(timezone.utc)
    )
    db.session.add(tournament)
    db.session.flush()

    for seed, player in enumerate(ordered_users, start=1):
        db.session.add(TournamentParticipant(
            tournament_id=tournament.id,
            user_id=player.id,
            seed=seed,
            status='active',
            position='Participant'
        ))

    seeded = []
    left = 0
    right = len(ordered_users) - 1
    while left <= right:
        seeded.append(ordered_users[left])
        if left != right:
            seeded.append(ordered_users[right])
        left += 1
        right -= 1

    round_name = tournament_round_name(size)
    for index in range(0, len(seeded), 2):
        create_tournament_match(
            tournament,
            1,
            round_name,
            (index // 2) + 1,
            seeded[index].id,
            seeded[index + 1].id
        )

    log_admin_action(
        session['user_id'],
        'create_tournament',
        f'Created {size}-player tournament',
        tournament_id=tournament.id,
        admin_note=name
    )
    db.session.commit()
    socketio.emit('tournament_bracket_update', {'tournament': serialize_tournament(tournament)}, room=f"tournament_{tournament.id}")
    notify_users_by_email(
        ordered_users,
        f'You were added to tournament: {name}',
        (
            f'You have been added to the {name} tournament in UI Battle Arena.\n\n'
            f'Challenge: {challenge.title}\n'
            f'Players: {size}\n\n'
            'Sign in to view your match room and bracket.'
        )
    )
    return jsonify({'success': True, 'tournament_id': tournament.id, 'redirect': url_for('tournament_detail', tournament_id=tournament.id)})

@app.route('/api/competition/<int:competition_id>/leaderboard')
@admin_required
def api_competition_leaderboard(competition_id):
    competition = db.session.get(Competition, competition_id)
    if not competition:
        return jsonify({'success': False, 'error': 'Competition not found'}), 404
    rows = qualification_rows(competition_id=competition.id)
    return jsonify({
        'success': True,
        'competition': serialize_competition(competition),
        'leaderboard': [
            {
                'rank': row['rank'],
                'user_id': row['user'].id,
                'username': row['user'].username,
                'score': row['score'],
                'completed': row['completed'],
                'submitted_at': row['submitted_at'].isoformat() if row['submitted_at'] else None,
                'fair_play_warnings': row['fair_play_warnings'],
                'disqualified': row['disqualified'],
                'room_id': row['room'].id if row.get('room') else None,
                'room_code': row['room'].room_code if row.get('room') else None
            }
            for row in rows
        ]
    })

@app.route('/admin/competition/<int:competition_id>/advance-to-bracket', methods=['POST'])
@admin_required
def admin_competition_advance_to_bracket(competition_id):
    data = request.get_json(silent=True) or request.form
    competition = db.session.get(Competition, competition_id)
    if not competition:
        return jsonify({'success': False, 'error': 'Competition not found'}), 404
    if not competition.challenge_id:
        return jsonify({'success': False, 'error': 'Competition has no challenge target'}), 400

    selected_ids = parse_int_list(data.get('participant_ids', []))
    top_n = parse_positive_int(data.get('top_n'), 32, 4, 128)
    if selected_ids:
        ordered_ids = selected_ids
    else:
        rows = [row for row in qualification_rows(competition_id=competition.id) if not row['disqualified']]
        ordered_ids = [row['user'].id for row in rows[:top_n]]

    size = len(ordered_ids)
    if size not in TOURNAMENT_SIZES:
        return jsonify({'success': False, 'error': 'Bracket entrants must be exactly 4, 8, 16, 32, 64, or 128 players'}), 400

    users = User.query.filter(User.id.in_(ordered_ids), User.role == 'player').all()
    if len(users) != size:
        return jsonify({'success': False, 'error': 'All selected entrants must be player accounts'}), 400
    users_by_id = {player.id: player for player in users}
    ordered_users = [users_by_id[player_id] for player_id in ordered_ids]

    tournament = create_tournament_from_players(
        f'{competition.name} Bracket',
        size,
        competition.challenge_id,
        ordered_users,
        auto_advance=parse_bool_value(data.get('auto_advance'), True),
        competition=competition,
        created_by=session['user_id']
    )
    log_admin_action(
        session['user_id'],
        'advance_competition_to_bracket',
        f'Advanced {size} players from qualification leaderboard',
        tournament_id=tournament.id,
        admin_note=competition.name
    )
    db.session.commit()
    socketio.emit('tournament_bracket_update', {'tournament': serialize_tournament(tournament)}, room=f"tournament_{tournament.id}")
    return jsonify({'success': True, 'tournament_id': tournament.id, 'redirect': url_for('tournament_detail', tournament_id=tournament.id)})

@app.route('/admin/competition/<int:competition_id>/assignment', methods=['POST'])
@admin_required
def admin_competition_assignment(competition_id):
    data = request.get_json(silent=True) or request.form
    competition = db.session.get(Competition, competition_id)
    if not competition:
        return jsonify({'success': False, 'error': 'Competition not found'}), 404
    admin_id = parse_positive_int(data.get('admin_id'), 0, 1)
    role = (data.get('role') or 'room_admin').strip()[:40]
    wave_id = parse_positive_int(data.get('wave_id'), 0, 0) or None
    if wave_id and not CompetitionWave.query.filter_by(id=wave_id, competition_id=competition.id).first():
        return jsonify({'success': False, 'error': 'Wave not found for this competition'}), 404
    admin = db.session.get(User, admin_id)
    if not admin or admin.role != 'admin':
        return jsonify({'success': False, 'error': 'Select a valid admin user'}), 400
    assignment = CompetitionAdminAssignment(
        competition_id=competition.id,
        wave_id=wave_id,
        admin_id=admin.id,
        role=role,
        room_range_start=parse_positive_int(data.get('room_range_start'), 0, 0) or None,
        room_range_end=parse_positive_int(data.get('room_range_end'), 0, 0) or None,
        notes=(data.get('notes') or '').strip()[:500] or None
    )
    db.session.add(assignment)
    db.session.commit()
    return jsonify({'success': True, 'competition': serialize_competition(competition)})

@app.route('/admin/task/create', methods=['POST'])
@admin_required
def admin_task_create():
    data = request.get_json(silent=True) or request.form
    title = (data.get('title') or '').strip()[:160]
    if not title:
        return jsonify({'success': False, 'error': 'Task title is required'}), 400
    assigned_admin_id = parse_positive_int(data.get('assigned_admin_id') or data.get('admin_id'), 0, 1) or None
    if assigned_admin_id:
        assigned_admin = db.session.get(User, assigned_admin_id)
        if not assigned_admin or assigned_admin.role != 'admin':
            return jsonify({'success': False, 'error': 'Select a valid assigned admin'}), 400
    competition_id = parse_positive_int(data.get('competition_id'), 0, 0) or None
    wave_id = parse_positive_int(data.get('wave_id'), 0, 0) or None
    room_id = parse_positive_int(data.get('room_id'), 0, 0) or None
    competition = db.session.get(Competition, competition_id) if competition_id else None
    if competition_id and not competition:
        return jsonify({'success': False, 'error': 'Competition not found'}), 404
    if wave_id and not CompetitionWave.query.filter_by(id=wave_id, competition_id=competition_id).first():
        return jsonify({'success': False, 'error': 'Wave not found for this competition'}), 404
    room = db.session.get(Room, room_id) if room_id else None
    if room_id and not room:
        return jsonify({'success': False, 'error': 'Room not found'}), 404
    if room and competition_id and room.competition_id != competition_id:
        return jsonify({'success': False, 'error': 'Room does not belong to the selected competition'}), 400

    room_range_start = parse_positive_int(data.get('room_range_start'), 0, 0) or None
    room_range_end = parse_positive_int(data.get('room_range_end'), 0, 0) or None
    task = AdminTask(
        title=title,
        description=(data.get('description') or '').strip()[:1200] or None,
        task_type=(data.get('task_type') or 'room_watch').strip()[:40],
        priority=(data.get('priority') or 'normal').strip()[:20],
        status='open',
        competition_id=competition_id,
        wave_id=wave_id,
        room_id=room_id,
        room_range_start=room_range_start,
        room_range_end=room_range_end,
        assigned_admin_id=assigned_admin_id,
        created_by=session.get('user_id'),
        due_at=(data.get('due_at') or '').strip()[:80] or None
    )
    db.session.add(task)

    assignment = None
    if competition and assigned_admin_id:
        assignment = CompetitionAdminAssignment(
            competition_id=competition.id,
            wave_id=wave_id,
            admin_id=assigned_admin_id,
            role=task.task_type or 'room_admin',
            room_range_start=room_range_start,
            room_range_end=room_range_end,
            notes=f'Task: {title}'
        )
        db.session.add(assignment)
    db.session.commit()
    if assigned_admin_id:
        socketio.emit('admin_task_assigned', serialize_admin_task(task), room=f"user_{task.assigned_admin.username}")
    return jsonify({
        'success': True,
        'task': serialize_admin_task(task),
        'assignment_id': assignment.id if assignment else None
    })

@app.route('/admin/task/<int:task_id>/status', methods=['POST'])
@admin_required
def admin_task_status(task_id):
    task = db.session.get(AdminTask, task_id)
    if not task:
        return jsonify({'success': False, 'error': 'Task not found'}), 404
    user = get_current_user()
    if task.assigned_admin_id and task.assigned_admin_id != user.id and user.role != 'admin':
        return jsonify({'success': False, 'error': 'You cannot update this task'}), 403
    data = request.get_json(silent=True) or request.form
    status = (data.get('status') or '').strip()
    if status not in {'open', 'acknowledged', 'active', 'completed', 'missed'}:
        return jsonify({'success': False, 'error': 'Invalid task status'}), 400
    task.status = status
    if status in {'acknowledged', 'active'} and not task.acknowledged_at:
        task.acknowledged_at = datetime.now(timezone.utc)
    if status == 'completed':
        task.completed_at = datetime.now(timezone.utc)
    if status != 'completed':
        task.completed_at = None
    db.session.commit()
    return jsonify({'success': True, 'task': serialize_admin_task(task)})

@app.route('/admin/dispute/<int:case_id>/resolve', methods=['POST'])
@admin_required
def admin_resolve_dispute(case_id):
    data = request.get_json(silent=True) or request.form
    case = db.session.get(DisputeCase, case_id)
    if not case:
        return jsonify({'success': False, 'error': 'Dispute case not found'}), 404
    case.status = (data.get('status') or 'resolved').strip()[:30]
    case.resolution = (data.get('resolution') or '').strip()[:1000] or None
    case.resolved_by = session['user_id']
    case.resolved_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/tournament/<int:tournament_id>/match/<int:match_id>/advance', methods=['POST'])
@admin_required
def admin_advance_tournament_match(tournament_id, match_id):
    data = request.get_json(silent=True) or {}
    match = db.session.get(TournamentMatch, match_id)
    if not match or match.tournament_id != tournament_id:
        return jsonify({'success': False, 'error': 'Tournament match not found'}), 404
    try:
        winner_id = int(data.get('winner_id'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'winner_id is required'}), 400
    reason = (data.get('reason') or 'Manual admin advancement').strip()
    note = (data.get('admin_note') or '').strip()
    if not complete_tournament_match(match, winner_id, 'manual'):
        return jsonify({'success': False, 'error': 'Winner must be one of the match players'}), 400
    log_admin_action(session['user_id'], 'manual_advance', reason, tournament_id=tournament_id, tournament_match_id=match.id, player_id=winner_id, admin_note=note)
    db.session.commit()
    socketio.emit('tournament_bracket_update', {'tournament': serialize_tournament(match.tournament)}, room=f"tournament_{tournament_id}")
    socketio.emit('tournament_notification', {'message': 'Admin advanced a player in the tournament.'}, room=f"tournament_{tournament_id}")
    return jsonify({'success': True, 'tournament': serialize_tournament(match.tournament)})

@app.route('/admin/tournament/<int:tournament_id>/player/<int:player_id>/discipline', methods=['POST'])
@admin_required
def admin_discipline_tournament_player(tournament_id, player_id):
    data = request.get_json(silent=True) or {}
    action_type = (data.get('action_type') or 'disqualify').strip()
    reason = (data.get('reason') or '').strip()
    admin_note = (data.get('admin_note') or '').strip()
    if action_type not in {'kick', 'disqualify', 'remove', 'force_qualify'}:
        return jsonify({'success': False, 'error': 'Invalid action type'}), 400
    if not reason:
        return jsonify({'success': False, 'error': 'Reason is required'}), 400
    participant = get_participant(tournament_id, player_id)
    if not participant:
        return jsonify({'success': False, 'error': 'Participant not found'}), 404

    if action_type == 'force_qualify':
        participant.status = 'active'
        participant.position = 'Force Qualified'
    else:
        active_matches = TournamentMatch.query.filter(
            TournamentMatch.tournament_id == tournament_id,
            TournamentMatch.status.in_(['waiting', 'live']),
            ((TournamentMatch.player1_id == player_id) | (TournamentMatch.player2_id == player_id))
        ).all()
        for match in active_matches:
            opponent_id = match.player2_id if match.player1_id == player_id else match.player1_id
            if opponent_id:
                complete_tournament_match(match, opponent_id, 'manual')
            else:
                match.status = 'disqualified'
        participant.status = 'kicked' if action_type == 'kick' else 'disqualified'
        participant.position = 'Disqualified' if action_type == 'disqualify' else 'Removed'
    participant.reason = reason
    participant.admin_note = admin_note or None

    log_admin_action(session['user_id'], action_type, reason, tournament_id=tournament_id, player_id=player_id, admin_note=admin_note)
    db.session.commit()
    user = db.session.get(User, player_id)
    if user:
        socketio.emit('tournament_kick', {
            'message': f'Tournament action: {action_type}. Reason: {reason}',
            'reason': reason,
            'admin_note': admin_note
        }, room=f"user_{user.username}")
    tournament = db.session.get(Tournament, tournament_id)
    socketio.emit('tournament_bracket_update', {'tournament': serialize_tournament(tournament)}, room=f"tournament_{tournament_id}")
    return jsonify({'success': True})

@app.route('/admin/tournament/<int:tournament_id>/score-override', methods=['POST'])
@admin_required
def admin_tournament_score_override(tournament_id):
    data = request.get_json(silent=True) or {}
    try:
        match_id = int(data.get('match_id'))
        player_id = int(data.get('player_id'))
        score = float(data.get('score'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'match_id, player_id, and score are required'}), 400
    reason = (data.get('reason') or 'Manual score override').strip()
    admin_note = (data.get('admin_note') or '').strip()
    match = db.session.get(TournamentMatch, match_id)
    if not match or match.tournament_id != tournament_id or player_id not in {match.player1_id, match.player2_id}:
        return jsonify({'success': False, 'error': 'Invalid match/player'}), 400
    save_match_result(match, player_id, score, match.winner_id == player_id, 'manual')
    update_participant_from_result(tournament_id, player_id, score)
    log_admin_action(session['user_id'], 'score_override', reason, tournament_id=tournament_id, tournament_match_id=match.id, player_id=player_id, admin_note=admin_note)
    db.session.commit()
    socketio.emit('tournament_score_update', {'tournament_id': tournament_id, 'match': serialize_tournament_match(match)}, room=f"tournament_{tournament_id}")
    return jsonify({'success': True})

# ========== CHALLENGE MANAGEMENT ROUTES ==========
@app.route('/admin/challenge/<int:challenge_id>/delete', methods=['DELETE'])
@admin_required
def delete_challenge(challenge_id):
    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return jsonify({'success': False, 'error': 'Challenge not found'}), 404

    if request.args.get('mode') == 'soft':
        challenge.is_active = False
        db.session.commit()
        return jsonify({'success': True, 'deleted': 'soft'})

    affected_user_ids = set()
    for room in list(challenge.rooms):
        affected_user_ids.update(delete_room_data(room))

    target_image_path = challenge.target_image_path
    db.session.delete(challenge)
    sync_users_by_id(affected_user_ids)
    db.session.commit()

    if target_image_path:
        upload_path = os.path.abspath(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], target_image_path))
        upload_root = os.path.abspath(os.path.join(app.root_path, app.config['UPLOAD_FOLDER']))
        if upload_path.startswith(upload_root) and os.path.exists(upload_path):
            try:
                os.remove(upload_path)
            except OSError:
                pass

    return jsonify({'success': True, 'deleted': 'permanent'})

@app.route('/admin/challenge/<int:challenge_id>/details')
@admin_required
def challenge_details(challenge_id):
    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return jsonify({'success': False, 'error': 'Challenge not found'}), 404
    
    return jsonify({
        'success': True,
        'id': challenge.id,
        'title': challenge.title,
        'description': challenge.description,
        'difficulty': challenge.difficulty,
        'time_limit': challenge.time_limit,
        'challenge_type': challenge.challenge_type,
        'target_image_url': url_for('static', filename='uploads/' + challenge.target_image_path) if challenge.target_image_path else None,
        'target_html': challenge.target_html,
        'target_css': challenge.target_css,
        'target_js': challenge.target_js or '',
        'starter_html': challenge.starter_html if challenge.starter_html is not None else (challenge.target_html or ''),
        'starter_css': challenge.starter_css or '',
        'starter_js': challenge.starter_js or '',
        'html_locked': challenge.html_locked,
        'is_active': challenge.is_active
    })

@app.route('/admin/challenge/<int:challenge_id>/restore', methods=['POST'])
@admin_required
def restore_challenge(challenge_id):
    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return jsonify({'success': False, 'error': 'Challenge not found'}), 404
    
    challenge.is_active = True
    db.session.commit()
    return jsonify({'success': True})

# ========== USER MANAGEMENT ROUTES ==========
@app.route('/admin/user/<int:user_id>/delete', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    if user.id == session.get('user_id'):
        return jsonify({'success': False, 'error': 'You cannot delete your own admin account'}), 400

    if user.role == 'admin' and User.query.filter_by(role='admin').count() <= 1:
        return jsonify({'success': False, 'error': 'Cannot delete the last admin'}), 400
    
    affected_user_ids = set()
    for room in Room.query.filter((Room.player1_id == user_id) | (Room.player2_id == user_id)).all():
        affected_user_ids.update({room.player1_id, room.player2_id})

    Submission.query.filter_by(user_id=user_id).delete()
    ChatMessage.query.filter_by(user_id=user_id).delete()
    AwardCard.query.filter_by(user_id=user_id).delete()
    AwardCard.query.filter_by(awarded_by=user_id).delete()
    Room.query.filter_by(player1_id=user_id).update({Room.player1_id: None})
    Room.query.filter_by(player2_id=user_id).update({Room.player2_id: None})
    db.session.delete(user)
    remove_profile_record(user_id)
    sync_users_by_id(affected_user_ids - {user_id})
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/user/<int:user_id>/role', methods=['POST'])
@admin_required
def toggle_user_role(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    action = request.json.get('action')
    
    if action == 'promote' and user.role != 'admin':
        user.role = 'admin'
    elif action == 'demote' and user.role == 'admin':
        admin_count = User.query.filter_by(role='admin').count()
        if admin_count <= 1:
            return jsonify({'success': False, 'error': 'Cannot demote the last admin'}), 400
        user.role = 'player'
    else:
        return jsonify({'success': False, 'error': 'Invalid action'}), 400
    
    db.session.commit()
    return jsonify({'success': True, 'new_role': user.role})

@app.route('/admin/user/<int:user_id>/rename', methods=['POST'])
@admin_required
def rename_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404

    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()[:80]
    if not username:
        return jsonify({'success': False, 'error': 'Real name is required'}), 400

    existing = User.query.filter(User.username == username, User.id != user.id).first()
    if existing:
        return jsonify({'success': False, 'error': 'Another user already has that name'}), 400

    old_username = user.username
    user.username = username
    db.session.commit()

    if user.id == session.get('user_id'):
        session['username'] = user.username

    return jsonify({'success': True, 'username': user.username, 'old_username': old_username})

@app.route('/admin/user/<int:user_id>/reset-stats', methods=['POST'])
@admin_required
def reset_player_stats(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    user.matches_played = 0
    user.best_accuracy = 0
    user.total_wins = 0
    user.leaderboard_unlocked_at = None
    Submission.query.filter_by(user_id=user_id, is_final=False).delete()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/room/<int:room_id>/delete', methods=['DELETE'])
@admin_required
def delete_room(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({'success': False, 'error': 'Room not found'}), 404

    try:
        affected_user_ids = delete_room_data(room)
        sync_users_by_id(affected_user_ids)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception('Room delete failed for room %s', room_id)
        return jsonify({'success': False, 'error': 'Could not delete room because related match data could not be cleared.'}), 500

    return jsonify({'success': True})

# ========== ARENA & GAMEPLAY ROUTES ==========
@app.route('/arena/<int:room_id>')
@login_required
def arena(room_id):
    ensure_schema_upgrades()
    user = get_current_user()
    room = db.session.get(Room, room_id)
    
    if not room:
        return redirect(url_for('dashboard'))
    if room_access_is_suspended(room, user):
        flash('You were removed from this match by an admin.', 'warning')
        return redirect(url_for('dashboard'))
    
    challenge = room.challenge
    player1_username = room.player1.username if room.player1 else None
    player2_username = room.player2.username if room.player2 else None
    admin_user = User.query.filter_by(role='admin').first()
    p1_sub = get_best_room_submission(room.id, room.player1_id) if room.player1_id else None
    p2_sub = get_best_room_submission(room.id, room.player2_id) if room.player2_id else None
    
    user_role = 'spectator'
    if room.player1_id == user.id:
        user_role = 'player1'
    elif room.player2_id == user.id:
        user_role = 'player2'
    elif user.role == 'admin':
        user_role = 'admin'
    elif not get_room_access(room, user):
        record_room_access(room, user, 'spectator')
        db.session.commit()
    
    return render_template('arena.html',
                         room=room,
                         challenge=challenge,
                         user=user,
                         user_role=user_role,
                         player1_username=player1_username,
                         player2_username=player2_username,
                         admin_username=admin_user.username if admin_user else 'Admin',
                         p1_accuracy=round(float(p1_sub.accuracy or 0), 1) if p1_sub else 0,
                         p2_accuracy=round(float(p2_sub.accuracy or 0), 1) if p2_sub else 0)

@app.route('/results/<int:room_id>')
@login_required
def results(room_id):
    ensure_schema_upgrades()
    user = get_current_user()
    room = db.session.get(Room, room_id)
    
    if not room:
        return redirect(url_for('dashboard'))
    
    p1_sub = get_best_room_submission(room.id, room.player1_id) if room.player1_id else None
    p2_sub = get_best_room_submission(room.id, room.player2_id) if room.player2_id else None
    best_submissions = [sub for sub in [p1_sub, p2_sub] if sub]
    result_rows = sorted(best_submissions, key=lambda sub: submission_rank_tuple(sub, room.challenge), reverse=True)
    
    winner_id = get_room_winner_id(room)
    if winner_id:
        winner_user = db.session.get(User, winner_id)
        winner = winner_user.username if winner_user else 'Winner'
    elif p1_sub or p2_sub:
        winner = 'DRAW'
    else:
        winner = None
    
    if room.player1_id:
        update_user_stats(room.player1_id)
    if room.player2_id:
        update_user_stats(room.player2_id)
    finalize_room_results(room)
    db.session.commit()
    result_analysis = {
        room.player1_id: build_submission_analysis(p1_sub, room.challenge, p2_sub) if room.player1_id else None,
        room.player2_id: build_submission_analysis(p2_sub, room.challenge, p1_sub) if room.player2_id else None
    }
    
    return render_template('results.html',
                         room=room,
                         p1_sub=p1_sub,
                         p2_sub=p2_sub,
                         result_rows=result_rows,
                         winner=winner,
                         result_analysis=result_analysis,
                         user=user)

@app.route('/tournament')
@login_required
def tournament():
    latest = Tournament.query.order_by(Tournament.created_at.desc()).first()
    if latest:
        return redirect(url_for('tournament_detail', tournament_id=latest.id))
    user = get_current_user()
    return render_template('tournament.html',
                           user=user,
                           tournament=None,
                           tournaments=[])

@app.route('/tournament/<int:tournament_id>')
@login_required
def tournament_detail(tournament_id):
    ensure_schema_upgrades()
    user = get_current_user()
    tournament_obj = db.session.get(Tournament, tournament_id)
    if not tournament_obj:
        return redirect(url_for('dashboard'))
    return render_template('tournament.html',
                           user=user,
                           tournament=serialize_tournament(tournament_obj),
                           tournaments=Tournament.query.order_by(Tournament.created_at.desc()).all())

@app.route('/api/tournament/<int:tournament_id>')
@login_required
def tournament_api(tournament_id):
    tournament_obj = db.session.get(Tournament, tournament_id)
    if not tournament_obj:
        return jsonify({'success': False, 'error': 'Tournament not found'}), 404
    return jsonify({'success': True, 'tournament': serialize_tournament(tournament_obj)})

@app.route('/admin/tournament/<int:tournament_id>/certificate-settings', methods=['POST'])
@admin_required
def update_tournament_certificate_settings(tournament_id):
    ensure_schema_upgrades()
    tournament_obj = db.session.get(Tournament, tournament_id)
    if not tournament_obj:
        return jsonify({'success': False, 'error': 'Tournament not found'}), 404

    data = request.get_json(silent=True) or {}
    raw_officials = data.get('officials') if isinstance(data.get('officials'), list) else []
    officials = []
    for item in raw_officials[:6]:
        if not isinstance(item, dict):
            continue
        officials.append({
            'name': str(item.get('name') or '')[:120],
            'title': str(item.get('title') or '')[:120],
            'signature': str(item.get('signature') or '')[:300000]
        })

    if not officials:
        officials = [
            {
                'name': str(data.get('official_1_name') or '')[:120],
                'title': str(data.get('official_1_title') or '')[:120],
                'signature': str(data.get('official_1_signature') or '')[:300000]
            },
            {
                'name': str(data.get('official_2_name') or '')[:120],
                'title': str(data.get('official_2_title') or '')[:120],
                'signature': str(data.get('official_2_signature') or '')[:300000]
            }
        ]

    allowed = {
        'competition_name': str(data.get('competition_name') or tournament_obj.name or '')[:160],
        'regards_text': str(data.get('regards_text') or 'has successfully completed and earned the official standing of')[:220],
        'sponsor_name': str(data.get('sponsor_name') or '')[:120],
        'officials': officials,
        'official_1_name': officials[0]['name'] if len(officials) > 0 else '',
        'official_1_title': officials[0]['title'] if len(officials) > 0 else '',
        'official_1_signature': officials[0]['signature'] if len(officials) > 0 else '',
        'official_2_name': officials[1]['name'] if len(officials) > 1 else '',
        'official_2_title': officials[1]['title'] if len(officials) > 1 else '',
        'official_2_signature': officials[1]['signature'] if len(officials) > 1 else '',
        'sponsor_logos': [
            str(item)[:300000]
            for item in (data.get('sponsor_logos') if isinstance(data.get('sponsor_logos'), list) else [])
        ][:4],
        'player_names': {
            str(key): str(value)[:120]
            for key, value in (data.get('player_names') if isinstance(data.get('player_names'), dict) else {}).items()
        }
    }
    tournament_obj.certificate_settings = json.dumps(allowed)
    db.session.commit()
    socketio.emit('tournament_bracket_update', {'tournament': serialize_tournament(tournament_obj)}, room=f"tournament_{tournament_id}")
    return jsonify({'success': True, 'certificate_settings': allowed})

@app.route('/certificate/verify/<certificate_id>')
def verify_certificate(certificate_id):
    participant = TournamentParticipant.query.filter_by(certificate_id=certificate_id).first()
    if not participant:
        return jsonify({'valid': False, 'error': 'Certificate not found'}), 404
    return jsonify({
        'valid': True,
        'certificate_id': participant.certificate_id,
        'username': participant.user.username if participant.user else None,
        'tournament': participant.tournament.name if participant.tournament else None,
        'position': participant.position,
        'final_score': round(participant.final_score or 0, 1),
        'matches_played': participant.matches_played,
        'issued_at': participant.tournament.ended_at.isoformat() if participant.tournament and participant.tournament.ended_at else None
    })

@app.route('/submission/save', methods=['POST'])
@login_required
def save_submission():
    data = request.json or {}
    user = get_current_user()
    room = db.session.get(Room, data.get('room_id'))

    if not room:
        return jsonify({'success': False, 'error': 'Room not found'}), 404
    if user.role == 'admin' or user.id not in {room.player1_id, room.player2_id}:
        return jsonify({'success': False, 'error': 'Only active players can submit scores'}), 403
    if room.status == 'ended':
        return jsonify({'success': False, 'error': 'Match has ended'}), 403

    html_code = data.get('html_code', '')
    css_code = data.get('css_code', '')
    js_code = data.get('js_code', '')
    challenge = room.challenge or db.session.get(Challenge, data.get('challenge_id'))
    accuracy, score_details = deterministic_submission_score(
        challenge,
        html_code,
        css_code,
        js_code,
        data.get('accuracy')
    )
    
    existing = Submission.query.filter_by(
        user_id=user.id,
        room_id=room.id,
        is_final=False
    ).first()
    
    if existing:
        existing.html_code = html_code
        existing.css_code = css_code
        existing.js_code = js_code
        existing.challenge_id = challenge.id if challenge else data.get('challenge_id')
        existing.accuracy = accuracy
        existing.score_details = json.dumps(score_details)
        existing.submitted_at = datetime.now(timezone.utc)
    else:
        submission = Submission(
            user_id=user.id,
            room_id=room.id,
            challenge_id=challenge.id if challenge else data.get('challenge_id'),
            html_code=html_code,
            css_code=css_code,
            js_code=js_code,
            accuracy=accuracy,
            score_details=json.dumps(score_details)
        )
        db.session.add(submission)
    
    db.session.commit()
    broadcast_leaderboard(room.id)
    tournament_match = TournamentMatch.query.filter_by(room_id=room.id).first()
    if tournament_match:
        socketio.emit('tournament_score_update', {
            'tournament_id': tournament_match.tournament_id,
            'match': serialize_tournament_match(tournament_match)
        }, room=f"tournament_{tournament_match.tournament_id}")
    
    return jsonify({'success': True, 'accuracy': accuracy, 'score_details': score_details})


@app.route('/room/invite/<room_code>')
@login_required
def room_invite(room_code):
    user = get_current_user()
    normalized_code = ('#' + str(room_code or '').lstrip('#')).upper()
    room = Room.query.filter(func.upper(Room.room_code) == normalized_code).first()
    if not room or room.status == 'ended':
        flash('That match invite is no longer available.', 'warning')
        return redirect(url_for('dashboard'))
    access_response = room_access_redirect_or_error(room, user, 'player')
    if access_response:
        return access_response

    original_room = room
    role = 'spectator'
    if user.role == 'admin':
        role = 'admin'
    elif room.player1_id == user.id:
        role = 'player1'
    elif room.player2_id == user.id:
        role = 'player2'
    elif is_auto_pair_room(room):
        target_room = find_or_create_auto_pair_room(room, user)
        if not target_room:
            flash('This competition is already full.', 'warning')
            return redirect(url_for('dashboard'))
        room = target_room
        if not room.player1_id:
            room.player1_id = user.id
            role = 'player1'
            record_room_access(room, user, 'player')
        elif not room.player2_id and room.player1_id != user.id:
            room.player2_id = user.id
            role = 'player2'
            record_room_access(room, user, 'player')
        if room.player1_id and room.player2_id and room.status == 'waiting':
            competition = db.session.get(Competition, room.competition_id) if room.competition_id else None
            if is_auto_pair_competition(competition) and competition.status == 'live':
                db.session.commit()
                emit_room_players(room, username=user.username)
                start_room_match(room, started_by=room.started_by or competition.created_by)
                socketio.emit('system_announcement', {'message': 'Your partner joined. Match started automatically.'}, room=str(room.id))
                return redirect(url_for('arena', room_id=room.id, role=role))
        db.session.commit()
    elif room.status == 'waiting' and not room.player1_id:
        room.player1_id = user.id
        record_room_access(room, user, 'player')
        db.session.commit()
        role = 'player1'
    elif room.status == 'waiting' and not room.player2_id and room.player1_id != user.id:
        room.player2_id = user.id
        record_room_access(room, user, 'player')
        db.session.commit()
        role = 'player2'

    emit_room_players(room, username=user.username)
    if original_room.id != room.id:
        socketio.emit('system_announcement', {
            'message': f'{user.username} was moved into the next auto-pair room and is waiting for a partner.'
        }, room=str(original_room.id))
    return redirect(url_for('arena', room_id=room.id, role=role))

@app.route('/admin/room/<int:room_id>/share-email', methods=['POST'])
@admin_required
def admin_share_room_email(room_id):
    if not email_configured():
        return jsonify({'success': False, 'error': smtp_configuration_error()}), 400
    if rate_limited('room-share-email', f"{session.get('user_id')}:{room_id}", limit=5, window_seconds=60 * 60):
        return rate_limit_response('Too many invite emails for this room. Wait a while before sending again.')
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({'success': False, 'error': 'Room not found'}), 404
    if room.status == 'ended':
        return jsonify({'success': False, 'error': 'This room has ended'}), 400
    data = request.get_json(silent=True) or {}
    stats = send_room_invites(room, data.get('message') or '')
    return jsonify({'success': True, 'invite_url': room_invite_url(room), 'invite_stats': stats})

@app.route('/room/join', methods=['POST'])
@login_required
def join_room_route():
    data = request.json or {}
    room_id = data.get('room_id')
    join_as = data.get('join_as', 'player')
    user = get_current_user()
    
    print(f"Join room request: room_id={room_id}, user={user.username if user else 'None'}")
    
    room = db.session.get(Room, room_id)
    
    if not room:
        print(f"Room {room_id} not found")
        return jsonify({'success': False, 'error': 'Room not found'}), 400
    access_response = room_access_redirect_or_error(room, user, 'spectator' if join_as == 'spectator' else 'player', json_response=True)
    if access_response:
        return access_response
    
    print(f"Room status: {room.status}, Player1: {room.player1_id}, Player2: {room.player2_id}")

    if join_as == 'spectator':
        if room.status == 'ended':
            return jsonify({'success': False, 'error': 'This match has ended'}), 400
        record_room_access(room, user, 'spectator')
        db.session.commit()
        return jsonify({'success': True, 'room_id': room_id, 'role': 'spectator'})

    if user.role != 'admin':
        provided_code = str(data.get('room_code') or data.get('match_room_id') or '').strip().upper()
        expected_code = (room.room_code or '').strip().upper()
        accepted_codes = {expected_code}
        if is_auto_pair_room(room):
            accepted_codes.update(auto_pair_competition_codes(room.competition_id))
        if provided_code not in accepted_codes:
            return jsonify({
                'success': False,
                'error': 'Enter the correct match room ID to join as a player'
            }), 403

    if is_auto_pair_room(room):
        target_room = find_or_create_auto_pair_room(room, user)
        if not target_room:
            return jsonify({'success': False, 'error': 'This competition is already full'}), 400
        room = target_room
        room_id = room.id

    if room.player1_id == user.id or room.player2_id == user.id:
        print(f"User {user.username} already in room")
        record_room_access(room, user, 'player')
        db.session.commit()
        return jsonify({'success': True, 'room_id': room_id, 'role': 'player'})

    if room.status != 'waiting':
        print(f"Room status is {room.status}, cannot join")
        return jsonify({'success': False, 'error': 'Room already started'}), 400
    
    if not room.player1_id:
        room.player1_id = user.id
        record_room_access(room, user, 'player')
        print(f"Assigned {user.username} as Player 1")
    elif not room.player2_id and room.player1_id != user.id:
        room.player2_id = user.id
        record_room_access(room, user, 'player')
        print(f"Assigned {user.username} as Player 2")
    else:
        print("Room is full")
        return jsonify({'success': False, 'error': 'Room is full'}), 400
    
    should_auto_start = False
    competition = None
    if room.player1_id and room.player2_id and is_auto_pair_room(room):
        competition = db.session.get(Competition, room.competition_id) if room.competition_id else None
        should_auto_start = bool(is_auto_pair_competition(competition) and competition.status == 'live')

    db.session.commit()
    
    emit_room_players(room, username=user.username)
    
    socketio.emit('chat_message', {
        'username': 'SYSTEM',
        'message': f'{user.username} joined as {"Player 1" if room.player1_id == user.id else "Player 2"}!',
        'is_system': True,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=str(room_id))

    if should_auto_start:
        start_room_match(room, started_by=room.started_by or (competition.created_by if competition else None))
        socketio.emit('system_announcement', {'message': 'Your partner joined. Match started automatically.'}, room=str(room.id))
    elif is_auto_pair_room(room) and not room.player2_id:
        socketio.emit('system_announcement', {'message': 'Waiting for a partner. The match starts automatically when the second player joins.'}, room=str(room.id))
    
    return jsonify({'success': True, 'room_id': room_id, 'role': 'player'})

@app.route('/room/spectate', methods=['POST'])
@login_required
def spectate_room_route():
    data = request.json or {}
    room_id = data.get('room_id')
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({'success': False, 'error': 'Room not found'}), 400
    user = get_current_user()
    access_response = room_access_redirect_or_error(room, user, 'spectator', json_response=True)
    if access_response:
        return access_response
    if room.status == 'ended':
        return jsonify({'success': False, 'error': 'This match has ended'}), 400
    record_room_access(room, user, 'spectator')
    db.session.commit()
    return jsonify({'success': True, 'room_id': room_id, 'role': 'spectator'})

@app.route('/room/list')
def room_list():
    ensure_schema_upgrades()
    rooms = Room.query.filter(Room.status != 'ended').all()
    return jsonify([
        {
            'id': r.id,
            'room_code': r.room_code if r.is_public else None,
            'is_public': bool(r.is_public),
            'status': r.status
        }
        for r in rooms
    ])

@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ========== PROFILE & API ROUTES ==========
@app.route('/leaderboard')
@login_required
def leaderboard():
    user = get_current_user()
    leaderboard_rows = build_leaderboard_rows()
    current_row = next((row for row in leaderboard_rows if row['user'].id == user.id), None)
    current_rank = next((index + 1 for index, row in enumerate(leaderboard_rows) if row['user'].id == user.id), None)
    award_card = build_leaderboard_award_card(user, current_row, current_rank) if current_row else None
    return render_template('leaderboard.html',
                           players=[row['user'] for row in leaderboard_rows],
                           leaderboard_rows=leaderboard_rows,
                           current_row=current_row,
                           award_card=award_card,
                           streak_target=LEADERBOARD_STREAK_TARGET,
                           user=user)

@app.route('/api/leaderboard')
def leaderboard_api():
    rows = build_leaderboard_rows()
    return jsonify([
        {
            'rank': index + 1,
            'id': row['user'].id,
            'username': row['user'].username,
            'matches_played': row['record']['matches_played'],
            'wins': row['record']['wins'],
            'losses': row['record']['losses'],
            'draws': row['record']['draws'],
            'win_rate': row['record']['win_rate'],
            'best_accuracy': row['record']['best_accuracy'],
            'avg_accuracy': row['record']['avg_accuracy'],
            'current_streak': row['record']['current_streak'],
            'best_streak': row['record']['best_streak'],
            'power_score': row['record']['power_score'],
        'leaderboard_unlocked': row['leaderboard_unlocked'],
            'unlock_reason': row['unlock_reason'],
            'award_reason': row['user'].leaderboard_award_reason,
            'award_details': row['user'].leaderboard_award_details,
            'award_color': row['user'].leaderboard_award_color
        }
        for index, row in enumerate(rows)
    ])

@app.route('/profile/<int:user_id>')
@login_required
def profile(user_id):
    target_user = db.session.get(User, user_id)
    current_user = get_current_user()
    
    if not target_user:
        return redirect(url_for('dashboard'))
    
    leaderboard_rows = build_leaderboard_rows()
    target_row = next((row for row in leaderboard_rows if row['user'].id == target_user.id), None)
    record = target_row['record'] if target_row else sync_user_competition_state(target_user)
    rank = next((i+1 for i, row in enumerate(leaderboard_rows) if row['user'].id == target_user.id), None)
    recent_matches = [event['submission'] for event in record['events'][:20] if event['submission']]
    award_card = build_leaderboard_award_card(target_user, target_row, rank) if target_row else None
    achievements = build_profile_achievements(target_user, record, rank, award_card)
    
    return render_template('profile.html',
                         target_user=target_user,
                         current_user=current_user,
                         user=current_user,
                         target_profile=get_profile_view_data(target_user.id),
                         recent_matches=recent_matches,
                         rank=rank,
                         leaderboard_record=record,
                         leaderboard_unlocked=user_has_leaderboard_access(target_user, record),
                         leaderboard_awarded=bool(target_user.leaderboard_awarded),
                         leaderboard_streak_target=LEADERBOARD_STREAK_TARGET,
                         achievements=achievements,
                         award_card=award_card)

@app.route('/profile/<int:user_id>/achievements')
@login_required
def profile_achievements(user_id):
    target_user = db.session.get(User, user_id)
    current_user = get_current_user()
    if not target_user:
        return redirect(url_for('dashboard'))
    leaderboard_rows = build_leaderboard_rows()
    target_row = next((row for row in leaderboard_rows if row['user'].id == target_user.id), None)
    record = target_row['record'] if target_row else sync_user_competition_state(target_user)
    rank = next((i + 1 for i, row in enumerate(leaderboard_rows) if row['user'].id == target_user.id), None)
    award_card = build_leaderboard_award_card(target_user, target_row, rank) if target_row else None
    achievements = build_profile_achievements(target_user, record, rank, award_card)
    return render_template('achievements.html',
                           user=current_user,
                           current_user=current_user,
                           target_user=target_user,
                           target_profile=get_profile_view_data(target_user.id),
                           leaderboard_record=record,
                           leaderboard_unlocked=user_has_leaderboard_access(target_user, record),
                           achievements=achievements,
                           award_card=award_card)

@app.route('/awards')
@login_required
def my_awards():
    current_user = get_current_user()
    cards = AwardCard.query.filter_by(user_id=current_user.id).order_by(AwardCard.created_at.desc()).all()
    return render_template(
        'student_awards.html',
        user=current_user,
        target_user=current_user,
        cards=[serialize_award_card(card) for card in cards],
        card_templates=CARD_TEMPLATES,
        avatar_templates=AVATAR_TEMPLATES,
        admin_mode=False
    )

@app.route('/awards/<int:card_id>/color', methods=['POST'])
@login_required
def update_award_card_color(card_id):
    current_user = get_current_user()
    card = db.session.get(AwardCard, card_id)
    if not card or card.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'Award card not found'}), 404
    data = request.get_json(silent=True) or {}
    card.student_color = clean_hex_color(data.get('color'), card.primary_color)
    db.session.commit()
    return jsonify({'success': True, 'card': serialize_award_card(card)})

@app.route('/api/profile/me', methods=['GET', 'POST'])
@login_required
def profile_me_api():
    user = get_current_user()
    if not user:
        return jsonify({'success': False, 'error': 'Not logged in'}), 401

    if request.method == 'GET':
        return jsonify({'success': True, 'user': profile_payload(user)})

    username = (request.form.get('username') or '').strip()
    email = valid_email(request.form.get('email'))
    bio = (request.form.get('bio') or '').strip()

    if not username:
        return jsonify({'success': False, 'error': 'Username is required'}), 400
    if email is None:
        return jsonify({'success': False, 'error': 'Enter a valid recovery email or leave it blank'}), 400

    existing = User.query.filter(User.username == username, User.id != user.id).first()
    if existing:
        return jsonify({'success': False, 'error': 'Username already exists'}), 400
    if email and User.query.filter(User.email == email, User.id != user.id).first():
        return jsonify({'success': False, 'error': 'Recovery email is already used by another account'}), 400

    username_changed = username != user.username
    email_changed = (email or None) != (user.email or None)
    if user.role == 'admin' and email_changed:
        current_password = request.form.get('current_password') or ''
        if not user.check_password(current_password):
            return jsonify({'success': False, 'error': 'Current password is required to change the admin email'}), 400
    user.username = username[:80]
    user.email = email or None
    profiles, profile = get_profile_record(user.id)
    profile['bio'] = bio[:500]
    if email_changed:
        profile['email_verified'] = False
        profile.pop('email_verification_hash', None)
        profile.pop('email_verification_expires_at', None)

    avatar = request.files.get('avatar')
    if avatar and avatar.filename:
        if not allowed_file(avatar.filename):
            return jsonify({'success': False, 'error': 'Avatar must be png, jpg, jpeg, or gif'}), 400
        ext = secure_filename(avatar.filename).rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        avatar.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        profile['avatar_filename'] = filename

    try:
        db.session.commit()
        save_profile_store(profiles)
    except (OSError, SQLAlchemyError):
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Profile storage is not writable. Restart the app from your VS Code terminal and try again.'}), 500
    session['username'] = user.username
    return jsonify({'success': True, 'user': profile_payload(user)})

@app.route('/api/account/password', methods=['POST'])
@login_required
def account_change_password():
    user = get_current_user()
    data = request.get_json() or {}
    current_password = data.get('current_password') or ''
    new_password = data.get('new_password') or ''
    confirm_password = data.get('confirm_password') or ''

    if not user.check_password(current_password):
        return jsonify({'success': False, 'error': 'Current password is incorrect'}), 400
    if not password_is_strong(new_password):
        return jsonify({'success': False, 'error': 'Use at least 12 characters with uppercase, lowercase, and a number'}), 400
    if new_password != confirm_password:
        return jsonify({'success': False, 'error': 'New passwords do not match'}), 400

    user.set_password(new_password)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/account/email/send-verification', methods=['POST'])
@login_required
def account_send_email_verification():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    requested_email = valid_email(data.get('email')) if data.get('email') is not None else (user.email or '')
    if requested_email is None:
        return jsonify({'success': False, 'error': 'Enter a valid recovery email'}), 400
    if not requested_email:
        return jsonify({'success': False, 'error': 'Add a recovery email first'}), 400
    if User.query.filter(User.email == requested_email, User.id != user.id).first():
        return jsonify({'success': False, 'error': 'Recovery email is already used by another account'}), 400
    if not email_configured():
        return jsonify({'success': False, 'error': smtp_configuration_error()}), 400

    email_changed = requested_email != (user.email or '')
    if user.role == 'admin' and email_changed:
        if not user.check_password(data.get('current_password') or ''):
            return jsonify({'success': False, 'error': 'Current password is required to change the admin email'}), 400
    if email_changed:
        user.email = requested_email
        profiles, profile = get_profile_record(user.id)
        profile['email_verified'] = False
        profile.pop('email_verification_hash', None)
        profile.pop('email_verification_expires_at', None)
        db.session.commit()
        save_profile_store(profiles)

    try:
        sent = send_email_verification(user)
    except Exception:
        app.logger.exception('Email verification send failed')
        sent = False
    if not sent:
        return jsonify({'success': False, 'error': 'Could not send verification email. Check SMTP settings and try again.'}), 500
    return jsonify({'success': True, 'message': 'Verification code sent', 'email': user.email})

@app.route('/api/account/email/verify', methods=['POST'])
@login_required
def account_verify_email():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    if verify_email_code(user, data.get('code')):
        return jsonify({'success': True, 'email_verified': True})
    return jsonify({'success': False, 'error': 'Invalid or expired verification code'}), 400

@app.route('/api/account/2fa/setup', methods=['POST'])
@login_required
def account_2fa_setup():
    user = get_current_user()
    data = request.get_json() or {}
    if not user.check_password(data.get('current_password') or ''):
        return jsonify({'success': False, 'error': 'Current password is required'}), 400
    if not user.two_factor_secret:
        user.two_factor_secret = generate_totp_secret()
        db.session.commit()
    otpauth_uri = totp_otpauth_uri(user, user.two_factor_secret)
    return jsonify({
        'success': True,
        'secret': user.two_factor_secret,
        'otpauth_uri': otpauth_uri,
        'qr_data_uri': qr_data_uri(otpauth_uri),
        'enabled': bool(user.two_factor_enabled)
    })

@app.route('/api/account/2fa/enable', methods=['POST'])
@login_required
def account_2fa_enable():
    user = get_current_user()
    data = request.get_json() or {}
    if not user.two_factor_secret:
        return jsonify({'success': False, 'error': 'Start two-step setup first'}), 400
    if not verify_totp(user.two_factor_secret, data.get('code')):
        return jsonify({'success': False, 'error': 'Invalid verification code'}), 400
    recovery_codes = []
    if not get_recovery_hashes(user):
        recovery_codes, recovery_hashes = generate_recovery_codes()
        user.two_factor_recovery_hashes = json.dumps(recovery_hashes)
    user.two_factor_enabled = True
    db.session.commit()
    return jsonify({'success': True, 'enabled': True, 'recovery_codes': recovery_codes})

@app.route('/api/account/2fa/disable', methods=['POST'])
@login_required
def account_2fa_disable():
    user = get_current_user()
    data = request.get_json() or {}
    if not user.check_password(data.get('current_password') or ''):
        return jsonify({'success': False, 'error': 'Current password is incorrect'}), 400
    if user.two_factor_enabled and not verify_totp(user.two_factor_secret, data.get('code')):
        return jsonify({'success': False, 'error': 'Invalid verification code'}), 400
    user.two_factor_enabled = False
    user.two_factor_secret = None
    user.two_factor_recovery_hashes = None
    db.session.commit()
    return jsonify({'success': True, 'enabled': False})

@app.route('/api/account/2fa/recovery-codes', methods=['POST'])
@login_required
def account_2fa_recovery_codes():
    user = get_current_user()
    data = request.get_json() or {}
    if not user.two_factor_enabled:
        return jsonify({'success': False, 'error': 'Enable two-step verification first'}), 400
    if not user.check_password(data.get('current_password') or ''):
        return jsonify({'success': False, 'error': 'Current password is incorrect'}), 400
    recovery_codes, recovery_hashes = generate_recovery_codes()
    user.two_factor_recovery_hashes = json.dumps(recovery_hashes)
    db.session.commit()
    return jsonify({'success': True, 'recovery_codes': recovery_codes})

@app.route('/api/user/<int:user_id>/matches/all')
@login_required
def get_user_all_matches(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    matches = []
    for event in get_user_match_events(user_id):
        s = event['submission']
        if not s:
            continue
        challenge = event['room'].challenge if event['room'] else s.challenge
        matches.append({
            'id': s.id,
            'date': event['completed_at'].strftime('%Y-%m-%d %H:%M') if event['completed_at'] else 'Unknown',
            'challenge': challenge.title if challenge else 'Unknown',
            'type': s.challenge.challenge_type.upper() if s.challenge else '-',
            'accuracy': round(s.accuracy, 1),
            'status': 'Forfeit' if s.is_forfeit else event['result'].title(),
            'result': event['result'],
            'is_winner': event['result'] == 'win'
        })
    
    return jsonify({'success': True, 'matches': matches})

@app.route('/api/match/<int:match_id>')
@login_required
def get_match_details(match_id):
    submission = db.session.get(Submission, match_id)
    if not submission:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    current_user = get_current_user()
    room = submission.room
    can_view = (
        current_user.role == 'admin'
        or submission.user_id == current_user.id
        or (room and current_user.id in {room.player1_id, room.player2_id})
    )
    if not can_view:
        return jsonify({'success': False, 'error': 'You can only view your own match code'}), 403
    
    return jsonify({
        'success': True,
        'challenge': submission.challenge.title if submission.challenge else 'Unknown',
        'accuracy': round(submission.accuracy, 1),
        'date': submission.submitted_at.strftime('%Y-%m-%d %H:%M') if submission.submitted_at else 'Unknown',
        'is_forfeit': submission.is_forfeit,
        'html_code': submission.html_code[:500] if submission.html_code else '',
        'css_code': submission.css_code[:500] if submission.css_code else '',
        'js_code': submission.js_code[:500] if submission.js_code else ''
    })

@app.route('/api/user/<int:user_id>/stats')
@login_required
def get_user_stats_api(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    record = sync_user_competition_state(user)
    db.session.commit()
    submissions = [event['submission'] for event in record['events'] if event['submission'] and not event['submission'].is_forfeit]

    image_count = sum(1 for s in submissions if s.challenge and s.challenge.challenge_type == 'image')
    html_count = sum(1 for s in submissions if s.challenge and s.challenge.challenge_type == 'html')
    
    return jsonify({
        'success': True,
        'username': user.username,
        'matches_played': record['matches_played'],
        'best_accuracy': record['best_accuracy'],
        'total_wins': record['wins'],
        'win_rate': record['win_rate'],
        'avg_accuracy': record['avg_accuracy'],
        'current_streak': record['current_streak'],
        'best_streak': record['best_streak'],
        'total_submissions': len(submissions),
        'image_count': image_count,
        'html_count': html_count,
        'total_score': round(sum(s.accuracy for s in submissions), 1),
        'power_score': record['power_score'],
        'leaderboard_unlocked': user_has_leaderboard_access(user, record),
        'leaderboard_awarded': bool(user.leaderboard_awarded),
        'leaderboard_unlock_target': LEADERBOARD_STREAK_TARGET
    })

# ========== SOCKET.IO EVENTS ==========
@socketio.on('connect')
def handle_connect():
    print(f"Ã¢Å“â€¦ Client connected: {request.sid}")
    user = socket_current_user()
    if user:
        join_room(f"user_{user.username}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Ã¢ÂÅ’ Client disconnected: {request.sid}")
    info = connected_users.pop(request.sid, None)
    if info:
        room_id = info.get('room_id')
        if room_id in room_spectators:
            room_spectators[room_id].discard(info.get('username'))
            if not room_spectators[room_id]:
                del room_spectators[room_id]
            emit_spectator_list(room_id)
        if room_id in room_typing_users:
            room_typing_users[room_id].discard(info.get('username'))
            room_typing_expiry.pop((room_id, info.get('username')), None)
        emit_presence(room_id)


def get_spectator_names(room_id):
    return sorted(list(room_spectators.get(room_id, set())))


def emit_spectator_list(room_id):
    socketio.emit('spectator_list_update', {
        'spectators': get_spectator_names(room_id),
        'count': len(room_spectators.get(room_id, set()))
    }, room=str(room_id))


def emit_typing_update(room_id):
    socketio.emit('typing_update', {
        'room_id': room_id,
        'users': sorted(room_typing_users.get(room_id, set()))
    }, room=str(room_id))


def expire_typing_user(room_id, username, expires_at):
    time.sleep(3)
    if room_typing_expiry.get((room_id, username)) != expires_at:
        return
    if room_id in room_typing_users:
        room_typing_users[room_id].discard(username)
        if not room_typing_users[room_id]:
            del room_typing_users[room_id]
    room_typing_expiry.pop((room_id, username), None)
    emit_typing_update(room_id)


def emit_presence(room_id):
    users_by_name = {}
    for info in connected_users.values():
        if info.get('room_id') == room_id and info.get('username'):
            users_by_name[info['username']] = {
                'username': info['username'],
                'role': info.get('role', 'spectator')
            }
    socketio.emit('presence_update', {
        'users': sorted(users_by_name.values(), key=lambda item: (item['role'], item['username'].lower()))
    }, room=str(room_id))



@socketio.on('join_room')
def handle_join_room(data):
    user, room, user_role = socket_room_context(data)
    if not user or not room:
        emit('auth_required', {'message': 'Sign in again before joining this room.'}, room=request.sid)
        return
    if room.status == 'ended' and user_role != 'admin':
        emit('room_join_denied', {'message': 'This match has ended.'}, room=request.sid)
        return
    if room_access_is_suspended(room, user):
        emit('room_join_denied', {'message': 'You were removed from this match by an admin.'}, room=request.sid)
        return

    room_id = room.id
    username = user.username
    connected_users[request.sid] = {'username': username, 'room_id': room_id, 'role': user_role, 'user_id': user.id}

    if user_role == 'spectator':
        room_spectators.setdefault(room_id, set()).add(username)
        emit_spectator_list(room_id)

    join_room(str(room_id))
    join_room(f"user_{username}")

    recent_messages = ChatMessage.query.filter_by(room_id=room_id).order_by(ChatMessage.sent_at.desc()).limit(50).all()
    emit('chat_history', {
        'messages': [serialize_chat_message(msg) for msg in reversed(recent_messages)]
    }, room=request.sid)

    if room.status == 'running':
        challenge = room.challenge
        emit('challenge_started', {
            'time_limit': challenge.time_limit,
            'challenge_title': challenge.title,
            'room_id': room.id
        }, room=request.sid)
    elif room.status == 'paused':
        emit('challenge_paused', {
            'room_id': room.id,
            'remaining': room_timers.get(room.id, 0),
            'message': 'Match is currently paused by admin'
        }, room=request.sid)

    if user_role in {'spectator', 'admin'}:
        emit('spectator_preview_state', {
            'previews': [
                {
                    'username': preview_username,
                    'compiled_html': preview_data.get('compiled_html', '') if isinstance(preview_data, dict) else preview_data,
                    'html_code': preview_data.get('html_code', '') if isinstance(preview_data, dict) else '',
                    'css_code': preview_data.get('css_code', '') if isinstance(preview_data, dict) else '',
                    'js_code': preview_data.get('js_code', '') if isinstance(preview_data, dict) else ''
                }
                for preview_username, preview_data in room_preview_data.get(room_id, {}).items()
            ]
        }, room=request.sid)

    scores = room_score_payload(room)
    emit('score_state', {'room_id': room_id, 'scores': scores}, room=request.sid)
    for score in scores:
        emit('progress_update', {
            'room_id': room_id,
            'username': score['username'],
            'accuracy': score['accuracy'],
            'score_details': score.get('score_details') or {}
        }, room=request.sid)

    emit_presence(room_id)
    socketio.emit('media_peer_ready', {
        'room_id': room_id,
        'username': username,
        'role': user_role,
        'has_audio': False,
        'has_video': False
    }, room=str(room_id), include_self=False)
    socketio.emit('chat_message', {
        'username': 'SYSTEM',
        'message': f'{username} joined the arena as {user_role.replace("player1", "Player 1").replace("player2", "Player 2").replace("spectator", "Spectator").replace("admin", "Admin")}!',
        'is_system': True,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=str(room_id))

@socketio.on('join_tournament')
def handle_join_tournament(data):
    tournament_id = data.get('tournament_id')
    user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    if not tournament_id or not user:
        return
    join_room(f"tournament_{int(tournament_id)}")
    join_room(f"user_{user.username}")
    emit('tournament_notification', {'message': 'Connected to live tournament updates.'}, room=request.sid)



@socketio.on('leave_room')
def handle_leave_room(data):
    info = connected_users.pop(request.sid, {})
    try:
        room_id = int((data or {}).get('room_id') or info.get('room_id'))
    except (TypeError, ValueError):
        return
    username = info.get('username') or (socket_current_user().username if socket_current_user() else None)

    leave_room(str(room_id))

    if room_id in room_spectators and username in room_spectators[room_id]:
        room_spectators[room_id].discard(username)
        if not room_spectators[room_id]:
            del room_spectators[room_id]
        emit_spectator_list(room_id)
    if room_id in room_typing_users and username:
        room_typing_users[room_id].discard(username)
        room_typing_expiry.pop((room_id, username), None)
        emit_typing_update(room_id)
    emit_presence(room_id)

    if username:
        socketio.emit('chat_message', {
            'username': 'SYSTEM',
            'message': f'{username} left the arena.',
            'is_system': True,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, room=str(room_id))


@socketio.on('progress_update')
def handle_progress_update(data):
    user, room, _role = socket_room_context(data)
    if not is_room_player(user, room):
        return
    sub = get_best_room_submission(room.id, user.id)
    accuracy, details = submission_score_analysis(sub, room.challenge) if sub else (0.0, {})

    socketio.emit('progress_update', {
        'room_id': room.id,
        'username': user.username,
        'accuracy': accuracy,
        'score_details': details
    }, room=str(room.id), include_self=False)

    broadcast_leaderboard(room.id)


@socketio.on('chat_message')
def handle_chat_message(data):
    user, room, _role = socket_room_context(data)
    if not user or not room:
        emit('chat_warning', {
            'message': 'Join the room before sending chat messages.'
        }, room=request.sid)
        return

    room_id = room.id
    username = user.username
    message = ((data or {}).get('message') or '').strip()
    if not message:
        return
    message = message[:500]

    if contains_bad_language(message):
        if room_id in room_typing_users:
            room_typing_users[room_id].discard(username)
            room_typing_expiry.pop((room_id, username), None)
        emit('chat_warning', {
            'message': 'Please keep the arena chat respectful. Your message was not sent.'
        }, room=request.sid)
        emit_typing_update(room_id)
        return

    auto_flagged = contains_sensitive_language(message)
    chat_msg = ChatMessage(
        room_id=room_id,
        user_id=user.id,
        message=message,
        is_system=False,
        is_flagged=auto_flagged,
        flag_reason='Auto-flagged for sensitive language' if auto_flagged else None
    )
    db.session.add(chat_msg)
    db.session.commit()

    socketio.emit('chat_message', serialize_chat_message(chat_msg), room=str(room_id))
    socketio.emit('admin_chat_message', serialize_admin_chat_message(chat_msg))
    if auto_flagged:
        emit('chat_warning', {
            'message': 'Your message was sent but flagged for admin review because it contains sensitive language.'
        }, room=request.sid)
        socketio.emit('chat_flag_notice', {
            'message_id': chat_msg.id,
            'message': f'Message from {user.username} was auto-flagged for admin review.'
        }, room=str(room_id))
    if room_id in room_typing_users:
        room_typing_users[room_id].discard(username)
        room_typing_expiry.pop((room_id, username), None)
    emit_typing_update(room_id)

@socketio.on('flag_chat_message')
def handle_flag_chat_message(data):
    session_user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    if not session_user or session_user.role != 'admin':
        emit('chat_warning', {'message': 'Only admins can flag chat messages.'}, room=request.sid)
        return

    try:
        message_id = int(data.get('message_id'))
    except (TypeError, ValueError):
        return

    chat_msg = db.session.get(ChatMessage, message_id)
    if not chat_msg or chat_msg.is_system:
        return

    reason = (data.get('reason') or 'Flagged by admin').strip()[:160]
    chat_msg.is_flagged = True
    chat_msg.flag_reason = reason
    chat_msg.flagged_by = session_user.id
    db.session.commit()

    payload = {
        'id': chat_msg.id,
        'is_flagged': True,
        'flag_reason': reason
    }
    socketio.emit('chat_message_flagged', payload, room=str(chat_msg.room_id))
    socketio.emit('admin_chat_message_flagged', {
        'id': chat_msg.id,
        'flag_reason': reason
    })
    socketio.emit('chat_flag_notice', {
        'message_id': chat_msg.id,
        'message': f'Admin flagged a chat message from {chat_msg.user.username if chat_msg.user else "a user"}.'
    }, room=str(chat_msg.room_id))



@socketio.on('typing')
def handle_typing(data):
    user, room, _role = socket_room_context(data)
    if not user or not room:
        return
    is_typing = bool((data or {}).get('is_typing'))
    if is_typing:
        room_typing_users.setdefault(room.id, set()).add(user.username)
        expires_at = time.time() + 3
        room_typing_expiry[(room.id, user.username)] = expires_at
        socketio.start_background_task(expire_typing_user, room.id, user.username, expires_at)
    elif room.id in room_typing_users:
        room_typing_users[room.id].discard(user.username)
        room_typing_expiry.pop((room.id, user.username), None)
    emit_typing_update(room.id)


@socketio.on('cam_frame')
def handle_cam_frame(data):
    user, room, _role = socket_room_context(data)
    if not is_room_player(user, room):
        return
    frame_data = (data or {}).get('frame_data')

    socketio.emit('cam_frame', {
        'room_id': room.id,
        'username': user.username,
        'frame_data': frame_data
    }, room=str(room.id), include_self=False)


def can_publish_room_media(user, room, role):
    return bool(user and room and (role == 'admin' or is_room_player(user, room)))


@socketio.on('media_ready')
def handle_media_ready(data):
    user, room, role = socket_room_context(data)
    if not can_publish_room_media(user, room, role):
        return

    socketio.emit('media_peer_ready', {
        'room_id': room.id,
        'username': user.username,
        'role': role,
        'has_audio': bool((data or {}).get('has_audio')),
        'has_video': bool((data or {}).get('has_video'))
    }, room=str(room.id), include_self=False)


@socketio.on('media_offer')
def handle_media_offer(data):
    user, room, role = socket_room_context(data)
    if not can_publish_room_media(user, room, role):
        return
    target = str((data or {}).get('to') or '').strip()
    offer = (data or {}).get('offer')
    if not target or not offer:
        return

    socketio.emit('media_offer', {
        'room_id': room.id,
        'from': user.username,
        'role': role,
        'offer': offer
    }, room=f"user_{target}")


@socketio.on('media_answer')
def handle_media_answer(data):
    user, room, role = socket_room_context(data)
    if not can_publish_room_media(user, room, role):
        return
    target = str((data or {}).get('to') or '').strip()
    answer = (data or {}).get('answer')
    if not target or not answer:
        return

    socketio.emit('media_answer', {
        'room_id': room.id,
        'from': user.username,
        'role': role,
        'answer': answer
    }, room=f"user_{target}")


@socketio.on('media_ice_candidate')
def handle_media_ice_candidate(data):
    user, room, role = socket_room_context(data)
    if not can_publish_room_media(user, room, role):
        return
    target = str((data or {}).get('to') or '').strip()
    candidate = (data or {}).get('candidate')
    if not target or not candidate:
        return

    socketio.emit('media_ice_candidate', {
        'room_id': room.id,
        'from': user.username,
        'role': role,
        'candidate': candidate
    }, room=f"user_{target}")


@socketio.on('media_leave')
def handle_media_leave(data):
    user, room, role = socket_room_context(data)
    if not can_publish_room_media(user, room, role):
        return

    socketio.emit('media_peer_left', {
        'room_id': room.id,
        'username': user.username,
        'role': role
    }, room=str(room.id), include_self=False)


@socketio.on('voice_broadcast_start')
def handle_voice_broadcast_start(data):
    user, room, role = socket_room_context(data)
    if not user or not room or role != 'admin':
        return

    socketio.emit('voice_broadcast_start', {
        'room_id': room.id,
        'username': user.username
    }, room=str(room.id), include_self=False)


@socketio.on('voice_broadcast_chunk')
def handle_voice_broadcast_chunk(data):
    user, room, role = socket_room_context(data)
    if not user or not room or role != 'admin':
        return
    chunk = str((data or {}).get('chunk') or '')
    if not chunk.startswith('data:audio/') or len(chunk) > 250000:
        return

    socketio.emit('voice_broadcast_chunk', {
        'room_id': room.id,
        'username': user.username,
        'chunk': chunk
    }, room=str(room.id), include_self=False)


@socketio.on('voice_broadcast_end')
def handle_voice_broadcast_end(data):
    user, room, role = socket_room_context(data)
    if not user or not room or role != 'admin':
        return

    socketio.emit('voice_broadcast_end', {
        'room_id': room.id,
        'username': user.username
    }, room=str(room.id), include_self=False)


@socketio.on('code_preview')
def handle_code_preview(data):
    user, room, _role = socket_room_context(data)
    if not is_room_player(user, room):
        return
    compiled_html = (data or {}).get('compiled_html')

    room_preview_data.setdefault(room.id, {})[user.username] = {
        'compiled_html': compiled_html,
        'html_code': str((data or {}).get('html_code') or '')[:50000],
        'css_code': str((data or {}).get('css_code') or '')[:50000],
        'js_code': str((data or {}).get('js_code') or '')[:50000]
    }

    socketio.emit('admin_preview', {
        'room_id': room.id,
        'username': user.username,
        'compiled_html': compiled_html,
        'html_code': str((data or {}).get('html_code') or '')[:50000],
        'css_code': str((data or {}).get('css_code') or '')[:50000],
        'js_code': str((data or {}).get('js_code') or '')[:50000]
    }, room=str(room.id))

@socketio.on('admin_watch_room')
def handle_admin_watch_room(data):
    session_user = db.session.get(User, session.get('user_id')) if session.get('user_id') else None
    if not session_user or session_user.role != 'admin':
        return
    try:
        room_id = int(data.get('room_id'))
    except (TypeError, ValueError):
        return
    room = db.session.get(Room, room_id)
    if not room:
        return
    join_room(str(room_id))
    connected_users[request.sid] = {'username': session_user.username, 'room_id': room_id, 'role': 'admin', 'user_id': session_user.id}
    emit('admin_watch_ready', {
        'room_id': room_id,
        'player1': room.player1.username if room.player1 else '',
        'player2': room.player2.username if room.player2 else '',
        'status': room.status,
        'previews': [
            {
                'username': preview_username,
                'compiled_html': preview_data.get('compiled_html', '') if isinstance(preview_data, dict) else preview_data,
                'html_code': preview_data.get('html_code', '') if isinstance(preview_data, dict) else '',
                'css_code': preview_data.get('css_code', '') if isinstance(preview_data, dict) else '',
                'js_code': preview_data.get('js_code', '') if isinstance(preview_data, dict) else ''
            }
            for preview_username, preview_data in room_preview_data.get(room_id, {}).items()
        ]
    }, room=request.sid)


@socketio.on('forfeit')
def handle_forfeit(data):
    user, room, _role = socket_room_context(data)
    if not is_room_player(user, room):
        return

    submission = Submission(
        user_id=user.id,
        room_id=room.id,
        challenge_id=room.challenge_id,
        is_forfeit=True,
        accuracy=0
    )
    db.session.add(submission)
    db.session.commit()

    socketio.emit('player_forfeit', {'username': user.username}, room=str(room.id))


@socketio.on('right_click_attempt')
def handle_right_click_attempt(data):
    user, room, role = socket_room_context(data)
    if not is_room_player(user, room):
        return
    source = str((data or {}).get('source') or 'arena').strip()[:40]
    payload = {
        'room_id': room.id,
        'username': user.username,
        'player_name': user.username,
        'role': role,
        'source': source,
        'blocked': True,
        'worked': False,
        'message': f'Player {user.username} tried to right-click in {source}. The attempt was blocked.'
    }
    if room.competition_id:
        db.session.add(DisputeCase(
            competition_id=room.competition_id,
            wave_id=room.wave_id,
            room_id=room.id,
            player_id=user.id,
            type='fair_play_warning',
            status='open',
            priority='high' if source in {'inspect', 'view-source'} else 'normal',
            reason=payload['message'],
            created_by=user.id
        ))
        db.session.commit()
    socketio.emit('admin_right_click_attempt', payload, room=str(room.id))


@socketio.on('admin_warn_player')
def handle_admin_warn_player(data):
    admin, room, role = socket_room_context(data)
    if not admin or admin.role != 'admin' or role != 'admin' or not room:
        return
    target = str((data or {}).get('username') or '').strip()[:80]
    message = str((data or {}).get('message') or '').strip()[:500]
    if not target or not message:
        return
    socketio.emit('admin_player_warning', {
        'room_id': room.id,
        'username': target,
        'message': message,
        'admin': admin.username
    }, room=f"user_{target}")
    socketio.emit('chat_message', {
        'username': 'SYSTEM',
        'message': f'Admin warned {target}: {message}',
        'is_system': True,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=str(room.id))
    emit('admin_right_click_action_result', {
        'success': True,
        'message': f'Warning sent to {target}.'
    }, room=request.sid)


@socketio.on('admin_disqualify_player')
def handle_admin_disqualify_player(data):
    admin, room, role = socket_room_context(data)
    if not admin or admin.role != 'admin' or role != 'admin' or not room:
        return
    target = str((data or {}).get('username') or '').strip()[:80]
    reason = str((data or {}).get('reason') or 'Right-click attempt during arena match.').strip()[:500]
    player = None
    if room.player1 and room.player1.username == target:
        player = room.player1
    elif room.player2 and room.player2.username == target:
        player = room.player2
    if not player:
        emit('admin_right_click_action_result', {
            'success': False,
            'message': f'{target or "Player"} is not an active player in this room.'
        }, room=request.sid)
        return

    submission = Submission(
        user_id=player.id,
        room_id=room.id,
        challenge_id=room.challenge_id,
        is_forfeit=True,
        accuracy=0,
        score_details=json.dumps({
            'scoring_mode': 'disqualified',
            'reason': reason,
            'admin': admin.username
        })
    )
    db.session.add(submission)
    record_room_access(room, player, 'player', status='suspended', granted_by=admin.id, reason=reason)
    if room.competition_id:
        db.session.add(DisputeCase(
            competition_id=room.competition_id,
            wave_id=room.wave_id,
            room_id=room.id,
            player_id=player.id,
            type='disqualification',
            status='disqualified',
            priority='high',
            reason=reason,
            created_by=admin.id,
            resolved_by=admin.id,
            resolved_at=datetime.now(timezone.utc)
        ))
    db.session.commit()
    socketio.emit('kicked', {
        'message': f'You were disqualified by admin. Reason: {reason}'
    }, room=f"user_{target}")
    socketio.emit('player_disqualified', {
        'username': target,
        'reason': reason,
        'admin': admin.username
    }, room=str(room.id))
    socketio.emit('chat_message', {
        'username': 'SYSTEM',
        'message': f'{target} was disqualified. Reason: {reason}',
        'is_system': True,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=str(room.id))
    broadcast_leaderboard(room.id)
    emit('admin_right_click_action_result', {
        'success': True,
        'message': f'{target} was disqualified.'
    }, room=request.sid)


@socketio.on('start_challenge')
def on_start(data):
    admin = socket_current_user()
    if not admin or admin.role != 'admin':
        return

    try:
        room_id = int((data or {}).get('room_id'))
    except (TypeError, ValueError):
        return
    room = db.session.get(Room, room_id)
    if not room or room.status not in ['waiting', 'paused']:
        return

    challenge = room.challenge
    room.status = 'running'
    room.started_by = admin.id
    db.session.commit()

    if room.id not in room_timers or room_timers.get(room.id, 0) <= 0:
        room_timers[room.id] = challenge.time_limit

    socketio.emit('challenge_started', {
        'time_limit': challenge.time_limit,
        'challenge_title': challenge.title,
        'room_id': room.id
    }, room=str(room.id))

    thread = threading.Thread(target=run_room_timer, args=(room.id,))
    thread.daemon = True
    thread.start()

@socketio.on('pause_challenge')
def on_pause(data):
    admin = socket_current_user()
    if not admin or admin.role != 'admin':
        return
    try:
        room_id = int((data or {}).get('room_id'))
    except (TypeError, ValueError):
        return
    room = db.session.get(Room, room_id)
    if room and room.status == 'running':
        room.status = 'paused'
        db.session.commit()
        emit_challenge_paused(room)

@socketio.on('resume_challenge')
def on_resume(data):
    admin = socket_current_user()
    if not admin or admin.role != 'admin':
        return
    try:
        room_id = int((data or {}).get('room_id'))
    except (TypeError, ValueError):
        return
    room = db.session.get(Room, room_id)
    if room and room.status == 'paused':
        room.status = 'running'
        db.session.commit()
        emit_challenge_resumed(room)

@socketio.on('add_time')
def on_add_time(data):
    admin = socket_current_user()
    if not admin or admin.role != 'admin':
        return
    try:
        rid = int((data or {}).get('room_id'))
        seconds = max(1, min(600, int((data or {}).get('seconds', 30))))
    except (TypeError, ValueError):
        return
    room_timers[rid] = room_timers.get(rid, 0) + seconds
    socketio.emit('timer_tick', {'remaining': room_timers[rid]}, room=str(rid))

@socketio.on('end_challenge')
def on_end(data):
    admin = socket_current_user()
    if not admin or admin.role != 'admin':
        return
    try:
        rid = int((data or {}).get('room_id'))
    except (TypeError, ValueError):
        return
    room_timers[rid] = 0
    room = db.session.get(Room, rid)
    if room:
        room.status = 'ended'
        room.ended_at = datetime.now(timezone.utc)
        finalize_room_results(room)
        db.session.commit()
    socketio.emit('challenge_ended', {'room_id': rid}, room=str(rid))

@socketio.on('broadcast_message')
def on_broadcast(data):
    admin = socket_current_user()
    if not admin or admin.role != 'admin':
        return
    message = str((data or {}).get('message') or '').strip()[:500]
    if not message:
        return
    room_id = (data or {}).get('room_id')
    if room_id:
        socketio.emit('system_announcement', {'message': message}, room=str(room_id))
    else:
        for room in Room.query.all():
            socketio.emit('system_announcement', {'message': message}, room=str(room.id))

@socketio.on('kick_player')
def on_kick(data):
    admin = socket_current_user()
    if not admin or admin.role != 'admin':
        return
    target = str((data or {}).get('username') or '').strip()[:80]
    if target:
        socketio.emit('kicked', {'message': 'You were removed by the admin.'}, room=f"user_{target}")

@socketio.on('check_challenge_status')
def handle_check_status(data):
    user, room, _role = socket_room_context(data)
    if not user or not room:
        return
    if room.status == 'running':
        challenge = room.challenge
        emit('challenge_started', {
            'time_limit': challenge.time_limit,
            'challenge_title': challenge.title,
            'room_id': room.id
        })


# ========== DEBUG ROUTES ==========
@app.route('/debug/room/<int:room_id>')
@admin_required
def debug_room(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    
    return jsonify({
        'room_id': room.id,
        'room_code': room.room_code,
        'status': room.status,
        'player1': room.player1.username if room.player1 else None,
        'player2': room.player2.username if room.player2 else None,
        'connected_clients': list(connected_users.values())
    })

# Add this endpoint to check challenge status via HTTP (more reliable than WebSocket)
@app.route('/api/challenge-status/<int:room_id>')
@login_required
def api_challenge_status(room_id):
    room = db.session.get(Room, room_id)
    if room and room.status == 'running':
        return jsonify({
            'status': 'running',
            'time_limit': room.challenge.time_limit,
            'challenge_title': room.challenge.title
        })
    return jsonify({'status': room.status if room else 'unknown'})


# ========== MAIN ==========
def initialize_runtime_database(create_dev_admin=False):
    with app.app_context():
        db.create_all()
        ensure_schema_upgrades()
        refresh_builtin_site_content()

        admin = User.query.filter_by(role='admin').first()
        admin_email = configured_admin_email()
        admin_password = os.environ.get('ADMIN_PASSWORD')

        if admin and admin_email and admin.email != admin_email:
            admin.email = admin_email
            db.session.commit()
            print(f"Admin email set to {admin_email}")

        if not admin and admin_email and admin_password:
            admin = User(username='admin', email=admin_email, role='admin')
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print("=" * 50)
            print("Admin created successfully!")
            print(f"Email: {admin_email}")
            print("Password: from ADMIN_PASSWORD")
            print("=" * 50)
        elif create_dev_admin:
            if admin:
                print(f"Admin user already exists. Login email: {admin.email or 'not set'}")
            else:
                print("No admin user exists. Set ADMIN_EMAIL and ADMIN_PASSWORD before starting the app to create one.")

initialize_runtime_database(create_dev_admin=False)

# ========== MAIN ==========
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
