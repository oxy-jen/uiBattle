from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    auth_provider = db.Column(db.String(20), default='local')
    google_sub = db.Column(db.String(255), unique=True, nullable=True)
    two_factor_secret = db.Column(db.String(64), nullable=True)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_recovery_hashes = db.Column(db.Text, nullable=True)
    role = db.Column(db.String(10), default='player')
    matches_played = db.Column(db.Integer, default=0)
    best_accuracy = db.Column(db.Float, default=0.0)
    total_wins = db.Column(db.Integer, default=0)
    leaderboard_unlocked_at = db.Column(db.DateTime, nullable=True)
    leaderboard_awarded = db.Column(db.Boolean, default=False)
    leaderboard_awarded_at = db.Column(db.DateTime, nullable=True)
    leaderboard_awarded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    leaderboard_award_reason = db.Column(db.String(200), nullable=True)
    leaderboard_award_details = db.Column(db.Text, nullable=True)
    leaderboard_award_color = db.Column(db.String(20), nullable=True)
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
            'total_wins': self.total_wins,
            'leaderboard_unlocked': bool(self.leaderboard_unlocked_at or self.leaderboard_awarded)
        }

class Challenge(db.Model):
    __tablename__ = 'challenges'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    difficulty = db.Column(db.String(10), default='Medium')
    time_limit = db.Column(db.Integer, default=120)
    
    challenge_type = db.Column(db.String(30), default='image')
    
    target_image_path = db.Column(db.String(200), nullable=True)
    target_html = db.Column(db.Text, nullable=True)
    target_css = db.Column(db.Text, nullable=True)
    target_js = db.Column(db.Text, nullable=True)
    starter_html = db.Column(db.Text, nullable=True)
    starter_css = db.Column(db.Text, nullable=True)
    starter_js = db.Column(db.Text, nullable=True)
    html_locked = db.Column(db.Boolean, default=True)
    website_config = db.Column(db.Text, nullable=True)
    
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
    is_public = db.Column(db.Boolean, default=False)
    competition_id = db.Column(db.Integer, db.ForeignKey('competitions.id'), nullable=True)
    wave_id = db.Column(db.Integer, db.ForeignKey('competition_waves.id'), nullable=True)
    
    challenge = db.relationship('Challenge', backref='rooms')
    player1 = db.relationship('User', foreign_keys=[player1_id])
    player2 = db.relationship('User', foreign_keys=[player2_id])

class RoomAccess(db.Model):
    __tablename__ = 'room_access'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='spectator')
    status = db.Column(db.String(20), nullable=False, default='active')
    granted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reason = db.Column(db.String(240), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('room_id', 'user_id', name='uq_room_access_room_user'),
    )

    room = db.relationship('Room', backref='access_records')
    user = db.relationship('User', foreign_keys=[user_id], backref='room_access_records')
    grant_admin = db.relationship('User', foreign_keys=[granted_by])

class Competition(db.Model):
    __tablename__ = 'competitions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    format = db.Column(db.String(40), default='single_room')
    stage = db.Column(db.String(40), default='registration')
    status = db.Column(db.String(30), default='registration')
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournaments.id'), nullable=True)
    max_participants = db.Column(db.Integer, default=2)
    room_mode = db.Column(db.String(20), default='1v1')
    players_per_wave = db.Column(db.Integer, default=100)
    room_visibility = db.Column(db.String(20), default='private')
    start_at = db.Column(db.String(80), nullable=True)
    end_at = db.Column(db.String(80), nullable=True)
    auto_start = db.Column(db.Boolean, default=False)
    auto_submit = db.Column(db.Boolean, default=True)
    allowed_attempts = db.Column(db.String(20), default='one')
    tie_break_rule = db.Column(db.String(120), default='higher_score_then_time')
    advance_rule = db.Column(db.String(120), default='top_32')
    fair_play_strictness = db.Column(db.String(20), default='normal')
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    challenge = db.relationship('Challenge', backref='competitions')
    tournament = db.relationship('Tournament', backref='source_competitions')
    creator = db.relationship('User', foreign_keys=[created_by])

class CompetitionWave(db.Model):
    __tablename__ = 'competition_waves'

    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competitions.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(30), default='scheduled')
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=True)
    start_at = db.Column(db.String(80), nullable=True)
    end_at = db.Column(db.String(80), nullable=True)
    players_expected = db.Column(db.Integer, default=0)
    rooms_created = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    competition = db.relationship('Competition', backref='waves')
    challenge = db.relationship('Challenge', backref='competition_waves')

class CompetitionAdminAssignment(db.Model):
    __tablename__ = 'competition_admin_assignments'

    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competitions.id'), nullable=False)
    wave_id = db.Column(db.Integer, db.ForeignKey('competition_waves.id'), nullable=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(40), default='room_admin')
    room_range_start = db.Column(db.Integer, nullable=True)
    room_range_end = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    competition = db.relationship('Competition', backref='admin_assignments')
    wave = db.relationship('CompetitionWave', backref='admin_assignments')
    admin = db.relationship('User', foreign_keys=[admin_id])

