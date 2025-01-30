#!/bin/bash

# Variables passed by Deluge
torrentid=$1
torrentname=$2
torrentpath=$3

# Log file for debugging
LOG_FILE="/tmp/execute_script.log"

# Run file for the current torrent
RUN_DIR="/tmp/transcoding"
mkdir -p "$RUN_DIR"
RUN_FILE="${RUN_DIR}/transcode_${torrentid}.run"

# Create the run file with metadata
echo "torrentid=$torrentid" > "$RUN_FILE"
echo "torrentname=$torrentname" >> "$RUN_FILE"
echo "start_time=$(date)" >> "$RUN_FILE"

trap 'rm -f "$RUN_FILE"' EXIT

echo "Torrent Completed: $torrentname" >> "$LOG_FILE"
echo "Path: $torrentpath" >> "$LOG_FILE"

# Check if torrentname is a video file based on its extension
if [[ "$torrentname" =~ \.(mp4|mkv|avi|mov|flv|wmv)$ ]]; then
    largest_file="$torrentpath/$torrentname"
    echo "Torrentname is a video file: $largest_file" >> "$LOG_FILE"
else
    # Append torrentname to torrentpath to form the full directory path
    video_dir="$torrentpath/$torrentname"

    if [[ ! -d "$video_dir" ]]; then
        echo "Directory $video_dir does not exist. Exiting." >> "$LOG_FILE"
        exit 1
    fi

    echo "Searching for video files in: $video_dir" >> "$LOG_FILE"

    # Find the largest video file in the directory
    #largest_file=$(find "$video_dir" -type f -exec du -b {} + | sort -n -r | awk '{print $2}' | grep -Ei '\.(mp4|mkv|avi|mov|flv|wmv)$' | head -n 1)
    largest_file=$(find "$video_dir" -type f -printf '%s %p\n' | sort -n -r | grep -Ei '\.(mp4|mkv|avi|mov|flv|wmv)$' | head -n 1 | cut -d' ' -f2-)

    if [[ -z "$largest_file" ]]; then
        echo "No video files found in $video_dir" >> "$LOG_FILE"
        exit 1
    fi

    echo "Largest Video File: $largest_file" >> "$LOG_FILE"
fi

# Find the .env file by searching up the directory tree
find_env_file() {
    local current_dir="$1"
    while [[ "$current_dir" != "/" ]]; do
        if [[ -f "$current_dir/main/.env" ]]; then
            echo "$current_dir"
            return 0
        fi
        current_dir="$(dirname "$current_dir")"
    done
    return 1
}

# Get the absolute path of the script's directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Find the root directory containing .env
ROOT_DIR=$(find_env_file "$SCRIPT_DIR")

if [[ -z "$ROOT_DIR" ]]; then
    echo "Error: Could not find .env file in parent directories" >> "$LOG_FILE"
    exit 1
fi

# Set output directory relative to the root directory
output_dir="$ROOT_DIR/main/media/${torrentname}"
mkdir -p "$output_dir"
mkdir -p "$output_dir/segments"

# Transcode to shared fMP4 segments for both DASH and HLS
echo "Starting FFmpeg transcoding for: $largest_file" >> "$LOG_FILE"

ffmpeg -i "$largest_file" \
    -filter_complex "[0:v]split=3[v1][v2][v3]; \
    [v1]scale=w=1920:h=1080[v1out]; \
    [v2]scale=w=1280:h=720[v2out]; \
    [v3]scale=w=854:h=480[v3out]" \
    -map "[v1out]" -c:v:0 libx264 -b:v:0 5000k -maxrate:v:0 5350k -bufsize:v:0 7500k -map 0:a -c:a aac -ar 48000 -b:a 192k \
    -map "[v2out]" -c:v:1 libx264 -b:v:1 3000k -maxrate:v:1 3210k -bufsize:v:1 4500k -map 0:a -c:a aac -ar 48000 -b:a 128k \
    -map "[v3out]" -c:v:2 libx264 -b:v:2 1000k -maxrate:v:2 1070k -bufsize:v:2 1500k -map 0:a -c:a aac -ar 48000 -b:a 96k \
    -init_seg_name "init_\$RepresentationID\$.m4s" \
    -media_seg_name "chunk_\$RepresentationID\$_\$Number%05d\$.m4s" \
    -use_template 1 -use_timeline 1 \
    -seg_duration 8 \
    -adaptation_sets "id=0,streams=v id=1,streams=a" \
    -f dash "$output_dir/manifest.mpd" \
    -hls_segment_type fmp4 \
    -hls_time 8 \
    -hls_playlist_type vod \
    -master_pl_name master.m3u8 \
    -var_stream_map "v:0,a:0 v:1,a:1 v:2,a:2" \
    -hls_fmp4_init_filename "init_\$RepresentationID\$.m4s" \
    -hls_segment_filename "$output_dir/segments/chunk_\$RepresentationID\$_%05d.m4s" \
    "$output_dir/stream_%v.m3u8" >> "$LOG_FILE" 2>&1

# Check the exit status of FFmpeg
if [[ $? -eq 0 ]]; then
    echo "Transcoding completed successfully. DASH and HLS outputs at: $output_dir" >> "$LOG_FILE"
    
    # Create symbolic links for HLS segments to DASH segments
    echo "Creating symbolic links for shared segments..." >> "$LOG_FILE"
    cd "$output_dir"
    for f in segments/*.m4s; do
        ln -sf "$f" "hls/${f##*/}" 2>> "$LOG_FILE"
    done
else
    echo "Error during transcoding. Check the log file for details." >> "$LOG_FILE"
    exit 1
fi

echo "Script finished successfully." >> "$LOG_FILE"

exit 0
