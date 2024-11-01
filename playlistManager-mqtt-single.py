import sys
from time import sleep
import os
import threading
import json
import datetime
from pprint import pprint
import paho.mqtt.client as mqtt

#server = "192.168.1.234"
#server = "192.168.1.166"
server = "192.168.1.18"
port = "1883"

videoStats = {  1: {"player_status": False},
                2: {"player_status": False},
             }
loop = True

messagelog = []

def on_message(client, userdata, msg):
        global videoStats
	#print "Topic: ", msg.topic+'\nMessage: '+str(msg.payload)
        junk, player, key = msg.topic.split("/", 3)
	#print "%s/%s = %s" % (player, key, msg.payload)
	try:
		videoStats[int(player)][key] = json.loads(msg.payload)
	except:
		videoStats[int(player)][key] = msg.payload

print 'Launching mqtt client'

# Socket to talk to server
mqttc = mqtt.Client("mgr")
mqttc.connect(server, port)

# add more topics if you plan to have more video clients
mqttc.subscribe("player/#")

mqttc.on_message = on_message

mqttc.loop_start()
#mqttc.loop_forever()

if len(sys.argv) > 1:
    currentplaylist = int(sys.argv[1])
else:
    currentplaylist=1

playlist = { 
      1: {  			# playlist 1
        "master": 1,
	        1: {			# player 1
            "file": "/home/pi/videos/Jack-O-Lantern\ -\ Songs\ -\ Window/Jack-O-Lantern\ -\ Songs\ -\ Window/JOLJ_PumpkinSong_Trio_Win_BG_H.mp4",
            "args": "-o local --no-osd",
            "vol": 15,
		        #"endtime": 15,
		        "endtime": 100,
		      },
        "front_lights": {
		        "r": 114,
		        "g": 40,
		        "b": 0,
		      },
	        "graveyard": {
		        "r": 0,
		        "g": 114,
		        "b": 0,
		      },
	   },
     2: {  			# playlist 2
       "master": 1,
#1       1: {			# player 1
#           "file": "/home/pi/videos/Jack-O-Lantern\ -\ Funny\ Faces\ -\ Window/Jack-O-Lantern\ -\ Funny\ Faces\ -\ Window/JOLJ_FunnyFaces_Trio_Win_BG_H.mp4",
#           "args": "-o local --loop --no-osd",
#		       "wait": 8,
#           "vol": -18,
#		     },
	       1: {			# player 2
           "file": "/home/pi/videos/WH\ -\ Spell2\ -\ Wicked\ Brew\ -\ Hollusion+TV+Window/WH_Spell\ 2_WickedBrew_Holl_H.mp4",
           "args": "-o local --no-osd",
		       #"endtime": 15,
           "vol": 15,
		     },
	       "front_lights": {
		       "r": 0,
		       "g": 0,
		       "b": 89,
		     },
	       "graveyard": {
		       "r": 49,
		       "g": 0,
		       "b": 89,
		     },
	   },
     3: {  			# playlist 3
       "master": 1,
	       1: {			# player 1
           "file": "/home/pi/videos/Jack-O-Lantern\ -\ Stories\ -\ Window/Jack-O-Lantern\ -\ Stories\ -\ Window/JOLJ_TwasTheNight_Trio_Win_BG_H.mp4",
           "args": "-o local --no-osd",
		       #"endtime": 15,
		     },
#	       2: {			# player 2
#           "file": "/home/pi/videos/Bone\ Chillers\ -\ Jittery\ Bones/Wall/BC_JitteryBones_Wall_H.mp4",
#           #"file": "/home/pi/videos/WH\ -\ Spell2\ -\ Wicked\ Brew\ -\ Hollusion+TV+Window/WH_Spell\ 2_WickedBrew_Holl_H.mp4",
#		       "wait": 20,
#           "args": "-o local --no-osd",
#           #"vol": -7,
#		     },
	       "front_lights": {
		       "r": 255,
		       "g": 165,
		       "b": 0,
		     },
	       "graveyard": {
		       "r": 255,
		       "g": 165,
		       "b": 0,
		     },
	   },
     4: {  			# playlist 4
       "master": 1,
	     1: {			# player 2
         "file": "/home/pi/videos/WH\ -\ Song2\ -\ Cat\ Crow\ Canzonet\ -\ Hollusion-TV-Window/WH_Song\ 2_CatCrow_Holl_H.mp4",
         "args": "-o local --no-osd",
		     #"endtime": 15,
         #"vol": -7,
		   },
	     "front_lights": {
		     "r": 64,
		     "g": 64,
		     "b": 64,
		   },
	     "graveyard": {
		     "r": 49,
		     "g": 0,
		     "b": 89,
		   },
	   },
     5: {  			# playlist 5
       "master": 1,
	     1: {			# player 1
         "file": "/home/pi/videos/Tricks\ and\ Treats-Frankenstein.mp4",
         "args": "--no-osd -o local -l 37",
         #"vol": -7,
		   },
#	     2: {			# player 2
#         "file": "/home/pi/videos/Phantasms-Rise\ Of\ The\ Wraiths.mp4",
#         "args": "-o local --no-osd",
#		     "wait": 40,
#		     #"endtime": 15,
#         "vol": -7,
#		   },
	     "front_lights": {
		     "r": 64,
		     "g": 64,
		     "b": 64,
		   },
	     "graveyard": {
		     "r": 0,
		     "g": 64,
		     "b": 0,
		   },
	   },
#     6: {  			# playlist 6
#       "master": 1,
#	     1: {			# player 1
#         "file": "/home/pi/videos/Thriller/thriller_video.mp4",
#         #"args": "--no-osd -o local -l 410",
#         "args": "--no-osd -o local -l 244",
#         #"vol": -7,
#		   },
#	     2: {			# player 2
#         "file": "/home/pi/videos/Thriller/thriller_anim.mp4",
#         "args": "-o local --no-osd",
#		     "wait": 420,
#		     "endtime": 225,
#         "vol": -75,
#		   },
#	     "front_lights": {
#		     "r": 34,
#		     "g": 0,
#		     "b": 0,
#		   },
#	     "graveyard": {
#		     "r": 64,
#		     "g": 0,
#		     "b": 64,
#		   },
#	   },
     7: {  			# playlist 7
       "master": 1,
	     1: {			# player 2
         "file": "/home/pi/videos/things_that_go_bump_in_the_night_halloween_exclusive.mp4",
         "args": "-o local --no-osd",
         #"vol": -75,
		   },
	     "front_lights": {
		     "r": 0,
		     "g": 24,
		     "b": 0,
		   },
	     "graveyard": {
		     "r": 64,
		     "g": 64,
		     "b": 64,
		   },
	   },
     8: {  			# playlist 8
       "master": 1,
	       1: {	
            "file": "/home/pi/videos/Bone\ Chillers\ -\ Numskulls/Wall/BC_Numskulls_Wall_H.mp4",
            "args": "-o local --no-osd",
            "vol": 15,
		      },
	     "front_lights": {
		     "r": 24,
		     "g": 24,
		     "b": 24,
		   },
	     "graveyard": {
		     "r": 64,
		     "g": 64,
		     "b": 64,
		   },
	   },
	   9: {  			# playlist 9
       "master": 1,
	     1: {			# player 1
         "file": "/home/pi/videos/Bone\ Chillers-Dancing\ Dead.mp4",
         "args": "-o local --no-osd",
         #"args": "--no-osd -o local -l 410",
         "vol": 15,
		   },
	     "front_lights": {
		     "r": 0,
		     "g": 0,
		     "b": 24,
		   },
	     "graveyard": {
		     "r": 64,
		     "g": 64,
		     "b": 64,
		   },
	   },
	   10: {  			# playlist 10
       "master": 1,
	     1: {			# player 1
         "file": "/home/pi/videos/silly_symphonies_the_skeleton_dance.mp4",
         "args": "-o local --no-osd",
         #"args": "--no-osd -o local -l 410",
         "vol": 15,
		   },
	     "front_lights": {
		     "r": 24,
		     "g": 24,
		     "b": 24,
		   },
	     "graveyard": {
		     "r": 64,
		     "g": 64,
		     "b": 64,
		   },
	   },
	   11: {  			# playlist 10
       "master": 1,
	     1: {			# player 1
         "file": "/home/pi/videos/tim_curry_in_the_worst_witch.mp4",
         "args": "-o local --no-osd",
         #"args": "--no-osd -o local -l 410",
         "vol": 0,
		   },
	     "front_lights": {
		     "r": 24,
		     "g": 0,
		     "b": 0,
		   },
	     "graveyard": {
		     "r": 64,
		     "g": 64,
		     "b": 64,
		   },
	   },
	   6: {  			# playlist 12
       "master": 1,
	     1: {			# player 1
         "file": "/home/pi/videos/TnT\ -\ Vampire\ Scenes\ -\ Window/TnT_BatsAndBrooms_Win_H.mp4",
         "args": "-o local --no-osd",
         #"args": "--no-osd -o local -l 410",
         "vol": 15,
		   },
	     "front_lights": {
		     "r": 24,
		     "g": 0,
		     "b": 24,
		   },
	     "graveyard": {
		     "r": 64,
		     "g": 64,
		     "b": 64,
		   },
	   },

	}


