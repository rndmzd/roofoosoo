#!/bin/bash

# Set the correct permissions for the files
chown -Rc ubuntu:www-data ./
sudo chown debian-deluged:debian-deluged ./main/transcoding/transcode.sh
sudo chmod a+x ./main/transcoding/transcode.sh