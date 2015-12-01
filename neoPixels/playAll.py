# NeoPixel multithreaded display
# This script plays all lyr_* modules in the directory, calling hte NeoFX() function from the module
# Author: Karl Grindley (karl@linuxninja.net)
#
# derived from NeoPixel library strandtest example
# NeoPixel strandtest Author: Tony DiCola (tony@tonydicola.com)

import time
import threading
from pprint import pprint
from time import sleep
from neopixel import *
import random


plugins= [	"lyr_blink",
		"lyr_chaseRainbow2",
		"lyr_chaseRainbow",
		"lyr_fillin",
		"lyr_particles",
		"lyr_rainbow",
		"lyr_redwhiteblue",
		"lyr_twinkle",
	]

modules = map(__import__, plugins)

print "Playing sequences in random from the following moduels"
pprint(modules)

# LED strip configuration:
LED_COUNT      = 632     # Number of LED pixels.
LED_PIN        = 18      # GPIO pin connected to the pixels (must support PWM!).
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 5       # DMA channel to use for generating signal (try 5)
LED_BRIGHTNESS = 255     # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)

# target FPS
#TARGET_FPS = 1
TARGET_FPS = 24

import pxlBuffer as pxb
from pxlLayers import *

#pxlModules = []
#for importer, modname, ispkg in pkgutil.iter_modules(pxlLayers.__path__):
    #pxlModules.append(modname)
    #print "Found submodule %s (is a package: %s)" % (modname, ispkg)

#print pxlModules


# Create NeoPixel object with appropriate configuration.
strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
# Intialize the library (must be called once before other functions).
strip.begin()

master = pxb.pixelMaster(strip)
master.show()
pprint(master.layers)

def masterThread():
	global master
	startTime=time.time()
	iterTime=startTime
	count=1
	runTime=(time.time()-startTime)
	master.show()
	count += 1
	#print "Time: %2.3f FPS: %2.3f" % (runTime, count/runTime)
	iterTime=time.time()

	sleepTime=1/float(TARGET_FPS+0.5)-(time.time()-iterTime)
       	if sleepTime > 0:
		sleep(sleepTime)


t = threading.Thread(target=masterThread)
t.daemon=True
t.start()


while True:
	module= modules[random.randrange(0,len(modules))]
	print "playing %s" % module
	module.NeoFX(master)
	#lyr_blink.NeoFX(master)
