from pyomxplayer import OMXPlayer
import json
from time import sleep
from pprint import pprint


import zmq
import random
import sys
import time

port = "5556"

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("tcp://*:%s" % port)

if len(sys.argv) > 1:
    playerID =  int(sys.argv[1])
else:
    raise RuntimeError("specify player id: omxplayer.py [id]")


def sendUpdate(messagedata):
    global playerID
    print "%d %s" % (playerID, messagedata)
    socket.send("%d %s" % (playerID, messagedata))


player = OMXPlayer('/home/pi/test2.mp4', '--no-osd --loop')

# The player will initially be paused

player.toggle_mute()
player.toggle_pause()
#player.toggle_pause()
#player.toggle_pause()
#player.toggle_mute()
#player.toggle_mute()
#player.toggle_mute(.1)
#player.toggle_mute(.5)

# Kill the `omxplayer` process gracefully.
try:
    while True:
        messagedata = json.dumps({
		"audio": player.__dict__['audio'],
		"video": player.__dict__['video'],
		"current_volume": player.__dict__['current_volume'],
		"duration": player.__dict__['duration'],
		"media_file": player.__dict__['media_file'],
		"paused": player.__dict__['paused'],
		"position": player.__dict__['position'],
		"title": player.__dict__['title'],
		})
        sendUpdate(messagedata)
        sleep(1)
except KeyboardInterrupt:
    player.stop()

#socket_sub.setsockopt(zmq.SUBSCRIBE, 1)
#
#poller = zmq.Poller()
#    poller.register(socket_pull, zmq.POLLIN)
#    poller.register(socket_sub, zmq.POLLIN)
