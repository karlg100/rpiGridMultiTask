#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep

def wheel(pos):
        """Generate rainbow colors across 0-255 positions."""
        if pos < 85:
                return Color(pos * 3, 255 - pos * 3, 0)
        elif pos < 170:
                pos -= 85
                return Color(255 - pos * 3, 0, pos * 3)
        else:
                pos -= 170
                return Color(0, pos * 3, 255 - pos * 3)

def rainbowCycle(wait_ms=20, iterations=5):
	global master
	layer = master.newLayer()
        """Draw rainbow that uniformly distributes itself across all pixels."""
        for j in range(256*iterations):
                for i in range(layer.numPixels()):
                        layer.setPixelColor(i, wheel(((i * 256 / layer.numPixels()) + j) & 255))
                layer.show()
                time.sleep(wait_ms/1000.0)

# entry function
def NeoFX(*args):
	rainbowCycle(*args)

# if we're testing the module, setup and execute
if __name__ == "__main__":
	from neopixel import *
	import threading
	import time
	from pprint import pprint

	# target FPS
	#TARGET_FPS = 1
	TARGET_FPS = 24

	# LED strip configuration:
	LED_COUNT      = 480      # Number of LED pixels.
	LED_PIN        = 18      # GPIO pin connected to the pixels (must support PWM!).
	LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
	LED_DMA        = 5       # DMA channel to use for generating signal (try 5)
	LED_BRIGHTNESS = 128     # Set to 0 for darkest and 255 for brightest
	LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)

	# Create NeoPixel object with appropriate configuration.
	strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
	# Intialize the library (must be called once before other functions).
	strip.begin()

	master = pxb.pixelMaster(strip)
	master.show()
	pprint(master.layers)

	#pprint(master.ledsColorBuffer)

	def masterThread():
		global master
		master.show()
		sleep(1)

	t = threading.Thread(target=masterThread)
	t.daemon=True
	t.start()

	a = threading.Thread(target=NeoFX)
	#a = threading.Thread(target=NeoFX, args=(10, 20, 30))
	a.daemon=True
	a.start()

	startTime=time.time()
	iterTime=startTime
	count=1

	while True:
		runTime=(time.time()-startTime)
		master.show()
		count += 1
		#print "Time: %2.3f FPS: %2.3f" % (runTime, count/runTime)
		iterTime=time.time()

		sleepTime=1/float(TARGET_FPS+0.5)-(time.time()-iterTime)
        	if sleepTime > 0:
			sleep(sleepTime)

