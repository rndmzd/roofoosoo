import configparser
from flask import Flask, jsonify, render_template, send_from_directory, url_for, redirect, request, flash, make_response
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_caching import Cache
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
import redis
import json

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

# Clear any existing handlers to prevent duplication
app.logger.handlers.clear()

# Add our custom handlers
app.logger.addHandler(file_handler)
if app.debug:
    app.logger.addHandler(console_handler)
app.logger.setLevel(logging.INFO)
# Prevent propagation to avoid duplicate logs
app.logger.propagate = False

# Configure caching
cache = Cache(app, config={
    'CACHE_TYPE': 'filesystem',
    'CACHE_DIR': 'cache',
    'CACHE_DEFAULT_TIMEOUT': 300,
    'CACHE_THRESHOLD': 1000  # Maximum number of items in cache
})

app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY')
csrf = CSRFProtect(app)

socketio = SocketIO(app, cors_allowed_origins=[domain.strip() for domain in config["DEFAULT"]["ALLOWED_DOMAINS"].split(",")])

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

app.logger.info('Application startup: Initializing components')

# Configure Redis
redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    db=0,
    decode_responses=True
)

# Initialize playback state in Redis if not exists
def get_playback_state():
    state = redis_client.get('playback_state')
    if state is None:
        default_state = {
            "status": "PAUSED",
            "time": 0
        }
        redis_client.set('playback_state', json.dumps(default_state))
        return default_state
    return json.loads(state)

def update_playback_state(state):
    redis_client.set('playback_state', json.dumps(state))

# Enhanced User class
class User(UserMixin):
    def __init__(self, id, password_hash):
        self.id = id
        self.password_hash = password_hash

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Create owner user with hashed password
owner_password = os.getenv('OWNER_PASSWORD')
owner = User(1, generate_password_hash(owner_password))

@login_manager.user_loader
def load_user(user_id):
    if int(user_id) == 1:  # Only the owner (id=1) is valid
        return owner
    return None

# Login route with rate limiting
@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if owner.check_password(password):
            login_user(owner)
            app.logger.info('Owner login successful')
            return redirect(url_for('list_videos'))
        app.logger.warning(f'Failed login attempt from IP: {get_remote_address()}')
        flash('Invalid password')
    return render_template('login.html')

@app.route("/logout")
@login_required
def logout():
    app.logger.info('Owner logged out')
    logout_user()
    return redirect(url_for('login'))

# Store current playback state in memory
# current_playback = {
#     "status": "PAUSED",
#     "time": 0
# }

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

@app.route("/")
@login_required  # Only allow authenticated users (owner) to access the index
def list_videos():
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

@app.route("/player/<video_name>")
def player(video_name):
    try:
        app.logger.info(f'Accessing player for video: {video_name}')
        # Sanitize video name to prevent directory traversal
        if '..' in video_name or '/' in video_name:
            app.logger.warning(f'Attempted directory traversal with video name: {video_name}')
            return "Invalid video name", 400

        # Verify the manifest exists
        manifest_path = os.path.join(MEDIA_DIR, video_name, "manifest.mpd")
        if not os.path.exists(manifest_path):
            app.logger.warning(f'Manifest not found for video: {video_name}')
            return render_template("error.html", error="Video not found or not ready"), 404
            
        # Generate the manifest URL
        manifest_url = url_for('serve_manifest', video_name=video_name)
        return render_template("player.html", manifest_url=manifest_url, video_name=video_name, is_owner=current_user.is_authenticated)
    except Exception as e:
        app.logger.error(f'Error in player route for video {video_name}: {str(e)}')
        return render_template("error.html", error="An unexpected error occurred"), 500

@app.route("/manifest/<video_name>/manifest.mpd")
def serve_manifest(video_name):
    try:
        app.logger.debug(f'Serving manifest for video: {video_name}')
        # Sanitize video name
        if '..' in video_name or '/' in video_name:
            app.logger.warning(f'Attempted directory traversal in manifest route: {video_name}')
            return "Invalid video name", 400
            
        manifest_path = os.path.join(MEDIA_DIR, video_name, "manifest.mpd")
        if not os.path.exists(manifest_path):
            app.logger.warning(f'Manifest file not found: {manifest_path}')
            return "Manifest not found", 404
        
        # Read and cache the manifest content instead of the file handle
        with open(manifest_path, 'r') as f:
            manifest_content = f.read()
            
        response = make_response(manifest_content)
        response.headers['Content-Type'] = 'application/dash+xml'
        response.headers['Cache-Control'] = 'public, max-age=60'
        return response
    except Exception as e:
        app.logger.error(f'Error serving manifest for {video_name}: {str(e)}')
        return "Internal server error", 500

# Add new route for serving video segments
@app.route("/manifest/<video_name>/<path:filename>")
def serve_video_segment(video_name, filename):
    try:
        # Sanitize inputs
        if '..' in video_name or '..' in filename:
            app.logger.warning(f'Attempted directory traversal - video: {video_name}, file: {filename}')
            return "Invalid path", 400
            
        # Verify file exists
        file_path = os.path.join(MEDIA_DIR, video_name, filename)
        if not os.path.exists(file_path):
            app.logger.warning(f'Video segment not found: {file_path}')
            return "Segment not found", 404
        
        # Read and serve the file content
        with open(file_path, 'rb') as f:
            content = f.read()
            
        response = make_response(content)
        
        # Set appropriate content type based on file extension
        if filename.endswith('.mp4'):
            response.headers['Content-Type'] = 'video/mp4'
        elif filename.endswith('.m4s'):
            response.headers['Content-Type'] = 'video/iso.segment'
        
        response.headers['Cache-Control'] = 'public, max-age=3600'
        return response
        
    except Exception as e:
        app.logger.error(f'Error serving video segment - video: {video_name}, file: {filename}: {str(e)}')
        return "Internal server error", 500

# Socket.IO event handlers
@socketio.on('connect')
def handle_connect():
    app.logger.info(f'New client connected: {request.sid}')
    # Send current playback state from Redis to new client
    emit('currentPlayback', get_playback_state())

@socketio.on('disconnect')
def handle_disconnect():
    app.logger.info(f'Client disconnected: {request.sid}')

@socketio.on('playbackCommand')
def handle_playback_command(data):
    # Only allow owner to control playback
    if not current_user.is_authenticated:
        app.logger.warning(f'Unauthorized playback command from {request.sid}')
        return
        
    # Update Redis playback state
    current_state = get_playback_state()
    current_state['time'] = data['time']
    if data['action'] == 'PLAY':
        current_state['status'] = 'PLAYING'
        app.logger.info(f'Owner started playback at time: {data["time"]}')
    elif data['action'] == 'PAUSE':
        current_state['status'] = 'PAUSED'
        app.logger.info(f'Owner paused playback at time: {data["time"]}')
    
    update_playback_state(current_state)
    
    # Broadcast to all other clients
    emit('playbackCommand', data, broadcast=True, include_self=False)
    app.logger.debug(f'Broadcasted playback command to all clients')

@socketio.on('timeUpdate')
def handle_time_update(time):
    if current_user.is_authenticated:  # Only owner can update time
        current_state = get_playback_state()
        current_state['time'] = time
        update_playback_state(current_state)
        app.logger.debug(f'Updated playback time to: {time}')

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    app.logger.warning(f'404 error: {request.url}')
    return render_template('error.html', error="Page not found"), 404

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f'500 error: {str(error)}')
    return render_template('error.html', error="An internal error occurred"), 500

if __name__ == "__main__":
    app.logger.info('Starting application server')
    socketio.run(app, host="0.0.0.0", port=8080, debug=True)
