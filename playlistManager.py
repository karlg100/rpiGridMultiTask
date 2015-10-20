import sys
from time import sleep
import zmq
import os
import threading
import json
import datetime
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
    socket.connect ("tcp://192.168.1.236:%s" % port)

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
                   "file": "/home/pi/videos/Jack-O-Lantern\ -\ Songs\ -\ Window/Jack-O-Lantern\ -\ Songs\ -\ Window/JOLJ_PumpkinSong_Trio_Win_BG_H.mp4",
                   "args": "--no-osd",
		   "endtime": 15,
		},
	    2: {			# player 2
                   "file": "/home/pi/videos/WH\ -\ Spell2\ -\ Wicked\ Brew\ -\ Hollusion+TV+Window/WH_Spell\ 2_WickedBrew_Holl_H.mp4",
                   "args": "--loop --no-osd",
                   "vol": -75,
		},
	   },
        2: {  			# playlist 2
           "master": 2,
	    1: {			# player 1
                   "file": "/home/pi/videos/Jack-O-Lantern\ -\ Funny\ Faces\ -\ Window/Jack-O-Lantern\ -\ Funny\ Faces\ -\ Window/JOLJ_FunnyFaces_Trio_Win_BG_H.mp4",
                   "args": "--loop --no-osd",
                   "vol": -75,
		},
	    2: {			# player 2
                   "file": "/home/pi/videos/WH\ -\ Spell2\ -\ Wicked\ Brew\ -\ Hollusion+TV+Window/WH_Spell\ 2_WickedBrew_Holl_H.mp4",
                   "args": "--no-osd",
		   "endtime": 15,
		},
	   },
        3: {  			# playlist 3
            "master": 1,
	    1: {			# player 1
                   "file": "/home/pi/videos/Jack-O-Lantern\ -\ Stories\ -\ Window/Jack-O-Lantern\ -\ Stories\ -\ Window/JOLJ_TwasTheNight_Trio_Win_BG_H.mp4",
                   "args": "--no-osd",
		   "endtime": 15,
		},
	    2: {			# player 2
                   "file": "/home/pi/videos/WH\ -\ Spell2\ -\ Wicked\ Brew\ -\ Hollusion+TV+Window/WH_Spell\ 2_WickedBrew_Holl_H.mp4",
                   "args": "--loop --no-osd",
                   "vol": -75,
		},
	   },
	}


def timeNow():
    return datetime.datetime.strftime(datetime.datetime.now(), '%H:%M:%S')

def nextPlayList():
    global currentplaylist
    global playlist
    global messagelog
    currentplaylist += 1
    if len(playlist) < currentplaylist:
        messagelog.append("%s : at last playlist %d, starting over at 1" % (timeNow(), currentplaylist))
        currentplaylist = 1

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
            messagelog.append("%s : resetting %d" % (timeNow(), player))
            socket.send("%d reset" % player)
        elif videoStats[player]["player_status"] == "reset":
            #pprint(playlist[currentplaylist][int(player)])
            messagelog.append("%s : queuing %d with %s" % (timeNow(), player, json.dumps(playlist[currentplaylist][int(player)])))
            socket.send("%d queue %s" % (player, json.dumps(playlist[currentplaylist][int(player)])))
        elif master == int(player) and \
            videoStats[player]["player_status"] == "running" and \
            videoStats[player]["paused"]:
                messagelog.append("%s : unpausing %d" % (timeNow(), player))
                socket.send("%d unpause" % player)
        elif master != int(player) and \
	    videoStats[master].has_key("paused") and \
            videoStats[master]["paused"] == False and \
            videoStats[player].has_key("paused") and \
            videoStats[player]["paused"]:
                messagelog.append("%s : unpausing %d" % (timeNow(), player))
                socket.send("%d unpause" % player)
        elif master == int(player) and \
            videoStats[player].has_key("player_running") and \
            videoStats[player]["player_running"] == False:
                messagelog.append("%s : Master is done, resetting all players, next playlist" % timeNow())
                resetAllPlayers(socket)
                nextPlayList()
	elif master == player and \
	    videoStats[master].has_key("duration") and \
	    playlist[currentplaylist][master].has_key("endtime") and \
	    videoStats[master]["position"] > playlist[currentplaylist][master]["endtime"]:
                messagelog.append("%s : Master reached endtime, resetting all players, next playlist" % timeNow())
                resetAllPlayers(socket)
                nextPlayList()
	#elif master != player and \
	    #videoStats[master].has_key("duration") and \
	    #videoStats[master]["duration"] - videoStats[master]["position"] < 10:
                #messagelog.append("%s : fade to black %d" % (timeNow(), player))
                #socket.send("%d fadeblack" % player)
    

def resetAllPlayers(socket):
    global videoStats
    global messagelog
    messagelog.append("%s : resetting all players" % timeNow())
    for player in videoStats:
        messagelog.append("%s :   resetting %d" % (timeNow(), player))
        socket.send("%d reset" % player)
    sleep(1)
    messagelog.append("%s :   resetAllPlayers exit" % (timeNow()))
    

def commandControl():
    global videoStats
    global loop
    global cmd_send
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
        print "current playlist : %d" % currentplaylist
        print "master player : %d" % playlist[currentplaylist]["master"]
        pprint(videoStats)
        sleep(1)
except KeyboardInterrupt:
    print "exiting"
    loop = False
    resetAllPlayers(cmd_send)
    #t.stop()

