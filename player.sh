#!/bin/bash

sudo sh -c "clear > /dev/tty1"
python omxplayer-mqtt.py $*