class AdminTask(db.Model):
    __tablename__ = 'admin_tasks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)
    task_type = db.Column(db.String(40), default='room_watch')
    priority = db.Column(db.String(20), default='normal')
    status = db.Column(db.String(20), default='open')
    competition_id = db.Column(db.Integer, db.ForeignKey('competitions.id'), nullable=True)
    wave_id = db.Column(db.Integer, db.ForeignKey('competition_waves.id'), nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    room_range_start = db.Column(db.Integer, nullable=True)
    room_range_end = db.Column(db.Integer, nullable=True)
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    due_at = db.Column(db.String(80), nullable=True)
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    competition = db.relationship('Competition', backref='admin_tasks')
    wave = db.relationship('CompetitionWave', backref='admin_tasks')
    room = db.relationship('Room', backref='admin_tasks')
    assigned_admin = db.relationship('User', foreign_keys=[assigned_admin_id], backref='assigned_admin_tasks')
    creator = db.relationship('User', foreign_keys=[created_by])

class DisputeCase(db.Model):
    __tablename__ = 'dispute_cases'

    id = db.Column(db.Integer, primary_key=True)
    competition_id = db.Column(db.Integer, db.ForeignKey('competitions.id'), nullable=True)
    wave_id = db.Column(db.Integer, db.ForeignKey('competition_waves.id'), nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    player_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    type = db.Column(db.String(40), default='manual_review')
    status = db.Column(db.String(30), default='open')
    priority = db.Column(db.String(20), default='normal')
    reason = db.Column(db.String(220), nullable=False)
    resolution = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)

    competition = db.relationship('Competition', backref='disputes')
    wave = db.relationship('CompetitionWave', backref='disputes')
    room = db.relationship('Room', backref='disputes')
    player = db.relationship('User', foreign_keys=[player_id])
    creator = db.relationship('User', foreign_keys=[created_by])
    resolver = db.relationship('User', foreign_keys=[resolved_by])

class Tournament(db.Model):
    __tablename__ = 'tournaments'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    size = db.Column(db.Integer, nullable=False, default=8)
    challenge_id = db.Column(db.Integer, db.ForeignKey('challenges.id'), nullable=False)
    status = db.Column(db.String(20), default='waiting')
    auto_advance = db.Column(db.Boolean, default=True)
    certificate_settings = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)

    challenge = db.relationship('Challenge', backref='tournaments')
    creator = db.relationship('User', foreign_keys=[created_by])

class TournamentParticipant(db.Model):
    __tablename__ = 'tournament_participants'

    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournaments.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    seed = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='active')
    position = db.Column(db.String(40), default='Participant')
    final_score = db.Column(db.Float, default=0.0)
    matches_played = db.Column(db.Integer, default=0)
    certificate_id = db.Column(db.String(64), nullable=True)
    admin_note = db.Column(db.Text, nullable=True)
    reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tournament = db.relationship('Tournament', backref='participants')
    user = db.relationship('User', backref='tournament_entries')

class TournamentMatch(db.Model):
    __tablename__ = 'tournament_matches'

    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournaments.id'), nullable=False)
    round_number = db.Column(db.Integer, nullable=False)
    round_name = db.Column(db.String(40), nullable=False)
    match_number = db.Column(db.Integer, nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=True)
    player1_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    player2_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    winner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status = db.Column(db.String(20), default='waiting')
    is_manual_override = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    tournament = db.relationship('Tournament', backref='matches')
    room = db.relationship('Room', backref='tournament_match')
    player1 = db.relationship('User', foreign_keys=[player1_id])
    player2 = db.relationship('User', foreign_keys=[player2_id])
    winner = db.relationship('User', foreign_keys=[winner_id])

class MatchResult(db.Model):
    __tablename__ = 'match_results'

    id = db.Column(db.Integer, primary_key=True)
    tournament_match_id = db.Column(db.Integer, db.ForeignKey('tournament_matches.id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    score = db.Column(db.Float, default=0.0)
    is_winner = db.Column(db.Boolean, default=False)
    source = db.Column(db.String(20), default='auto')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tournament_match = db.relationship('TournamentMatch', backref='results')
    room = db.relationship('Room', backref='match_results')
    player = db.relationship('User', backref='match_results')

class AdminAction(db.Model):
    __tablename__ = 'admin_actions'

    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournaments.id'), nullable=True)
    tournament_match_id = db.Column(db.Integer, db.ForeignKey('tournament_matches.id'), nullable=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action_type = db.Column(db.String(40), nullable=False)
    reason = db.Column(db.String(200), nullable=False)
    admin_note = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    tournament = db.relationship('Tournament', backref='admin_actions')
    tournament_match = db.relationship('TournamentMatch', backref='admin_actions')
    admin = db.relationship('User', foreign_keys=[admin_id])
    player = db.relationship('User', foreign_keys=[player_id])

class AwardCard(db.Model):
    __tablename__ = 'award_cards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    awarded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(140), nullable=False)
    reason = db.Column(db.String(200), nullable=True)
    message = db.Column(db.Text, nullable=True)
    card_template = db.Column(db.String(40), default='champion')
    avatar_template = db.Column(db.String(40), default='spark')
    accent_icon = db.Column(db.String(40), default='fa-award')
    avatar_label = db.Column(db.String(80), nullable=True)
    primary_color = db.Column(db.String(20), default='#22d3ee')
    secondary_color = db.Column(db.String(20), default='#f59e0b')
    student_color = db.Column(db.String(20), nullable=True)
    shape = db.Column(db.String(20), default='rounded')
    avatar_shape = db.Column(db.String(20), default='circle')
    layout = db.Column(db.String(20), default='classic')
    certificate_payload = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', foreign_keys=[user_id], backref='award_cards')
    admin = db.relationship('User', foreign_keys=[awarded_by])

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
    score_details = db.Column(db.Text)
    is_forfeit = db.Column(db.Boolean, default=False)
    is_final = db.Column(db.Boolean, default=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='submissions')
    room = db.relationship('Room', backref='submissions')
    challenge = db.relationship('Challenge', backref='submissions')

class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    message = db.Column(db.Text, nullable=False)
    is_system = db.Column(db.Boolean, default=False)
    is_flagged = db.Column(db.Boolean, default=False)
    flag_reason = db.Column(db.String(160), nullable=True)
    flagged_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id], backref='messages')
    flagger = db.relationship('User', foreign_keys=[flagged_by])
