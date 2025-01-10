import configparser
from flask import Flask, jsonify, render_template, send_from_directory, url_for, redirect, request, flash
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
if not os.path.exists('logs'):
    os.makedirs('logs')

formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)

file_handler = RotatingFileHandler(
    'logs/app.log', 
    maxBytes=10485760,  # 10MB
    backupCount=10
)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

# Also log to console in debug mode
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.DEBUG)

# Load configuration
config = configparser.ConfigParser()
config.read("config.ini")

# Configure Flask logger
app = Flask(__name__)

# Remove Flask's default handlers when in debug mode
app.logger.handlers.clear()

# Add our custom handlers
app.logger.addHandler(file_handler)
app.logger.addHandler(console_handler)
app.logger.setLevel(logging.INFO)

app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY')  # Load secret key from environment
socketio = SocketIO(app, cors_allowed_origins=[domain.strip() for domain in config["DEFAULT"]["ALLOWED_DOMAINS"].split(",")])

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

app.logger.info('Application startup: Initializing components')

# Simple User class for the owner
class User(UserMixin):
    def __init__(self, id):
        self.id = id

# Create a single owner user
owner = User(1)

@login_manager.user_loader
def load_user(user_id):
    if int(user_id) == 1:  # Only the owner (id=1) is valid
        return owner
    return None

# Login route
@app.route("/admin/login", methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == os.getenv('OWNER_PASSWORD'):  # Check against environment variable
            login_user(owner)
            app.logger.info('Owner login successful')
            return redirect(url_for('admin_dashboard'))
        app.logger.warning('Failed login attempt with incorrect password')
        flash('Invalid password')
    return render_template('login.html')

@app.route("/admin")
@login_required
def admin_dashboard():
    app.logger.info('Listing videos')
    video_states = []

    try:
        # Iterate over subdirectories in MEDIA_DIR
        for dirname in os.listdir(MEDIA_DIR):
            dirpath = os.path.join(MEDIA_DIR, dirname)

            if os.path.isdir(dirpath):
                # Check for manifest.mpd
                manifest_path = os.path.join(dirpath, "manifest.mpd")
                if os.path.exists(manifest_path):
                    state = "Ready"
                else:
                    # Check if a run file exists for this torrent
                    run_file = os.path.join(RUN_DIR, f"transcode_{dirname}.run")
                    state = "Not Ready" if os.path.exists(run_file) else "Incomplete"

                # Get directory creation time
                creation_time = datetime.fromtimestamp(os.path.getctime(dirpath))
                formatted_time = creation_time.strftime("%Y-%m-%d %H:%M:%S")

                video_states.append({
                    "name": dirname,
                    "state": state,
                    "created": formatted_time
                })
                app.logger.debug(f'Found video: {dirname} (state: {state})')
    except Exception as e:
        app.logger.error(f"Error listing videos: {str(e)}")
        # Continue with empty video_states list
        
    # Render the state in the web interface
    return render_template("index.html", videos=video_states)

@app.route("/admin/logout")
@login_required
def admin_logout():
    app.logger.info('Owner logged out')
    logout_user()
    return redirect(url_for('admin_login'))

# Store current playback state in memory
current_playback = {
    "status": "PAUSED",
    "time": 0
}

# Paths
MEDIA_DIR = config["DEFAULT"]["MEDIA_DIR"]
RUN_DIR = config["DEFAULT"]["RUN_DIR"]

# Ensure required directories exist
try:
    os.makedirs(MEDIA_DIR, exist_ok=True)
    os.makedirs(RUN_DIR, exist_ok=True)
    app.logger.info(f'Ensured directories exist: MEDIA_DIR={MEDIA_DIR}, RUN_DIR={RUN_DIR}')
except Exception as e:
    app.logger.error(f'Failed to create required directories: {str(e)}')

# Make the video player the default route
@app.route("/")
def default_player():
    # Find the first ready video
    try:
        for dirname in os.listdir(MEDIA_DIR):
            dirpath = os.path.join(MEDIA_DIR, dirname)
            if os.path.isdir(dirpath):
                manifest_path = os.path.join(dirpath, "manifest.mpd")
                if os.path.exists(manifest_path):
                    return redirect(url_for('player', video_name=dirname))
    except Exception as e:
        app.logger.error(f"Error finding default video: {str(e)}")
    
    return "No videos available", 404

@app.route("/player/<video_name>")
def player(video_name):
    app.logger.info(f'Accessing player for video: {video_name}')
    # Verify the manifest exists
    manifest_path = os.path.join(MEDIA_DIR, video_name, "manifest.mpd")
    if not os.path.exists(manifest_path):
        app.logger.warning(f'Manifest not found for video: {video_name}')
        return "Video not ready", 404
        
    # Generate the manifest URL
    manifest_url = url_for('serve_manifest', video_name=video_name)
    # Pass is_owner flag to template
    return render_template("player.html", manifest_url=manifest_url, video_name=video_name, is_owner=current_user.is_authenticated)

@app.route("/manifest/<video_name>/manifest.mpd")
def serve_manifest(video_name):
    app.logger.debug(f'Serving manifest for video: {video_name}')
    return send_from_directory(os.path.join(MEDIA_DIR, video_name), "manifest.mpd")

# Add new route for serving video segments
@app.route("/manifest/<video_name>/<path:filename>")
def serve_video_segment(video_name, filename):
    return send_from_directory(os.path.join(MEDIA_DIR, video_name), filename)

# Socket.IO event handlers
@socketio.on('connect')
def handle_connect():
    app.logger.info(f'New client connected: {request.sid}')
    # Send current playback state to new client
    emit('currentPlayback', current_playback)

@socketio.on('disconnect')
def handle_disconnect():
    app.logger.info(f'Client disconnected: {request.sid}')

@socketio.on('playbackCommand')
def handle_playback_command(data):
    # Only allow owner to control playback
    if not current_user.is_authenticated:
        app.logger.warning(f'Unauthorized playback command from {request.sid}')
        return
        
    # Update server's playback state
    current_playback['time'] = data['time']
    if data['action'] == 'PLAY':
        current_playback['status'] = 'PLAYING'
        app.logger.info(f'Owner started playback at time: {data["time"]}')
    elif data['action'] == 'PAUSE':
        current_playback['status'] = 'PAUSED'
        app.logger.info(f'Owner paused playback at time: {data["time"]}')
    
    # Broadcast to all other clients
    emit('playbackCommand', data, broadcast=True, include_self=False)
    app.logger.debug(f'Broadcasted playback command to all clients')

@socketio.on('timeUpdate')
def handle_time_update(time):
    if current_user.is_authenticated:  # Only owner can update time
        current_playback['time'] = time
        app.logger.debug(f'Updated playback time to: {time}')

if __name__ == "__main__":
    app.logger.info('Starting application server')
    socketio.run(app, host="0.0.0.0", port=8080, debug=True)
