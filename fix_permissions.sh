#!/bin/bash

# Set the correct permissions for the files
chown -Rc ubuntu:www-data ./
chown debian-deluged:debian-deluged ./main/transcoding/transcode.sh