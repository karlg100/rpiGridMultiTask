#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep
import time
import math
from collections import deque

def wheel(pos, brightness):
	"""Generate rainbow colors across 0-255 positions."""
	if pos < 85:
		return pxb.Color(pos * 3 * brightness, (255 - pos * 3) * brightness, 0)
	elif pos < 170:
		pos -= 85
		return pxb.Color((255 - pos * 3) * brightness, 0, pos * 3 * brightness)
	else:
		pos -= 170
		return pxb.Color(0, pos * 3 * brightness, (255 - pos * 3) * brightness)

def theaterChaseRainbow(q, led_count, layerNum, wait_ms=50, pxlSpace=20, runtime=60):
	layer = pxb.pixelLayer(q, led_count, layerNum)
	leds=deque(layer[::])
	"""Rainbow movie theater light style chaser animation."""
	endTime=time.time()+runtime
	count=0
	speedCount=0
	populate = True
        while time.time() < endTime:
		if count == 0:
			j=random.randrange(0,256)
		if count == 0:
			leds[0] = wheel(j, .1)
		elif count == 1:
			leds[0] = wheel(j, .5)
		elif count == 2:
			leds[0] = wheel(j, 1)
		elif count == 3:
			leds[0] = wheel(j, .5)
		elif count == 4:
			leds[0] = wheel(j, .1)
		else:
			leds[0] = None
		if populate == False:
			layer.leds = list(leds)
			layer.show()
			sleep(wait_ms/1000.0)
		elif speedCount > layer.numPixels():
			populate = False
		if count == pxlSpace:
			count = 0
		else:
			count += 1
		if speedCount > 3600:
			speedCount=0
		else:
			speedCount += 1
		#print math.cos(speedCount/10.0)+1
		#sleep((math.cos(speedCount/10.0)+1)*wait_ms/1000.0)
		leds.rotate()
	layer.die()

def NeoFX(q, led_count, layerNum, *args):
	theaterChaseRainbow(q, led_count, layerNum)

# if we're testing the module, setup and execute
if __name__ == "__main__":
	from neopixel import *
	import multiprocessing
	import time
	from pprint import pprint

	# target FPS
	#TARGET_FPS = 1
	TARGET_FPS = 24

	# LED strip configuration:
	LED_COUNT      = 632      # Number of LED pixels.
	LED_PIN        = 18      # GPIO pin connected to the pixels (must support PWM!).
	LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
	LED_DMA        = 5       # DMA channel to use for generating signal (try 5)
	LED_BRIGHTNESS = 128     # Set to 0 for darkest and 255 for brightest
	LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)

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
                                print master.layers
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
		while True:
			NeoFX(q, LED_COUNT, layer)
			layer += 1

	except KeyboardInterrupt:
		q.put("die")
		m.join()
