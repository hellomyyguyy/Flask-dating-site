from flask import Flask, render_template, request, redirect, url_for, session, flash
from models import db, User, UserImage, Match, Message
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
import os
import requests
from flask import g
from math import radians, sin, cos, sqrt, atan2

app = Flask(__name__)
app.secret_key = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dating_app.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
db.init_app(app)
migrate = Migrate(app, db)

IPGEOLOCATION_API_KEY = 'your-ipgeolocation-api-key-here'

# Simulated locations for local testing
SIMULATED_LOCATIONS = {
    1: (40.7128, -74.0060),  # New York
    2: (34.0522, -118.2437),  # Los Angeles
    3: (51.5074, -0.1278),  # London
    4: (35.6762, 139.6503),  # Tokyo
}

with app.app_context():
    db.create_all()


def get_geolocation(ip_address=''):
    if ip_address == '127.0.0.1' or not ip_address:
        return None, None
    url = f"https://api.ipgeolocation.io/ipgeo?apiKey={IPGEOLOCATION_API_KEY}&ip={ip_address}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        lat, lon = data.get('latitude'), data.get('longitude')
        if lat and lon:
            app.logger.debug(f"Geolocation for IP {ip_address}: ({lat}, {lon})")
            return float(lat), float(lon)
        return None, None
    except Exception as e:
        app.logger.error(f"Geolocation error: {e}")
        return None, None


def haversine_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return float('inf')
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


@app.before_request
def load_user():
    if request.path.startswith('/static'):
        app.logger.debug(f"Serving static file: {request.path}")
        return

    if 'user_id' in session:
        g.current_user = User.query.get(session['user_id'])
        if g.current_user is None:
            session.pop('user_id', None)
            if request.endpoint not in ['index', 'register', 'login']:
                return redirect(url_for('index'))
        elif not g.current_user.profile_complete and request.endpoint not in ['register', 'login']:
            return redirect(url_for('register'))
        else:
            if not g.current_user.latitude or not g.current_user.longitude:
                ip = request.remote_addr
                lat, lon = get_geolocation(ip)
                if lat and lon:
                    g.current_user.latitude = lat
                    g.current_user.longitude = lon
                elif ip == '127.0.0.1' and g.current_user.id in SIMULATED_LOCATIONS:
                    g.current_user.latitude, g.current_user.longitude = SIMULATED_LOCATIONS[g.current_user.id]
                db.session.commit()
                app.logger.debug(
                    f"Set geolocation for user {g.current_user.id}: ({g.current_user.latitude}, {g.current_user.longitude})")
    else:
        g.current_user = None
        if request.endpoint not in ['index', 'register', 'login']:
            return redirect(url_for('index'))


