import sys
from time import sleep
import zmq
import os
import threading
import json
from pprint import pprint

videoStats = {  1: {"player_status": False},
                2: {"player_status": False},
             }
loop = True

messagelog = []

def subCollector():
    global loop
    global videoStats
    print 'Launching listner'

    port = "5556"
    # Socket to talk to server
    context = zmq.Context()
    socket = context.socket(zmq.SUB)

    print "Collecting updates from video players..."
    socket.connect ("tcp://192.168.1.233:%s" % port)
    socket.connect ("tcp://192.168.1.235:%s" % port)

    # add more topics if you plan to have more video clients
    socket.setsockopt(zmq.SUBSCRIBE, "1")
    socket.setsockopt(zmq.SUBSCRIBE, "2")

    #for update_nbr in range (5):
    while loop:
        string = socket.recv(1000)
        topic, messagedata = string.split(" ", 1)
	videoStats[int(topic)] = json.loads(messagedata)
    return

currentplaylist=1
playlist = { 
        1: {  			# playlist 1
            "master": 1,
	    1: {			# player 1
                   "file": "/home/pi/test2.mp4",
                   "args": "--no-osd",
		},
	    2: {			# player 2
                   "file": "/home/pi/test.mp4",
                   "args": "--loop --no-osd",
                   "mute": True,
		},
	   },
	}


def checkPlayerStatus(socket):
    global videoStats
    global currentplaylist
    global playlist
    global messagelog
    master = playlist[currentplaylist]["master"]
    for player in videoStats:
        #pprint(videoStats[player])
        #socket.send("%d checking status" % player)
        if videoStats[player]["player_status"] == "standby":
            messagelog.append("resetting %d" % player)
            socket.send("%d reset" % player)
        elif videoStats[player]["player_status"] == "reset":
            #pprint(playlist[currentplaylist][int(player)])
            messagelog.append("queuing %d with %s" % (player, json.dumps(playlist[currentplaylist][int(player)])))
            socket.send("%d queue %s" % (player, json.dumps(playlist[currentplaylist][int(player)])))
        elif master == int(player) and \
            videoStats[player]["player_status"] == "running" and \
            videoStats[player]["paused"]:
                messagelog.append("unpausing %d" % player)
                socket.send("%d unpause" % player)
        elif master != int(player) and \
	    videoStats[master].has_key("paused") and \
            videoStats[master]["paused"] == False and \
            videoStats[player].has_key("paused") and \
            videoStats[player]["paused"]:
                messagelog.append("unpausing %d" % player)
                socket.send("%d unpause" % player)
        elif master == int(player) and \
            videoStats[player].has_key("player_running") and \
            videoStats[player]["player_running"] == False:
                resetAllPlayers(socket)
    

def resetAllPlayers(socket):
    global videoStats
    #messagelog.append( "resetting all players"
    for player in videoStats:
        messagelog.append("resetting %d" % player)
        socket.send("%d reset" % player)
    #sleep(1)
    #print "resetAllPlayers exit"
    

def commandControl():
    global videoStats
    global loop
    context = zmq.Context()
    cmd_send = context.socket(zmq.PUB)
    cmd_send.bind("tcp://*:5501")

    # init players
    while loop:
        checkPlayerStatus(cmd_send)
        sleep(.2)
            
def printlog():
    global messagelog
    while len(messagelog) > 10:
        del(messagelog[0])

    #for line in range (25):
    pprint(messagelog)


t = threading.Thread(target=subCollector)
t.start()
c = threading.Thread(target=commandControl)
c.start()

sleep(1)
try:
    while True:
        os.system('clear')
        printlog()
        pprint(videoStats)
        sleep(1)
except KeyboardInterrupt:
    print "exiting"
    loop = False
    t.stop()

