#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep

def twinklePxl(color, origR, origG, origB, swing):
	rand=random.randrange(-1,2)
	r, g, b = pxb.RGB(color)
	#print "rand: %s - r %s g %s b %s" % (rand, r,g,b)
	if 	(rand > 0 and \
		r < 255 and \
		g < 255 and \
		b < 255):
		#print "red %s, green %s, blue %s" % (r+rand, g+rand, b+rand)
		return pxb.Color(r+rand, g+rand, b+rand)
	elif	(rand < 0 and \
		r >= origR-swing and \
		g >= origG-swing and \
		b >= origB-swing and \
		r+rand >= 0 and \
		g+rand >= 0 and \
		b+rand >= 0):
		#print "red %s, green %s, blue %s" % (r+rand, g+rand, b+rand)
		return pxb.Color(r+rand, g+rand, b+rand)
	else:
		return color


def twinkleColor(red, green, blue, wait_ms=1, twinkleSwing=100, p1=50):
	global master
	layer = master.newLayer()
	layer[0:layer.size+1] = pxb.Color(red, green, blue);
	while True:
		pixels = layer[:]
		for x in range(layer.size+1):
			#print "random range of 1 to %s : %s\n" % (p1, random.randrange(1, p1+1))
			#print "x: %s\n" % pixels[x]
			if random.randrange(1, p1+1) == p1:
				layer.setPixelColor(x, twinklePxl(pixels[x], red, green, blue, twinkleSwing))
		layer.show()
		sleep(wait_ms/1000.0)

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

	e = threading.Thread(target=twinkleColor, args=(200,0,0))
	e.daemon=True
	e.start()

	startTime=time.time()
	iterTime=startTime
	count=1

	while True:
		runTime=(time.time()-startTime)
		master.show()
		count += 1
		print "Time: %2.3f FPS: %2.3f" % (runTime, count/runTime)
		iterTime=time.time()

		sleepTime=1/float(TARGET_FPS+0.5)-(time.time()-iterTime)
        	if sleepTime > 0:
			sleep(sleepTime)