@app.route('/')
def index():
    if 'user_id' in session and g.current_user and g.current_user.profile_complete:
        return redirect(url_for('hub'))
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session and g.current_user and g.current_user.profile_complete:
        return redirect(url_for('hub'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('Please provide both username and password')
            return redirect(url_for('login'))

        user = User.query.filter_by(username=username).first()

        if user and user.password == password:
            session['user_id'] = user.id
            app.logger.debug(f"Login successful for user {user.id}")
            if user.profile_complete:
                return redirect(url_for('hub'))
            return redirect(url_for('register'))
        else:
            flash('Invalid username or password')
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        bio = request.form.get('bio')

        if not username or not password or not bio:
            flash('All fields are required')
            return redirect(url_for('register'))

        if 'user_id' not in session:
            if User.query.filter_by(username=username).first():
                flash('Username already exists')
                return redirect(url_for('register'))
            user = User(username=username, password=password, bio=bio)
            db.session.add(user)
            db.session.commit()
            session['user_id'] = user.id
            ip = request.remote_addr
            lat, lon = get_geolocation(ip)
            if lat and lon:
                user.latitude = lat
                user.longitude = lon
            elif ip == '127.0.0.1' and user.id in SIMULATED_LOCATIONS:
                user.latitude, user.longitude = SIMULATED_LOCATIONS[user.id]
            db.session.commit()
        else:
            user = User.query.get(session['user_id'])
            if not user:
                session.pop('user_id', None)
                flash('Session expired, please sign up again')
                return redirect(url_for('index'))
            user.bio = bio

        if 'images' in request.files:
            files = request.files.getlist('images')
            for file in files:
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image = UserImage(user_id=user.id, image_path=filename)
                    db.session.add(image)

        if user.bio and UserImage.query.filter_by(user_id=user.id).count() > 0:
            user.profile_complete = True

        db.session.commit()
        return redirect(url_for('hub'))

    return render_template('register.html',
                           editing='user_id' in session,
                           current_user=g.current_user if 'user_id' in session else None,
                           bio=g.current_user.bio if g.current_user else '')


@app.route('/hub')
def hub():
    if 'user_id' not in session or not g.current_user or not g.current_user.profile_complete:
        return redirect(url_for('index'))
    return render_template('hub.html', current_user=g.current_user)


@app.route('/match', methods=['GET', 'POST'])
def match():
    if 'user_id' not in session or not g.current_user or not g.current_user.profile_complete:
        return redirect(url_for('register'))

    current_user = g.current_user

    if request.method == 'POST':
        other_user_id = int(request.form['user_id'])
        liked = request.form['action'] == 'like'

        match = Match.query.filter(
            ((Match.user1_id == current_user.id) & (Match.user2_id == other_user_id)) |
            ((Match.user1_id == other_user_id) & (Match.user2_id == current_user.id))
        ).first()

        if not match:
            match = Match(user1_id=current_user.id, user2_id=other_user_id, user1_liked=liked)
            db.session.add(match)
        else:
            if match.user1_id == current_user.id:
                match.user1_liked = liked
            else:
                match.user2_liked = liked

        if match.user1_liked and match.user2_liked:
            other_user = User.query.get(other_user_id)
            flash(f"Match confirmed! You and {other_user.username} like each other. Start messaging now!", "success")
            app.logger.debug(f"Mutual match between {current_user.id} and {other_user_id}")

        db.session.commit()
        app.logger.debug(f"Match updated: user1_id={match.user1_id}, user2_id={match.user2_id}, "
                         f"user1_liked={match.user1_liked}, user2_liked={match.user2_liked}")
        return redirect(url_for('match'))

    decided_matches = Match.query.filter(
        (Match.user1_id == current_user.id) & (Match.user1_liked.isnot(None)) |
        (Match.user2_id == current_user.id) & (Match.user2_liked.isnot(None))
    ).all()

    decided_user_ids = set()
    for match in decided_matches:
        if match.user1_id == current_user.id:
            decided_user_ids.add(match.user2_id)
        else:
            decided_user_ids.add(match.user1_id)

    all_users = User.query.filter(
        User.id != current_user.id,
        User.profile_complete == True
    ).all()

    available_users = [user for user in all_users if user.id not in decided_user_ids]

    next_user = None
    distance = None
    if available_users:
        if not current_user.latitude or not current_user.longitude:
            app.logger.warning(f"User {current_user.id} has no geolocation; sorting randomly")
            next_user = available_users[0]
        else:
            available_users.sort(key=lambda u: haversine_distance(
                current_user.latitude, current_user.longitude,
                u.latitude if u.latitude else SIMULATED_LOCATIONS.get(u.id, (0, 0))[0],
                u.longitude if u.longitude else SIMULATED_LOCATIONS.get(u.id, (0, 0))[1]
            ))
            next_user = available_users[0]
            distance = haversine_distance(
                current_user.latitude, current_user.longitude,
                next_user.latitude if next_user.latitude else SIMULATED_LOCATIONS.get(next_user.id, (0, 0))[0],
                next_user.longitude if next_user.longitude else SIMULATED_LOCATIONS.get(next_user.id, (0, 0))[1]
            )

    if next_user:
        app.logger.debug(
            f"Next user: {next_user.username} (id: {next_user.id}), Distance: {distance if distance is not None else 'Unknown'} km")
    else:
        app.logger.debug(f"No more users to match with for user {current_user.id}")

    return render_template('match.html', user=next_user, distance=distance)


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('You have been logged out')
    return redirect(url_for('index'))


@app.route('/messages', methods=['GET'])
def messages():
    if 'user_id' not in session or not g.current_user or not g.current_user.profile_complete:
        return redirect(url_for('register'))

    current_user = g.current_user

    mutual_matches = Match.query.filter(
        ((Match.user1_id == current_user.id) & (Match.user2_liked == True)) |
        ((Match.user2_id == current_user.id) & (Match.user1_liked == True)),
        Match.user1_liked == True,
        Match.user2_liked == True
    ).all()

    app.logger.debug(f"Found {len(mutual_matches)} mutual matches for user {current_user.id}")

    # Calculate distances for each match
    matches_with_distance = []
    for match in mutual_matches:
        other_user = match.user2 if match.user1_id == current_user.id else match.user1
        distance = haversine_distance(
            current_user.latitude, current_user.longitude,
            other_user.latitude if other_user.latitude else SIMULATED_LOCATIONS.get(other_user.id, (0, 0))[0],
            other_user.longitude if other_user.longitude else SIMULATED_LOCATIONS.get(other_user.id, (0, 0))[1]
        )
        matches_with_distance.append((match, distance))
        app.logger.debug(f"Match: {other_user.username} (id: {other_user.id}), Distance: {distance:.2f} km")

    selected_user_id = request.args.get('user_id', type=int)
    messages = []
    selected_user = None
    selected_distance = None

    if selected_user_id:
        selected_user = User.query.get(selected_user_id)
        if selected_user:
            messages = Message.query.filter(
                ((Message.sender_id == current_user.id) & (Message.receiver_id == selected_user.id)) |
                ((Message.sender_id == selected_user.id) & (Message.receiver_id == current_user.id))
            ).order_by(Message.timestamp.asc()).all()
            selected_distance = haversine_distance(
                current_user.latitude, current_user.longitude,
                selected_user.latitude if selected_user.latitude else SIMULATED_LOCATIONS.get(selected_user.id, (0, 0))[
                    0],
                selected_user.longitude if selected_user.longitude else
                SIMULATED_LOCATIONS.get(selected_user.id, (0, 0))[1]
            )

    return render_template('messages.html',
                           matches_with_distance=matches_with_distance,
                           current_user=current_user,
                           selected_user=selected_user,
                           selected_distance=selected_distance,
                           messages=messages)


@app.route('/send_message', methods=['POST'])
def send_message():
    if 'user_id' not in session or not g.current_user or not g.current_user.profile_complete:
        return redirect(url_for('register'))

    sender = g.current_user
    receiver_id = request.form['receiver_id']
    content = request.form['content'].strip()

    if not content:
        flash('Message cannot be empty')
        return redirect(url_for('messages', user_id=receiver_id))

    message = Message(sender_id=sender.id, receiver_id=receiver_id, content=content)
    db.session.add(message)
    db.session.commit()

    return redirect(url_for('messages', user_id=receiver_id))

@app.before_request
def log_request():
    if request.path.startswith('/static'):
        app.logger.debug(f"Serving static file: {request.path}")


if __name__ == '__main__':
    app.run(debug=True)