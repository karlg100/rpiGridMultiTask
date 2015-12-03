#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep

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

def theaterChaseRainbow(master, wait_ms=1, pxlSpace=20, runtime=30):
	layer = master.newLayer()
	"""Rainbow movie theater light style chaser animation."""
	endTime=time.time()+runtime
        while time.time() < endTime:
	#for j in range(256):
		for q in range(pxlSpace):
			for i in range(0, layer.numPixels()-q, pxlSpace):
				j=random.randrange(0,256)
				if i+q+1 < layer.numPixels():
					layer.setPixelColor(i+q+1, wheel((j) % 255, .5))
				if i+q+2 < layer.numPixels():
					layer.setPixelColor(i+q+2, wheel((j) % 255, .1))
				layer.setPixelColor(i+q, wheel((j) % 255, 1))
				if i+q >= 1:
					layer.setPixelColor(i+q-1, wheel((j) % 255, .5))
				if i+q >= 2:
					layer.setPixelColor(i+q-2, wheel((j) % 255, .1))
			layer.show()
			sleep(wait_ms/1000.0)
			for i in range(0, layer.numPixels()):
				layer.setPixelColor(i, None)
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
		NeoFX(master)
