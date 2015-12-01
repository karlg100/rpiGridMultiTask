#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep
import time

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


def randomDrop(master, wait_ms=1, runtime=60):
	layer = master.newLayer()
	count=0

        endTime=time.time()+runtime
        while time.time() < endTime:
		if count < 1000:
			layer.setPixelColor(random.randrange(layer.numPixels()), pxb.Color(0,0,255))
		elif count < 2000:
			layer.setPixelColor(random.randrange(layer.numPixels()), pxb.Color(255,0,0))
		elif count < 3000:
			layer.setPixelColor(random.randrange(layer.numPixels()), pxb.Color(0,255,0))
		elif count < 4000:
			layer.setPixelColor(random.randrange(layer.numPixels()), pxb.Color(255,255,255))
		elif count < 5000:
			layer.setPixelColor(random.randrange(layer.numPixels()), wheel(random.randrange(255),random.randrange(100)/100.0))
			layer.setPixelColor(random.randrange(layer.numPixels()), wheel(random.randrange(255),random.randrange(100)/100.0))
			layer.setPixelColor(random.randrange(layer.numPixels()), wheel(random.randrange(255),random.randrange(100)/100.0))
		else:
			count = 0

		count += 1
		#layer.setPixelColor(random.randrange(layer.numPixels()), wheel(random.randrange(255),random.randrange(100)/100.0))
		#layer.setPixelColor(random.randrange(layer.numPixels()), wheel(random.randrange(255),random.randrange(100)/100.0))
		#layer.setPixelColor(random.randrange(layer.numPixels()), wheel(random.randrange(255),random.randrange(100)/100.0))
		
		for pixel in range(layer.numPixels()):
			layer.pixelBrightness(pixel, -0.00001)

		layer.show()
		sleep(wait_ms/1000.0)


# entry function
def NeoFX(master, *args):
	randomDrop(master, *args)

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

