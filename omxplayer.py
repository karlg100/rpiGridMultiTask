from pyomxplayer import OMXPlayer
from time import sleep
from pprint import pprint

# This will start an `omxplayer` process, this might 
# fail the first time you run it, currently in the 
# process of fixing this though.
player = OMXPlayer('/home/pi/test.mp4', '--no-osd')

# The player will initially be paused

player.toggle_pause()
pprint(player.__dict__)
#sleep(5)
#player.toggle_pause()
#pprint(player.__dict__)
#sleep(5)
#player.toggle_pause()
#pprint(player.__dict__)
#sleep(5)
player.toggle_mute()
pprint(player.__dict__)
sleep(5)
player.toggle_mute()
pprint(player.__dict__)
sleep(5)
player.toggle_mute(.1)
pprint(player.__dict__)
sleep(5)
player.toggle_mute(.5)
pprint(player.__dict__)
sleep(30)

# Kill the `omxplayer` process gracefully.
player.stop()
