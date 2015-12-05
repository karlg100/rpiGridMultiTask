#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep
import time
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

def theaterChaseRainbow(master, wait_ms=1, pxlSpace=20, runtime=60):
	layer = master.newLayer()
	leds=deque(layer[::])
	"""Rainbow movie theater light style chaser animation."""
	endTime=time.time()+runtime
        while time.time() < endTime:
		j=random.randrange(0,256)
		leds[0] = wheel(j, random.randrange(10,100)/100.0)
		layer.ledsBuffer = list(leds)
		layer.show()
		sleep(wait_ms/1000.0)
		leds.rotate()
	layer.dead = 0

def NeoFX(master, wait_ms=50, pxlSpace=40):
	theaterChaseRainbow(master, wait_ms, pxlSpace)

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
                startTime=time.time()
                iterTime=startTime
                count=1
                targetSleep=1/float(TARGET_FPS+0.5)
                updateFreq=TARGET_FPS*10 # every 10 seconds
                while True:
                        runTime=(time.time()-startTime)
                        master.show()
                        count += 1
                        if count % updateFreq == 0:
                                print "Time: %2.3f FPS: %2.3f" % (runTime, count/runTime)
                                print master.layers

                        sleepTime=targetSleep-(time.time()-iterTime)
                        iterTime=time.time()
                        if sleepTime > 0:
                                sleep(sleepTime)

	t = threading.Thread(target=masterThread)
	t.daemon=True
	t.start()

	while True:
		NeoFX(master)