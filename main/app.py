import configparser
from flask import Flask, jsonify, render_template, send_from_directory, url_for
from flask_socketio import SocketIO, emit
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

config = configparser.ConfigParser()
config.read("../config.ini")

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY')  # Load secret key from environment
socketio = SocketIO(app)

# Store current playback state in memory
current_playback = {
    "status": "PAUSED",
    "time": 0
}

# Paths
MEDIA_DIR = config["DEFAULT"]["MEDIA_DIR"]
RUN_DIR = config["DEFAULT"]["RUN_DIR"]

@app.route("/")
def list_videos():
    # Prepare a list of directories and their states
    video_states = []

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

    # Render the state in the web interface
    return render_template("index.html", videos=video_states)

@app.route("/player/<video_name>")
def player(video_name):
    # Verify the manifest exists
    manifest_path = os.path.join(MEDIA_DIR, video_name, "manifest.mpd")
    if not os.path.exists(manifest_path):
        return "Video not ready", 404
        
    # Generate the manifest URL
    manifest_url = url_for('serve_manifest', video_name=video_name)
    return render_template("player.html", manifest_url=manifest_url, video_name=video_name)

@app.route("/manifest/<video_name>/manifest.mpd")
def serve_manifest(video_name):
    return send_from_directory(os.path.join(MEDIA_DIR, video_name), "manifest.mpd")

# Socket.IO event handlers
@socketio.on('connect')
def handle_connect():
    # Send current playback state to new client
    emit('currentPlayback', current_playback)

@socketio.on('playbackCommand')
def handle_playback_command(data):
    # Update server's playback state
    current_playback['time'] = data['time']
    if data['action'] == 'PLAY':
        current_playback['status'] = 'PLAYING'
    elif data['action'] == 'PAUSE':
        current_playback['status'] = 'PAUSED'
    
    # Broadcast to all other clients
    emit('playbackCommand', data, broadcast=True, include_self=False)

@socketio.on('timeUpdate')
def handle_time_update(time):
    current_playback['time'] = time

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8080, debug=True)
