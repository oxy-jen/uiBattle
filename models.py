from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(10), default='player')
    matches_played = db.Column(db.Integer, default=0)
    best_accuracy = db.Column(db.Float, default=0.0)
    total_wins = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'matches_played': self.matches_played,
            'best_accuracy': round(self.best_accuracy, 1),
            'total_wins': self.total_wins
        }

class Challenge(db.Model):
    __tablename__ = 'challenges'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    difficulty = db.Column(db.String(10), default='Medium')
    time_limit = db.Column(db.Integer, default=120)
    
    challenge_type = db.Column(db.String(10), default='image')
    
    target_image_path = db.Column(db.String(200), nullable=True)
    target_html = db.Column(db.Text, nullable=True)
    target_css = db.Column(db.Text, nullable=True)
    html_locked = db.Column(db.Boolean, default=True)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

class Room(db.Model):
    __tablename__ = 'rooms'
    
    id = db.Column(db.Integer, primary_key=True)
    room_code = db.Column(db.String(10), unique=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'))
    status = db.Column(db.String(10), default='waiting')
    player1_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    player2_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    started_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    
    challenge = db.relationship('Challenge', backref='rooms')
    player1 = db.relationship('User', foreign_keys=[player1_id])
    player2 = db.relationship('User', foreign_keys=[player2_id])

class Submission(db.Model):
    __tablename__ = 'submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'))
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'))
    html_code = db.Column(db.Text)
    css_code = db.Column(db.Text)
    js_code = db.Column(db.Text)
    accuracy = db.Column(db.Float, default=0.0)
    is_forfeit = db.Column(db.Boolean, default=False)
    is_final = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='submissions')

class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    message = db.Column(db.Text, nullable=False)
    is_system = db.Column(db.Boolean, default=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='messages')