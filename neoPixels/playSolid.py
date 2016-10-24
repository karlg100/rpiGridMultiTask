# NeoPixel multithreaded display
# This script plays all lyr_* modules in the directory, calling hte NeoFX() function from the module
# Author: Karl Grindley (karl@linuxninja.net)
#
# derived from NeoPixel library strandtest example
# NeoPixel strandtest Author: Tony DiCola (tony@tonydicola.com)

import time
import multiprocessing
from pprint import pprint
from time import sleep
import random
from neopixel import *
import pxlBuffer as pxb

import datetime
import ephem

# 14 Westview Street - 42.608492, -71.627986, 324 ft
lat  = str(42.608492)  #Note that lat should be in string format
lon  = str(-71.627986) #Note that lon should be in string format
elev = 324


plugins= [	
		"lyr_solid",
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


#pxlModules = []
#for importer, modname, ispkg in pkgutil.iter_modules(pxlLayers.__path__):
    #pxlModules.append(modname)
    #print "Found submodule %s (is a package: %s)" % (modname, ispkg)

#print pxlModules

q = multiprocessing.Queue()

def masterThread(q):

	# Create NeoPixel object with appropriate configuration.
	strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
	# Intialize the library (must be called once before other functions).
	strip.begin()

	master = pxb.pixelMaster(strip, q)
	master.show()
	#pprint(master.layers)

	#pprint(master.ledsColorBuffer)

	startTime=time.time()
	iterTime=startTime
	count=1
	targetSleep=1/float(TARGET_FPS)
	print "target FPS: %s" % TARGET_FPS
	print "target runtime per frame: %s" % targetSleep
	updateFreq=TARGET_FPS*10 # every 10 seconds
	while master.die == False:
		iterTime=time.time()
		runTime=(time.time()-startTime)
		master.show()
		if count % updateFreq == 0:
			print "Time: %2.3f FPS: %2.3f" % (runTime, count/runTime)
			print "active layers: %s" % len(master.layers)
			startTime=time.time()
			count = 1
		else:
			count += 1

		sleepTime=targetSleep-(time.time()-iterTime)
		if sleepTime > 0:
			sleep(sleepTime)

m = multiprocessing.Process(target=masterThread, args=(q,))
m.daemon=True
m.start()

try:
	layer = 1
	observ = ephem.Observer()
	observ.lat = lat
	observ.lon = lon
	observ.elev = elev
	observ.pressure= 0

	#-6=civil twilight, -12=nautical, -18=astronomical
	observ.horizon = '-6'
	

	while True:
		observ.date = datetime.datetime.now()
		#observ.date = "2016-07-25 01:00:00"
		sun = ephem.Sun()

		# if the next sun rise is before the next sun set, then it's nighttime
		if observ.next_rising(ephem.Sun()) < observ.next_setting(ephem.Sun()):
			module=modules[random.randrange(0,len(modules))]
		else:
			# turn everything off, and sleep a long time
			module="lyr_clear"

		print "playing %s on layer %s" % (module, layer)
		try:
			module.NeoFX(q, LED_COUNT, layer)
			layer += 1
		except:
			print "[!] %s module crashed" % module

		print "Sleeping 10 seconds"
		sleep(10)

except KeyboardInterrupt:
	q.put("die")
	m.join()
