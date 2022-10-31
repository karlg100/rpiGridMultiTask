from pyomxplayer import OMXPlayer
import json
from time import sleep
from pprint import pprint
import threading
#import zmq
import random
import sys
import time
import paho.mqtt.client as mqtt

if len(sys.argv) > 1:
    playerID =  int(sys.argv[1])
else:
    raise RuntimeError("specify player id: omxplayer.py [id]")

player = False
playerstatus = "standby"
exitnow = False

playerInfo = {}

def on_message(client, userdata, msg):
    global playerID
    global playerInfo
    #string = work_receiver.recv()
    #print string
    junk, player, topic = msg.topic.split("/", 2)
    if topic == "command":
    	doCommand(msg.payload)
    else:
    	playerInfo[topic] = msg.payload


def doCommand(cmdstr):
    try:
        cmd, messagedata = cmdstr.split(" ", 1)
    except:
        cmd = cmdstr
    if cmd == "reset":
        playerReset()
    elif cmd == "queue":
        playFile()
    elif cmd == "unpause":
        playerUnpause()
    print "doCommand exit"

def playerReset():
    global playerstatus
    global player
    global playerInfo
    if player:
        player.stop()
    playerstatus = "reset"
    playerInfo = {}
    player = False

def playFile():
    global player
    global playerInfo
    global playerstatus

    print playerInfo

    if not playerInfo.has_key("file") or not playerInfo.has_key("args"):
        print "not all arguments loaded!"
        return
    if player:
        print "player already launched!"
        return
    print "launching OMXPlayer"
    print playerInfo
    player = OMXPlayer(playerInfo["file"], playerInfo["args"])
    # The player will initially be paused
    if playerInfo.has_key("mute") and playerInfo["mute"] == "True":
        print "we need to mute"
        player.toggle_mute()
    if playerInfo.has_key("vol"):
        print "setting volume to %d" % int(playerInfo["vol"])
        player.set_vol(int(playerInfo["vol"]))
    playerstatus = "queued"
    print "playFile exit"

def playerUnpause():
    global player
    print "palyerUnpause()"
    if player.__dict__.has_key("paused") and player.__dict__["paused"] == True:
        player.toggle_pause()

#player.toggle_mute()
#player.toggle_mute(.1)
#player.toggle_mute(.5)

#server = "192.168.1.234"
#server = "192.168.1.166"
server = "192.168.1.18"
port = "1883"
mqttc = mqtt.Client("omxplayer %d" % playerID)
mqttc.connect(server, port)
mqttc.loop_start()

mqttc.subscribe("player/%d/#" % playerID)
mqttc.on_message = on_message

def sendUpdate(messagedata, base = None):
    global playerID
    if base is None:
        base = "player/%d" % (playerID)
    for key in messagedata:
        #print type(messagedata[key])
	if type(messagedata[key]) is dict or type(messagedata[key]) is list:
    	    print "%s/%s = %s" % (base, key, messagedata[key])
    	    mqttc.publish("%s/%s" % (base, key), json.dumps(messagedata[key]))
	    #sendUpdate(messagedata[key], "%s/%s" % (base, key))
        else:
    	    print "%s/%s = %s" % (base, key, messagedata[key])
    	    mqttc.publish("%s/%s" % (base, key), "%s" % messagedata[key])

#t = threading.Thread(target=playerHandler)
#t.start()

try:
    while True:
        if not player:
            sendUpdate({"player_status": playerstatus})
        else:
	    messagedata = {}
            if player.__dict__.has_key("audio"): messagedata["audio"] = player.__dict__['audio']
            if player.__dict__.has_key("video"): messagedata["video"] = player.__dict__['video'],
            if player.__dict__.has_key("current_volume"): messagedata["current_volume"] = player.__dict__['current_volume']
            if player.__dict__.has_key("duration"): messagedata["duration"] = player.__dict__['duration']
            if player.__dict__.has_key("media_file"): messagedata["media_file"] = player.__dict__['media_file']
            if player.__dict__.has_key("paused"): messagedata["paused"] = player.__dict__['paused']
            if player.__dict__.has_key("position"): messagedata["position"] = player.__dict__['position']
            if player.__dict__.has_key("title"): messagedata["title"] = player.__dict__['title']
            messagedata["player_running"] = player.is_running(),
            messagedata["player_status"] = "running"
            sendUpdate(messagedata)
        sleep(.25)
        #sleep(.1)
except KeyboardInterrupt:
    exitnow = True
    mqttc.publish("player/%d/player_status" % playerID, False)
    mqttc.loop_stop(force=False)
    mqttc.disconnect()
    playerReset()

