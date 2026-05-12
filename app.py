from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
import os
import uuid
import secrets
from functools import wraps
from werkzeug.utils import secure_filename
from PIL import Image
import threading

# IMPORTANT: Must import eventlet and monkey patch BEFORE anything else
import eventlet
eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

from models import db, User, Challenge, Room, Submission, ChatMessage
from auth import login_required, admin_required, get_current_user

db.init_app(app)

# Use eventlet for async - this is critical for WebSocket to work
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

room_timers = {}
room_preview_data = {}
connected_users = {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_room_code():
    import random
    import string
    return '#' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

def update_user_stats(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return
    submissions = Submission.query.filter_by(user_id=user_id, is_forfeit=False).all()
    user.matches_played = len(submissions)
    if submissions:
        best = max(s.accuracy for s in submissions)
        user.best_accuracy = max(user.best_accuracy, best)
    db.session.commit()

def run_room_timer(room_id):
    with app.app_context():
        while room_timers.get(room_id, 0) > 0:
            room = db.session.get(Room, room_id)
            if not room or room.status == 'ended':
                break
            if room.status == 'paused':
                eventlet.sleep(1)
                continue
            socketio.emit('timer_tick', {'remaining': room_timers[room_id]}, room=str(room_id))
            eventlet.sleep(1)
            if room_timers.get(room_id, 0) > 0:
                room_timers[room_id] -= 1
        with app.app_context():
            room = db.session.get(Room, room_id)
            if room and room.status == 'running':
                room.status = 'ended'
                room.ended_at = datetime.now(timezone.utc)
                db.session.commit()
                final_submissions = Submission.query.filter_by(room_id=room_id).all()
                for sub in final_submissions:
                    sub.is_final = True
                db.session.commit()
        socketio.emit('challenge_ended', {'room_id': room_id}, room=str(room_id))

def broadcast_leaderboard(room_id):
    submissions = Submission.query.filter_by(room_id=room_id, is_final=False).all()
    submission_dict = {}
    for sub in submissions:
        if sub.user:
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
    return render_template('login.html')

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role
        return jsonify({'success': True, 'role': user.role})
    return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

@app.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'player')
    
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Username already exists'}), 400
    
    user = User(username=username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    session['user_id'] = user.id
    session['username'] = user.username
    session['role'] = user.role
    return jsonify({'success': True, 'role': user.role})

@app.route('/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# ========== DASHBOARD ==========
@app.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user()
    rooms = Room.query.filter(Room.status != 'ended').order_by(Room.created_at.desc()).all()
    top_players = User.query.filter_by(role='player').order_by(User.best_accuracy.desc()).limit(10).all()
    recent_matches = Submission.query.filter_by(user_id=user.id).order_by(Submission.submitted_at.desc()).limit(5).all()
    
    room_data = []
    for room in rooms:
        challenge = room.challenge
        room_data.append({
            'id': room.id,
            'room_code': room.room_code,
            'challenge_title': challenge.title if challenge else 'Unknown',
            'challenge_type': challenge.challenge_type if challenge else 'image',
            'difficulty': challenge.difficulty if challenge else 'Medium',
            'status': room.status,
            'player1': room.player1.username if room.player1 else 'Open',
            'player2': room.player2.username if room.player2 else 'Open'
        })
    
    all_players = User.query.filter_by(role='player').order_by(User.best_accuracy.desc()).all()
    rank = next((i+1 for i, p in enumerate(all_players) if p.id == user.id), None)
    
    return render_template('dashboard.html', 
                         user=user, 
                         rooms=room_data,
                         top_players=top_players,
                         recent_matches=recent_matches,
                         active_rooms_count=len(rooms),
                         total_challenges=Challenge.query.filter_by(is_active=True).count(),
                         total_players=User.query.filter_by(role='player').count(),
                         global_rank=rank)

# ========== ADMIN ROUTES ==========
@app.route('/admin')
@admin_required
def admin_panel():
    user = get_current_user()
    rooms = Room.query.order_by(Room.created_at.desc()).all()
    challenges = Challenge.query.filter_by(is_active=True).all()
    all_challenges = Challenge.query.all()
    players = User.query.filter_by(role='player').all()
    
    return render_template('admin.html', 
                         user=user, 
                         rooms=rooms, 
                         challenges=challenges,
                         all_challenges=all_challenges,
                         players=players)

@app.route('/admin/create_challenge', methods=['POST'])
@admin_required
def create_challenge():
    challenge_type = request.form.get('challenge_type', 'image')
    title = request.form.get('title')
    difficulty = request.form.get('difficulty')
    time_limit = int(request.form.get('time_limit', 120))
    description = request.form.get('description', '')
    
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
        target_html = request.form.get('target_html', '')
        target_css = request.form.get('target_css', '')
        html_locked = request.form.get('html_locked') == 'true'
        
        new_challenge.target_html = target_html
        new_challenge.target_css = target_css
        new_challenge.html_locked = html_locked
    
    db.session.add(new_challenge)
    db.session.commit()
    
    room_code = generate_room_code()
    new_room = Room(
        room_code=room_code,
        challenge_id=new_challenge.id,
        status='waiting'
    )
    db.session.add(new_room)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'room_code': room_code,
        'room_id': new_room.id,
        'challenge_type': challenge_type
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
            room.status = 'running'
            room.started_by = session['user_id']
            db.session.commit()
            challenge = room.challenge
            if room.id not in room_timers or room_timers.get(room.id, 0) <= 0:
                room_timers[room.id] = challenge.time_limit
            socketio.emit('challenge_started', {
                'time_limit': challenge.time_limit,
                'challenge_title': challenge.title,
                'room_id': room.id
            }, room=str(room_id))
            thread = threading.Thread(target=run_room_timer, args=(room_id,))
            thread.daemon = True
            thread.start()
    elif action == 'pause':
        if room.status == 'running':
            room.status = 'paused'
            db.session.commit()
            socketio.emit('challenge_paused', {'remaining': room_timers.get(room_id, 0)}, room=str(room_id))
    elif action == 'resume':
        if room.status == 'paused':
            room.status = 'running'
            db.session.commit()
            socketio.emit('challenge_resumed', {}, room=str(room_id))
    elif action == 'end':
        room.status = 'ended'
        room.ended_at = datetime.now(timezone.utc)
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
    
    return jsonify({'success': True})

@app.route('/admin/kick', methods=['POST'])
@admin_required
def kick_player():
    data = request.json
    username = data.get('username')
    room_id = data.get('room_id')
    
    room = db.session.get(Room, room_id)
    if room:
        if room.player1 and room.player1.username == username:
            room.player1_id = None
        elif room.player2 and room.player2.username == username:
            room.player2_id = None
        db.session.commit()
    
    socketio.emit('kicked', {'message': 'You were kicked by the admin'}, room=f"user_{username}")
    return jsonify({'success': True})

# ========== CHALLENGE MANAGEMENT ROUTES ==========
@app.route('/admin/challenge/<int:challenge_id>/delete', methods=['DELETE'])
@admin_required
def delete_challenge(challenge_id):
    challenge = db.session.get(Challenge, challenge_id)
    if not challenge:
        return jsonify({'success': False, 'error': 'Challenge not found'}), 404
    
    challenge.is_active = False
    db.session.commit()
    return jsonify({'success': True})

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
    
    if user.role == 'admin':
        return jsonify({'success': False, 'error': 'Cannot delete admin users'}), 400
    
    Submission.query.filter_by(user_id=user_id).delete()
    ChatMessage.query.filter_by(user_id=user_id).delete()
    Room.query.filter_by(player1_id=user_id).update({Room.player1_id: None})
    Room.query.filter_by(player2_id=user_id).update({Room.player2_id: None})
    db.session.delete(user)
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

@app.route('/admin/user/<int:user_id>/reset-stats', methods=['POST'])
@admin_required
def reset_player_stats(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    user.matches_played = 0
    user.best_accuracy = 0
    user.total_wins = 0
    Submission.query.filter_by(user_id=user_id, is_final=False).delete()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/room/<int:room_id>/delete', methods=['DELETE'])
@admin_required
def delete_room(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({'success': False, 'error': 'Room not found'}), 404
    
    Submission.query.filter_by(room_id=room_id).delete()
    ChatMessage.query.filter_by(room_id=room_id).delete()
    db.session.delete(room)
    db.session.commit()
    
    if room_id in room_timers:
        del room_timers[room_id]
    
    return jsonify({'success': True})

# ========== ARENA & GAMEPLAY ROUTES ==========
@app.route('/arena/<int:room_id>')
@login_required
def arena(room_id):
    user = get_current_user()
    room = db.session.get(Room, room_id)
    
    if not room:
        return redirect(url_for('dashboard'))
    
    challenge = room.challenge
    player1_username = room.player1.username if room.player1 else None
    player2_username = room.player2.username if room.player2 else None
    admin_user = User.query.filter_by(role='admin').first()
    
    user_role = 'spectator'
    if room.player1_id == user.id:
        user_role = 'player1'
    elif room.player2_id == user.id:
        user_role = 'player2'
    elif user.role == 'admin':
        user_role = 'admin'
    
    return render_template('arena.html',
                         room=room,
                         challenge=challenge,
                         user=user,
                         user_role=user_role,
                         player1_username=player1_username,
                         player2_username=player2_username,
                         admin_username=admin_user.username if admin_user else 'Admin')

@app.route('/results/<int:room_id>')
@login_required
def results(room_id):
    user = get_current_user()
    room = db.session.get(Room, room_id)
    
    if not room:
        return redirect(url_for('dashboard'))
    
    final_subs = Submission.query.filter_by(room_id=room_id, is_final=True).all()
    
    p1_sub = None
    p2_sub = None
    
    if not final_subs:
        final_subs = Submission.query.filter_by(room_id=room_id).all()
    
    for sub in final_subs:
        if sub.user_id == room.player1_id:
            p1_sub = sub
        elif sub.user_id == room.player2_id:
            p2_sub = sub
    
    winner = None
    if p1_sub and p2_sub:
        if p1_sub.accuracy > p2_sub.accuracy:
            winner = p1_sub.user.username if p1_sub.user else 'Player 1'
        elif p2_sub.accuracy > p1_sub.accuracy:
            winner = p2_sub.user.username if p2_sub.user else 'Player 2'
        else:
            winner = 'DRAW'
    
    if room.player1_id:
        update_user_stats(room.player1_id)
    if room.player2_id:
        update_user_stats(room.player2_id)
    
    return render_template('results.html',
                         room=room,
                         p1_sub=p1_sub,
                         p2_sub=p2_sub,
                         winner=winner,
                         user=user)

@app.route('/submission/save', methods=['POST'])
@login_required
def save_submission():
    data = request.json
    user = get_current_user()
    
    existing = Submission.query.filter_by(
        user_id=user.id,
        room_id=data['room_id'],
        is_final=False
    ).first()
    
    if existing:
        existing.html_code = data.get('html_code', '')
        existing.css_code = data.get('css_code', '')
        existing.js_code = data.get('js_code', '')
        existing.accuracy = data['accuracy']
        existing.submitted_at = datetime.now(timezone.utc)
    else:
        submission = Submission(
            user_id=user.id,
            room_id=data['room_id'],
            challenge_id=data.get('challenge_id'),
            html_code=data.get('html_code', ''),
            css_code=data.get('css_code', ''),
            js_code=data.get('js_code', ''),
            accuracy=data['accuracy']
        )
        db.session.add(submission)
    
    db.session.commit()
    broadcast_leaderboard(data['room_id'])
    
    return jsonify({'success': True})

@app.route('/room/join', methods=['POST'])
@login_required
def join_room_route():
    data = request.json
    room_id = data.get('room_id')
    user = get_current_user()
    
    print(f"🔵 Join room request: room_id={room_id}, user={user.username if user else 'None'}")
    
    room = db.session.get(Room, room_id)
    
    if not room:
        print(f"❌ Room {room_id} not found")
        return jsonify({'success': False, 'error': 'Room not found'}), 400
    
    print(f"Room status: {room.status}, Player1: {room.player1_id}, Player2: {room.player2_id}")
    
    if room.status != 'waiting':
        print(f"❌ Room status is {room.status}, cannot join")
        return jsonify({'success': False, 'error': 'Room already started'}), 400
    
    if room.player1_id == user.id or room.player2_id == user.id:
        print(f"✅ User {user.username} already in room")
        return jsonify({'success': True, 'room_id': room_id})
    
    if not room.player1_id:
        room.player1_id = user.id
        print(f"✅ Assigned {user.username} as Player 1")
    elif not room.player2_id and room.player1_id != user.id:
        room.player2_id = user.id
        print(f"✅ Assigned {user.username} as Player 2")
    else:
        print(f"❌ Room is full")
        return jsonify({'success': False, 'error': 'Room is full'}), 400
    
    db.session.commit()
    
    socketio.emit('player_joined', {
        'player1': room.player1.username if room.player1 else None,
        'player2': room.player2.username if room.player2 else None,
        'username': user.username
    }, room=str(room_id))
    
    socketio.emit('chat_message', {
        'username': 'SYSTEM',
        'message': f'{user.username} joined as {"Player 1" if room.player1_id == user.id else "Player 2"}!',
        'is_system': True,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=str(room_id))
    
    return jsonify({'success': True, 'room_id': room_id})

@app.route('/room/list')
def room_list():
    rooms = Room.query.filter(Room.status != 'ended').all()
    return jsonify([{'id': r.id, 'room_code': r.room_code, 'status': r.status} for r in rooms])

@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ========== PROFILE & API ROUTES ==========
@app.route('/leaderboard')
@login_required
def leaderboard():
    user = get_current_user()
    players = User.query.filter_by(role='player').order_by(User.best_accuracy.desc()).all()
    return render_template('leaderboard.html', players=players, user=user)

@app.route('/profile/<int:user_id>')
@login_required
def profile(user_id):
    target_user = db.session.get(User, user_id)
    current_user = get_current_user()
    
    if not target_user:
        return redirect(url_for('dashboard'))
    
    recent_matches = Submission.query.filter_by(user_id=user_id).order_by(Submission.submitted_at.desc()).limit(20).all()
    
    all_players = User.query.filter_by(role='player').order_by(User.best_accuracy.desc()).all()
    rank = next((i+1 for i, p in enumerate(all_players) if p.id == target_user.id), None)
    
    return render_template('profile.html',
                         target_user=target_user,
                         current_user=current_user,
                         recent_matches=recent_matches,
                         rank=rank)

@app.route('/api/user/<int:user_id>/matches/all')
@login_required
def get_user_all_matches(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
    
    submissions = Submission.query.filter_by(user_id=user_id).order_by(Submission.submitted_at.desc()).all()
    
    matches = []
    for s in submissions:
        matches.append({
            'id': s.id,
            'date': s.submitted_at.strftime('%Y-%m-%d %H:%M') if s.submitted_at else 'Unknown',
            'challenge': s.challenge.title if s.challenge else 'Unknown',
            'type': s.challenge.challenge_type.upper() if s.challenge else '—',
            'accuracy': round(s.accuracy, 1),
            'status': 'Forfeit' if s.is_forfeit else 'Completed'
        })
    
    return jsonify({'success': True, 'matches': matches})

@app.route('/api/match/<int:match_id>')
@login_required
def get_match_details(match_id):
    submission = db.session.get(Submission, match_id)
    if not submission:
        return jsonify({'success': False, 'error': 'Match not found'}), 404
    
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
    
    submissions = Submission.query.filter_by(user_id=user_id, is_forfeit=False).order_by(Submission.submitted_at.desc()).all()
    
    total_matches = len(submissions)
    wins = sum(1 for s in submissions if s.accuracy > 50)
    win_rate = round((wins / total_matches * 100) if total_matches > 0 else 0, 1)
    avg_accuracy = round(sum(s.accuracy for s in submissions) / total_matches, 1) if total_matches > 0 else 0
    
    current_streak = 0
    best_streak = 0
    for s in submissions:
        if s.accuracy >= 50:
            current_streak += 1
            best_streak = max(best_streak, current_streak)
        else:
            current_streak = 0
    
    image_count = sum(1 for s in submissions if s.challenge and s.challenge.challenge_type == 'image')
    html_count = sum(1 for s in submissions if s.challenge and s.challenge.challenge_type == 'html')
    
    return jsonify({
        'success': True,
        'username': user.username,
        'matches_played': user.matches_played,
        'best_accuracy': round(user.best_accuracy, 1),
        'total_wins': user.total_wins,
        'win_rate': win_rate,
        'avg_accuracy': avg_accuracy,
        'best_streak': best_streak,
        'total_submissions': total_matches,
        'image_count': image_count,
        'html_count': html_count,
        'total_score': round(sum(s.accuracy for s in submissions), 1)
    })

@app.route('/setup-test-accounts')
def setup_test_accounts():
    player1 = User.query.filter_by(username='Player1').first()
    if not player1:
        player1 = User(username='Player1', role='player')
        player1.set_password('player1')
        db.session.add(player1)
    
    player2 = User.query.filter_by(username='Player2').first()
    if not player2:
        player2 = User(username='Player2', role='player')
        player2.set_password('player2')
        db.session.add(player2)
    
    spectator = User.query.filter_by(username='Spectator').first()
    if not spectator:
        spectator = User(username='Spectator', role='player')
        spectator.set_password('spectator')
        db.session.add(spectator)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': 'Test accounts created!',
        'accounts': [
            {'username': 'admin', 'password': 'admin123', 'role': 'admin'},
            {'username': 'Player1', 'password': 'player1', 'role': 'player'},
            {'username': 'Player2', 'password': 'player2', 'role': 'player'},
            {'username': 'Spectator', 'password': 'spectator', 'role': 'player'}
        ]
    })


@app.route('/preview')
def preview():
    return render_template('preview.html')

# ========== SOCKET.IO EVENTS ==========
@socketio.on('connect')
def handle_connect():
    print(f"✅ Client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"❌ Client disconnected: {request.sid}")
    if request.sid in connected_users:
        del connected_users[request.sid]

@socketio.on('join_room')
def handle_join_room(data):
    room_id = data.get('room_id')
    username = data.get('username')
    
    print(f"🔵 SOCKET join_room: {username} joining room {room_id}")
    
    if username:
        connected_users[request.sid] = {'username': username, 'room_id': room_id}
    
    join_room(str(room_id))
    
    room = db.session.get(Room, room_id)
    
    # CRITICAL: Send current status to the joining player
    if room:
        if room.status == 'running':
            challenge = room.challenge
            # Send via socket
            emit('challenge_started', {
                'time_limit': challenge.time_limit,
                'challenge_title': challenge.title,
                'room_id': room.id
            }, room=request.sid)
            print(f"🟢 Sent challenge_started to newly joined player {username}")
    
    socketio.emit('chat_message', {
        'username': 'SYSTEM',
        'message': f'{username} joined the arena!',
        'is_system': True,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=str(room_id))



@socketio.on('leave_room')
def handle_leave_room(data):
    room_id = data.get('room_id')
    username = data.get('username')
    
    leave_room(str(room_id))
    
    socketio.emit('chat_message', {
        'username': 'SYSTEM',
        'message': f'{username} left the arena.',
        'is_system': True,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=str(room_id))

@socketio.on('progress_update')
def handle_progress_update(data):
    room_id = data.get('room_id')
    username = data.get('username')
    accuracy = data.get('accuracy')
    
    socketio.emit('progress_update', {
        'username': username,
        'accuracy': accuracy
    }, room=str(room_id), include_self=False)
    
    broadcast_leaderboard(room_id)

@socketio.on('chat_message')
def handle_chat_message(data):
    room_id = data.get('room_id')
    username = data.get('username')
    message = data.get('message')
    
    room = db.session.get(Room, room_id)
    user = User.query.filter_by(username=username).first()
    
    if room and user:
        chat_msg = ChatMessage(
            room_id=room_id,
            user_id=user.id,
            message=message,
            is_system=False
        )
        db.session.add(chat_msg)
        db.session.commit()
    
    socketio.emit('chat_message', {
        'username': username,
        'message': message,
        'is_system': False,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, room=str(room_id))

@socketio.on('cam_frame')
def handle_cam_frame(data):
    room_id = data.get('room_id')
    username = data.get('username')
    frame_data = data.get('frame_data')
    
    socketio.emit('cam_frame', {
        'username': username,
        'frame_data': frame_data
    }, room=str(room_id), include_self=False)

@socketio.on('code_preview')
def handle_code_preview(data):
    room_id = data.get('room_id')
    username = data.get('username')
    compiled_html = data.get('compiled_html')
    
    if room_id not in room_preview_data:
        room_preview_data[room_id] = {}
    room_preview_data[room_id][username] = compiled_html
    
    socketio.emit('admin_preview', {
        'username': username,
        'compiled_html': compiled_html
    })

@socketio.on('forfeit')
def handle_forfeit(data):
    room_id = data.get('room_id')
    username = data.get('username')
    user = User.query.filter_by(username=username).first()
    
    if user:
        submission = Submission(
            user_id=user.id,
            room_id=room_id,
            is_forfeit=True,
            accuracy=0
        )
        db.session.add(submission)
        db.session.commit()
    
    socketio.emit('player_forfeit', {'username': username}, room=str(room_id))

@socketio.on('start_challenge')
def on_start(data):
    print(f"🚀 START_CHALLENGE called with data: {data}")
    
    if session.get('role') != 'admin':
        print("❌ Not admin")
        return
    
    room = db.session.get(Room, data['room_id'])
    if not room:
        print(f"❌ Room {data['room_id']} not found")
        return
    
    if room.status not in ['waiting', 'paused']:
        print(f"❌ Room status is {room.status}")
        return
    
    challenge = room.challenge
    room.status = 'running'
    room.started_by = session['user_id']
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
    
    print(f"✅ Challenge started for room {room.id}")

@socketio.on('pause_challenge')
def on_pause(data):
    if session.get('role') != 'admin':
        return
    room = db.session.get(Room, data['room_id'])
    if room and room.status == 'running':
        room.status = 'paused'
        db.session.commit()
        socketio.emit('challenge_paused', {'remaining': room_timers.get(data['room_id'], 0)}, room=str(data['room_id']))

@socketio.on('resume_challenge')
def on_resume(data):
    if session.get('role') != 'admin':
        return
    room = db.session.get(Room, data['room_id'])
    if room and room.status == 'paused':
        room.status = 'running'
        db.session.commit()
        socketio.emit('challenge_resumed', {}, room=str(data['room_id']))

@socketio.on('add_time')
def on_add_time(data):
    if session.get('role') != 'admin':
        return
    rid = data['room_id']
    room_timers[rid] = room_timers.get(rid, 0) + int(data.get('seconds', 30))
    socketio.emit('timer_tick', {'remaining': room_timers[rid]}, room=str(rid))

@socketio.on('end_challenge')
def on_end(data):
    if session.get('role') != 'admin':
        return
    rid = data['room_id']
    room_timers[rid] = 0
    room = db.session.get(Room, rid)
    if room:
        room.status = 'ended'
        room.ended_at = datetime.now(timezone.utc)
        db.session.commit()
    socketio.emit('challenge_ended', {'room_id': rid}, room=str(rid))

@socketio.on('broadcast_message')
def on_broadcast(data):
    if session.get('role') != 'admin':
        return
    message = data.get('message')
    room_id = data.get('room_id')
    if room_id:
        socketio.emit('system_announcement', {'message': message}, room=str(room_id))
    else:
        for room in Room.query.all():
            socketio.emit('system_announcement', {'message': message}, room=str(room.id))

@socketio.on('kick_player')
def on_kick(data):
    if session.get('role') != 'admin':
        return
    target = data.get('username')
    socketio.emit('kicked', {'message': 'You were removed by the admin.'}, room=f"user_{target}")



@socketio.on('check_challenge_status')
def handle_check_status(data):
    print(f"📡 Status check request from {request.sid}")
    room = db.session.get(Room, data['room_id'])
    if room and room.status == 'running':
        challenge = room.challenge
        emit('challenge_started', {
            'time_limit': challenge.time_limit,
            'challenge_title': challenge.title,
            'room_id': room.id
        })
        print(f"📡 Sent challenge_started to {request.sid}")


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

@app.route('/debug/add-player/<int:room_id>/<string:player_type>')
@admin_required
def debug_add_player(room_id, player_type):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    
    player1 = User.query.filter_by(username='Player1').first()
    player2 = User.query.filter_by(username='Player2').first()
    
    if player_type == 'p1' and player1:
        room.player1_id = player1.id
    elif player_type == 'p2' and player2:
        room.player2_id = player2.id
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'room_id': room.id,
        'player1': room.player1.username if room.player1 else None,
        'player2': room.player2.username if room.player2 else None
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
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        admin = User.query.filter_by(role='admin').first()
        if not admin:
            admin = User(username='admin', role='admin')
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print("=" * 50)
            print("Admin created successfully!")
            print("Username: admin")
            print("Password: admin123")
            print("=" * 50)
        else:
            print("Admin user already exists")
    
    print("\n" + "=" * 50)
    print("UI BATTLE ARENA is starting...")
    print("Open http://localhost:5001 in your browser")
    print("=" * 50 + "\n")
    
    # Use eventlet as the async mode
    socketio.run(app, host='0.0.0.0', port=8080, debug=True, use_reloader=False)