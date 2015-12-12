#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep
import time
from collections import deque

def redWhiteBlue(q, led_count, layerNum, wait_ms=10, sets=4, runtime=60):
	layer = pxb.pixelLayer(q, led_count, layerNum)
	count=0
	bandwidth=int(layer.numPixels()/sets/3)
	for i in range(0, layer.numPixels()):
		if count < bandwidth:
			layer.setPixelColorRGB(i, 200,200,200)
		elif count < bandwidth*2:
			layer.setPixelColorRGB(i, 0,0,200)
		elif count < bandwidth*3:
			layer.setPixelColorRGB(i, 200,0,0)
		else:
			count = 0
		count += 1
		layer.show()


	# rotate
	leds=deque(layer[::])
        endTime=time.time()+runtime
        while time.time() < endTime:
		leds.rotate()
		layer.leds = list(leds)
		layer.show()
		sleep(wait_ms/1000.0)
	layer.die()



# entry function
def NeoFX(q, led_count, layerNum, *args):
	redWhiteBlue(q, led_count, layerNum, *args)

# if we're testing the module, setup and execute
if __name__ == "__main__":
	from neopixel import *
	import multiprocessing
	import time
	from pprint import pprint

	# target FPS
	#TARGET_FPS = 1
	TARGET_FPS = 24
	run = True

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
		while run:
			NeoFX(q, LED_COUNT, layer)
			layer += 1

	except KeyboardInterrupt:
		q.put("die")
		while not q.empty():
			q.get()
		m.join()
		run = False
