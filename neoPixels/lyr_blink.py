#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep
import time

def blinkColor(master, wait_ms=1, color="random", runtime=30):
	layer = master.newLayer()
	if color == "random":
		rnd = True
	else:
		rnd = False
	endTime=time.time()+runtime
	while time.time() < endTime:
		if rnd:
			color=pxb.Color(random.randrange(0,256), random.randrange(0,256), random.randrange(0,256))
		layer[0:layer.size+1] = color;
		layer.show()
		sleep(random.randrange(1,300)/1000.0)
		#sleep(wait_ms/1000.0)
		layer[0:layer.size+1] = None;
		layer.show()
		sleep(random.randrange(1,1000)/1000.0)
		#sleep(wait_ms/1000.0)
		#sleep(wait_ms/1000.0)
	layer.dead = 0

# entry function
def NeoFX(master, *args):
	blinkColor(master, *args)

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

