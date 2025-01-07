import configparser
from flask import Flask, jsonify, render_template
import os

config = configparser.ConfigParser()
config.read("config.ini")

app = Flask(__name__)

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

            video_states.append({"name": dirname, "state": state})

    # Render the state in the web interface
    return render_template("index.html", videos=video_states)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
