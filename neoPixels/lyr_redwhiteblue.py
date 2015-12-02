#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep
import time

def redWhiteBlue(master, wait_ms=10, bandwidth=50, runtime=60):
	layer = master.newLayer()
	count=0
	for i in range(0, layer.numPixels()):
		#print "%s + %s mod %s = %s  count %s" % (i, o, bandwidth, (i+o) % bandwidth, count)
		if i % bandwidth == 0:
			count += 1
		if count == 4:
			count = 1
		#print("%s" % count),

		if count == 3:
			layer.setPixelColorRGB(i, 200,200,200)
		elif count == 2:
			layer.setPixelColorRGB(i, 0,0,200)
		elif count == 1:
			layer.setPixelColorRGB(i, 200,0,0)
		#if i < bandwidth*3:
		  #sleep(.5)
		layer.show()

	# rotate
        endTime=time.time()+runtime
        while time.time() < endTime:
		leds=layer[::]
		#print leds
		end=leds.pop()
		led=1
		for color in leds:
			layer.setPixelColor(led, color)
			led += 1
		layer.setPixelColor(0, end)
		layer.show()
		sleep(wait_ms/1000.0)
	layer.dead = 0



# entry function
def NeoFX(master, *args):
	redWhiteBlue(master, *args)

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

