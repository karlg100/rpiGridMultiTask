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
#server = "192.168.1.18"
server = "192.168.1.243"
port = "1883"

videoStats = {  1: {"player_status": False},
                2: {"player_status": False},
             }
loop = True

waitForReset = False

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
mqttc.username_pw_set(username='home-pi', password='passwd')
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
            "args": "-o local --no-osd --orientation 180",
            "vol": 5,
		        #"endtime": 15,
		        "endtime": 100,
		      },
	        2: {			# player 2
            "file": "/home/pi/videos/Bone\ Chillers\ -\ Numskulls/Wall/BC_Numskulls_Wall_H.mp4",
            "args": "-o local --no-osd",
		        "wait": 15,
            "vol": -7,
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
       "master": 2,
	       1: {			# player 1
           "file": "/home/pi/videos/Jack-O-Lantern\ -\ Funny\ Faces\ -\ Window/Jack-O-Lantern\ -\ Funny\ Faces\ -\ Window/JOLJ_FunnyFaces_Trio_Win_BG_H.mp4",
           "args": "-o local --loop --no-osd --orientation 180",
		       "wait": 8,
           "vol": -18,
		     },
	       2: {			# player 2
           "file": "/home/pi/videos/WH\ -\ Spell2\ -\ Wicked\ Brew\ -\ Hollusion+TV+Window/WH_Spell\ 2_WickedBrew_Holl_H.mp4",
           "args": "-o local --no-osd",
		       #"endtime": 15,
           "vol": 10,
		     },
	       "front_lights": {
		       "r": 0,
		       "g": 0,
		       "b": 190,
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
           "args": "-o local --no-osd --orientation 180",
           "vol": 0,
		       #"endtime": 15,
		     },
	       2: {			# player 2
           "file": "/home/pi/videos/Bone\ Chillers\ -\ Jittery\ Bones/Wall/BC_JitteryBones_Wall_H.mp4",
           #"file": "/home/pi/videos/WH\ -\ Spell2\ -\ Wicked\ Brew\ -\ Hollusion+TV+Window/WH_Spell\ 2_WickedBrew_Holl_H.mp4",
		       "wait": 20,
           "args": "-o local --no-osd",
           "vol": -7,
		     },
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
       "master": 2,
	     1: {			# player 1
         "file": "/home/pi/videos/TnT\ -\ Vampire\ Scenes\ -\ Window/TnT_BatsAndBrooms_Win_H.mp4",
         "args": "-o local --no-osd --orientation 180",
		     "wait": 20,
         "vol": -7,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/WH\ -\ Song2\ -\ Cat\ Crow\ Canzonet\ -\ Hollusion-TV-Window/WH_Song\ 2_CatCrow_Holl_H.mp4",
         "args": "-o local --no-osd",
		     #"endtime": 15,
         "vol": 10,
		   },
	     "front_lights": {
		     "r": 128,
		     "g": 128,
		     "b": 128,
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
         "args": "--no-osd -o local -l 37 --orientation 180",
         "vol": 10,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/Phantasms-Rise\ Of\ The\ Wraiths.mp4",
         "args": "-o local --no-osd",
		     "wait": 40,
		     #"endtime": 15,
         "vol": 10,
		   },
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
     6: {  			# playlist 6
       "master": 1,
	     1: {			# player 1
         "file": "/home/pi/videos/Thriller/thriller_video.mp4",
         #"args": "--no-osd -o local -l 410",
         "args": "--no-osd -o local -l 244 --orientation 180",
         "vol": 15,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/Thriller/thriller_anim.mp4",
         "args": "-o local --vol -4000 --no-osd",
		     "wait": 420,
		     "endtime": 225,
         "vol": -100,
		   },
	     "front_lights": {
		     "r": 255,
		     "g": 38,
		     "b": 49,
		   },
	     "graveyard": {
		     "r": 64,
		     "g": 0,
		     "b": 64,
		   },
	   },
     7: {  			# playlist 7
       "master": 1,
	     1: {			# player 1
         "file": "/home/pi/videos/JOLJ_InTheHallSong_Trio_Win_BG_H.mp4",
         #"args": "--no-osd -o local -l 410",
         "args": "--no-osd -o local --orientation 180",
         "vol": 10,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/EE_OminousOculi_Swarm_Eyes+Mouths_H.mp4",
         "args": "-o local --loop --no-osd",
         "vol": 0,
		   },
	     "front_lights": {
		     "r": 255,
		     "g": 138,
		     "b": 20,
		   },
	     "graveyard": {
		     "r": 255,
		     "g": 165,
		     "b": 0,
		   },
	   },
      8: {  			# playlist 8
       "master": 2,
	     1: {			# player 1
         "file": "/home/pi/videos/Bone\ Chillers-Dancing\ Dead.mp4",
         #"args": "--no-osd -o local -l 410",
         "args": "--no-osd -o local --loop --vol -4000 --orientation 180",
         "vol": -100,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/Spooly\ Scarry\ Skel.mp4",
         "args": "-o local --no-osd",
         "vol": 0,
		   },
	     "front_lights": {
		     "r": 0,
		     "g": 0,
		     "b": 200,
		   },
	     "graveyard": {
		     "r": 64,
		     "g": 0,
		     "b": 0,
		   },
	   },
     9: {  			# playlist 9
       "master": 2,
	     1: {			# player 1
         "file": "/home/pi/videos/Ghostly\ Apparitions-Beckoning\ Beauty.mp4",
         #"args": "--no-osd -o local -l 410",
         "args": "--no-osd -o local --loop  --orientation 180",
         "vol": -15,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/WH_Spell\ 3_Seance_Holl_H.mp4",
         "args": "-o local --no-osd",
         "vol": 0,
		   },
	     "front_lights": {
		     "r": 247,
		     "g": 0,
		     "b": 255,
		   },
	     "graveyard": {
		     "r": 0,
		     "g": 200,
		     "b": 0,
		   },
	   },
     10: {  			# playlist 10
       "master": 2,
	     1: {			# player 1
         "file": "/home/pi/videos/BOO_BooTime_Holl_H.mp4",
         #"args": "--no-osd -o local -l 410",
         "args": "--no-osd -o local --loop  --orientation 180",
         "vol": -15,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/WH\ -\ Song1\ -\ Witching\ Hour\ -\ Hollusion-TV-Window/WH_Song\ 1_WitchingHour_Holl_H.mp4",
         "args": "-o local --no-osd",
         "vol": 0,
		   },
	     "front_lights": {
		     "r": 247,
		     "g": 0,
		     "b": 255,
		   },
	     "graveyard": {
		     "r": 200,
		     "g": 0,
		     "b": 0,
		   },
	   },
     11: {  			# playlist 10
       "master": 1,
	     1: {			# player 1
         "file": "/home/pi/videos/Guardians_inferno.mp4",
         #"args": "--no-osd -o local -l 410",
         "args": "--no-osd -o local --orientation 180",
         "vol": 0,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/EE_OminousOculi_Swarm_Eyes+Mouths_H.mp4",
         "args": "-o local --loop --no-osd",
         "vol": 0,
		   },
	     "front_lights": {
		     "r": 200,
		     "g": 200,
		     "b": 0,
		   },
	     "graveyard": {
		     "r": 200,
		     "g": 200,
		     "b": 0,
		   },
	   },
	     12: {  			# playlist 10
       "master": 2,
	     1: {			# player 1
         "file": "/home/pi/videos/Jack-O-Lantern\ -\ Funny\ Faces\ -\ Window/Jack-O-Lantern\ -\ Funny\ Faces\ -\ Window/JOLJ_FunnyFaces_Trio_Win_BG_H.mp4",
         #"args": "--no-osd -o local -l 410",
         "args": "--no-osd -o local --loop  --orientation 180",
         "vol": 0,
		   },
	     2: {			# player 2
         "file": "/home/pi/videos/deadmou5_ghostsnstuff.mp4",
         "args": "-o local --no-osd",
         "vol": 0,
		   },
	     "front_lights": {
		     "r": 0,
		     "g": 200,
		     "b": 0,
		   },
	     "graveyard": {
		     "r": 200,
		     "g": 0,
		     "b": 0,
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


state = "init";

# states:
#   init - players just launched, waiting to reset data structures
#   reset - players have reset their data structres and ready for queuing
#   queued - video is loaded and ready to play
#   playing - playing has begun
#   done - all players done playing

def checkPlayerStatus():
    global videoStats
    global currentplaylist
    global playlist
    global messagelog
    global state
    global mqrttc
    global waitForReset

    master = playlist[currentplaylist]["master"]

    # keep resetting until all players are in reset state
    for player in videoStats:
        if videoStats[player]["player_status"] != "reset" and waitForReset == True:
          messagelog.append("%s : not all players ready, sending new reset %d" % (timeNow(), player))
          resetAllPlayers()
          return

    if waitForReset == True:
      messagelog.append("%s : all players ready, proceeding" % (timeNow()))
      waitForReset = False

        #pprint(videoStats[player])

    for player in videoStats:
      if videoStats[player]["player_status"] == "False":
        videoStats[player] = False

      elif videoStats[player]["player_status"] == "standby":
        #messagelog.append("%s : resetting %d" % (timeNow(), player))
        #mqttc.publish("player/%d/command" % player, "reset")
        mqttc.publish("player/%d/0_last_standby" % player, timeNow())
        resetAllPlayers()

      elif videoStats[player]["player_status"] == "reset":
        #pprint(playlist[currentplaylist][int(player)])
        #sleep(3)
        messagelog.append("%s : queuing %d with %s" % (timeNow(), player, json.dumps(playlist[currentplaylist][int(player)])))
        mqttc.publish("player/%d/current_playlist" % player, currentplaylist)
        for key in playlist[currentplaylist][int(player)]:
          mqttc.publish("player/%d/%s" % (player, key), playlist[currentplaylist][int(player)][key])
        mqttc.publish("player/%d/command" % player, "queue")
        mqttc.publish("player/%d/2_last_queue" % player, timeNow())

      elif master == int(player) and \
          videoStats[player][u"player_status"] == "queued" and \
          videoStats[player]["paused"] == "True":
        messagelog.append("%s : unpausing %d" % (timeNow(), player))
        mqttc.publish("player/%d/command" % player, "unpause")
        mqttc.publish("player/%d/3_last_master_unpause" % player, timeNow())
        #mqttc.publish("front_lights/command", "on")
        mqttc.publish("front_lights", "ON")
        mqttc.publish("graveyard/command", "on")
        mqttc.publish("front_lights/col", "#%x%x%x" % (playlist[currentplaylist]["front_lights"]["r"], playlist[currentplaylist]["front_lights"]["g"], playlist[currentplaylist]["front_lights"]["b"]))
        #mqttc.publish("front_lights/color/r", playlist[currentplaylist]["front_lights"]["r"])
        #mqttc.publish("front_lights/color/g", playlist[currentplaylist]["front_lights"]["g"])
        #mqttc.publish("front_lights/color/b", playlist[currentplaylist]["front_lights"]["b"])
        mqttc.publish("graveyard/color/r", playlist[currentplaylist]["graveyard"]["r"])
        mqttc.publish("graveyard/color/g", playlist[currentplaylist]["graveyard"]["g"])
        mqttc.publish("graveyard/color/b", playlist[currentplaylist]["graveyard"]["b"])
        mqttc.publish("front_lights/command", "go")
        mqttc.publish("graveyard/command", "go")
      elif master != int(player) and \
          videoStats[player][u"player_status"] == "queued" and \
          videoStats[master].has_key("paused") and videoStats[master]["paused"] == "False" and \
          videoStats[player].has_key("paused") and videoStats[player]["paused"] == "True" and \
          (not playlist[currentplaylist][player].has_key("wait") or playlist[currentplaylist][player]["wait"] < videoStats[master]["position"]):
        messagelog.append("%s : unpausing %d" % (timeNow(), player))
        mqttc.publish("player/%d/command" % player, "unpause")
        mqttc.publish("player/%d/3_last_slave_unpause" % player, timeNow())
      elif master == int(player) and \
          videoStats[player].has_key("player_running") and \
          videoStats[player]["player_running"] == "False":
        messagelog.append("%s : Master is done, resetting all players, next playlist" % timeNow())
        nextPlayList()
        resetAllPlayers()
      elif master == int(player) and \
          videoStats[master].has_key("duration") and \
          playlist[currentplaylist][master].has_key("endtime") and \
          videoStats[master]["position"] >= playlist[currentplaylist][master]["endtime"]:
        messagelog.append("%s : Master reached endtime, resetting all players, next playlist" % timeNow())
        nextPlayList()
        resetAllPlayers()

	#elif master != player and \
	    #videoStats[master].has_key("duration") and \
	    #videoStats[master]["duration"] - videoStats[master]["position"] < 10:
                #messagelog.append("%s : fade to black %d" % (timeNow(), player))
                #socket.send("%d fadeblack" % player)

def checkPlayers(targetState):
    for player in videoStats:
      if videoStats[player]["player_status"] != targetState:
        return False
      else:
        return False

def resetAllPlayers():
    global videoStats
    global messagelog
    global mqttc
    global currentplaylist
    messagelog.append("%s : resetting all players" % timeNow())
    for player in videoStats:
      messagelog.append("%s :   resetting %d" % (timeNow(), player))
      mqttc.publish("player/%d/command" % player, "reset")
      mqttc.publish("player/%d/1_last_reset" % player, timeNow())
    sleep(3)
    messagelog.append("%s :   resetAllPlayers exit" % (timeNow()))

def queuePlayers():
    print "queue players here"
    

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

