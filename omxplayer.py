from pyomxplayer import OMXPlayer
import json
from time import sleep
from pprint import pprint
import threading
import zmq
import random
import sys
import time

if len(sys.argv) > 1:
    playerID =  int(sys.argv[1])
else:
    raise RuntimeError("specify player id: omxplayer.py [id]")

player = False
playerstatus = "standby"
exitnow = False
def playerHandler():
    global playerID
    context = zmq.Context()

    work_receiver = context.socket(zmq.SUB)
    port = 5501
    work_receiver.connect("tcp://192.168.1.233:5501")

    #poller = zmq.Poller()
    #poller.register(work_receiver, zmq.POLLIN)
    work_receiver.setsockopt(zmq.SUBSCRIBE, "1")
    work_receiver.setsockopt(zmq.SUBSCRIBE, "2")
    #work_receiver.setsockopt(zmq.SUBSCRIBE, str(playerID))

    while not exitnow:
        print "listen here"
        string = work_receiver.recv()
        print string
        topic, messagedata = string.split(" ", 1)
        if int(topic) == playerID:
            doCommand(messagedata)
        #socks = dict(poller.poll(1000))
        #if socks:
                #if socks.get(work_receiver) == zmq.POLLIN:
        sleep(1)


def doCommand(cmdstr):
    try:
        cmd, messagedata = cmdstr.split(" ", 1)
    except:
        cmd = cmdstr
    if cmd == "reset":
        playerReset()
    elif cmd == "queue":
        args = json.loads(messagedata)
        playFile(args)
    elif cmd == "unpause":
        playerUnpause()

def playerReset():
    global playerstatus
    if player:
        player.stop()
    playerstatus = "reset"

def playFile(args):
    global player
    player = OMXPlayer(args["file"], args["args"])
    # The player will initially be paused
    if args.has_key("mute") and args["mute"]:
        player.toggle_mute()

def playerUnpause():
    global player
    print "palyerUnpause()"
    if player.__dict__["paused"]:
        player.toggle_pause()

#player.toggle_mute()
#player.toggle_mute(.1)
#player.toggle_mute(.5)

port = "5556"
context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("tcp://*:%s" % port)



def sendUpdate(messagedata):
    global playerID
    print "%d %s" % (playerID, messagedata)
    socket.send("%d %s" % (playerID, messagedata))

t = threading.Thread(target=playerHandler)
t.start()

try:
    while True:
        if not player:
            sendUpdate(json.dumps({"player_status": playerstatus}))
        else:
            messagedata = json.dumps({
		"audio": player.__dict__['audio'],
		"video": player.__dict__['video'],
		"current_volume": player.__dict__['current_volume'],
		"duration": player.__dict__['duration'],
		"media_file": player.__dict__['media_file'],
		"paused": player.__dict__['paused'],
		"position": player.__dict__['position'],
		"title": player.__dict__['title'],
                "player_running": player.is_running(),
                "player_status": "running",
		})
            sendUpdate(messagedata)
        sleep(1)
except KeyboardInterrupt:
    exitnow = True
    playerReset()