#	     1: {			# player 1
#         "file": "/home/pi/videos/Bone\ Chillers-Dancing\ Dead.mp4",
#         #"args": "--no-osd -o local -l 410",
#         "args": "--no-osd -o local -loop",
#         "vol": -75,
#		   },
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

def checkPlayerStatus():
    global videoStats
    global currentplaylist
    global playlist
    global messagelog
    global mqrttc
    master = playlist[currentplaylist]["master"]
    for player in videoStats:
        #pprint(videoStats[player])
        if videoStats[player]["player_status"] == "False":
	    videoStats[player] = False
        elif videoStats[player]["player_status"] == "standby":
            messagelog.append("%s : resetting %d" % (timeNow(), player))
	    mqttc.publish("player/%d/command" % player, "reset")
        elif videoStats[player]["player_status"] == "reset":
            #pprint(playlist[currentplaylist][int(player)])
            messagelog.append("%s : queuing %d with %s" % (timeNow(), player, json.dumps(playlist[currentplaylist][int(player)])))
	    for key in playlist[currentplaylist][int(player)]:
	    	mqttc.publish("player/%d/%s" % (player, key), playlist[currentplaylist][int(player)][key])
	    mqttc.publish("player/%d/command" % player, "queue")
        elif master == int(player) and \
            videoStats[player]["player_status"] == "running" and \
            videoStats[player]["paused"] == "True":
                messagelog.append("%s : unpausing %d" % (timeNow(), player))
	        mqttc.publish("player/%d/command" % player, "unpause")
	        mqttc.publish("front_lights/command", "on")
	        mqttc.publish("graveyard/command", "on")
	        mqttc.publish("front_lights/color/r", playlist[currentplaylist]["front_lights"]["r"])
	        mqttc.publish("front_lights/color/g", playlist[currentplaylist]["front_lights"]["g"])
	        mqttc.publish("front_lights/color/b", playlist[currentplaylist]["front_lights"]["b"])
	        mqttc.publish("graveyard/color/r", playlist[currentplaylist]["graveyard"]["r"])
	        mqttc.publish("graveyard/color/g", playlist[currentplaylist]["graveyard"]["g"])
	        mqttc.publish("graveyard/color/b", playlist[currentplaylist]["graveyard"]["b"])
	        mqttc.publish("front_lights/command", "go")
	        mqttc.publish("graveyard/command", "go")
        elif master != int(player) and \
	    videoStats[master].has_key("paused") and videoStats[master]["paused"] == "False" and \
            videoStats[player].has_key("paused") and videoStats[player]["paused"] == "True" and \
	    (not playlist[currentplaylist][player].has_key("wait") or playlist[currentplaylist][player]["wait"] < videoStats[master]["position"]):
                messagelog.append("%s : unpausing %d" % (timeNow(), player))
	        mqttc.publish("player/%d/command" % player, "unpause")
        elif master == int(player) and \
            videoStats[player].has_key("player_running") and \
            videoStats[player]["player_running"] == "False":
                messagelog.append("%s : Master is done, resetting all players, next playlist" % timeNow())
                resetAllPlayers()
                nextPlayList()
	elif master == player and \
	    videoStats[master].has_key("duration") and \
	    playlist[currentplaylist][master].has_key("endtime") and \
	    videoStats[master]["position"] >= playlist[currentplaylist][master]["endtime"]:
                messagelog.append("%s : Master reached endtime, resetting all players, next playlist" % timeNow())
                resetAllPlayers()
                nextPlayList()
	#elif master != player and \
	    #videoStats[master].has_key("duration") and \
	    #videoStats[master]["duration"] - videoStats[master]["position"] < 10:
                #messagelog.append("%s : fade to black %d" % (timeNow(), player))
                #socket.send("%d fadeblack" % player)


def resetAllPlayers():
    global videoStats
    global messagelog
    global mqttc
    messagelog.append("%s : resetting all players" % timeNow())
    for player in videoStats:
        messagelog.append("%s :   resetting %d" % (timeNow(), player))
	mqttc.publish("player/%d/command" % player, "reset")
    sleep(1)
    messagelog.append("%s :   resetAllPlayers exit" % (timeNow()))
    

def commandControl():
    global videoStats
    global loop
    global cmd_send

    # init players
    while loop:
        checkPlayerStatus()
        sleep(.2)
            
def printlog():
    global messagelog
    while len(messagelog) > 10:
        del(messagelog[0])

    #for line in range (25):
    pprint(messagelog)


#t = threading.Thread(target=subCollector)
#t.daemon = True
#t.start()
c = threading.Thread(target=commandControl)
c.daemon = True
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
    mqttc.disconect()
    mqttc.stop()
    #t.stop()

