import sys
import zmq

port = "5556"

from pyomxplayer import OMXPlayer
from time import sleep
from pprint import pprint

# Socket to talk to server
zmq_playfeedback = zmq.Context()
feedback_socket = zmq_playfeedback.socket(zmq.SUB)
socket.bind(socket.bind("tcp://*:%s" % port)


socket.connect ("tcp://192.168.1.233:%s" % port)

socket_sub.setsockopt(zmq.SUBSCRIBE, "1")

poller = zmq.Poller()
    poller.register(socket_pull, zmq.POLLIN)
    poller.register(socket_sub, zmq.POLLIN)


# This will start an `omxplayer` process, this might 
# fail the first time you run it, currently in the 
# process of fixing this though.
player = OMXPlayer('/home/pi/test.mp4', '--no-osd')

# The player will initially be paused

player.toggle_pause()
#pprint(player.__dict__)
#sleep(5)
#player.toggle_pause()
#pprint(player.__dict__)
#sleep(5)
#player.toggle_pause()
#pprint(player.__dict__)
#sleep(5)
#player.toggle_mute()
#pprint(player.__dict__)
#sleep(5)
#player.toggle_mute()
#pprint(player.__dict__)
#sleep(5)
#player.toggle_mute(.1)
#pprint(player.__dict__)
#sleep(5)
#player.toggle_mute(.5)
#pprint(player.__dict__)

# Kill the `omxplayer` process gracefully.
try:
    while True:
        pprint(player.__dict__)
except KeyboardInterrupt:
    player.stop()
