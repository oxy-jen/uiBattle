from functools import wraps
from flask import session, redirect, url_for, flash, request, jsonify
from models import User

def wants_json_response():
    return (
        request.is_json
        or request.accept_mimetypes.best == 'application/json'
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login_page'))
        user = User.query.get(session['user_id'])
        if not user:
            session.clear()
            return redirect(url_for('maintenance_page'))
        session['role'] = user.role
        session['username'] = user.username
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if wants_json_response():
                return jsonify({'success': False, 'error': 'Please log in again as an admin'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login_page'))
        user = User.query.get(session['user_id'])
        if not user:
            session.clear()
            if wants_json_response():
                return jsonify({'success': False, 'error': 'The arena was reset. Please log in again.'}), 401
            return redirect(url_for('maintenance_page'))
        session['role'] = user.role
        session['username'] = user.username
        if user.role != 'admin':
            if wants_json_response():
                return jsonify({'success': False, 'error': 'Admin access required'}), 403
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def get_current_user():
    from app import db
    if 'user_id' in session:
        return db.session.get(User, session['user_id'])
    return None
