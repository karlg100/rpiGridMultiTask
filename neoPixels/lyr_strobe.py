#!/usr/bin/python

import pxlBuffer as pxb
import random
from time import sleep
import time

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

def twinkleColor(master, wait_ms=1, wheelSpeed=20, twinkleProbability=.1, runtime=60):
	layer = master.newLayer()
	#layer[0:layer.numPixels()] = pxb.Color(red, green, blue);
	colorRound=0
	color=0
        endTime=time.time()+runtime
        while time.time() < endTime:
		for x in range(layer.numPixels()):
			#layer.setPixelColor(x, pxb.Color(red, green, blue))
			#layer[0:layer.size+1] = pxb.Color(red, green, blue);
			if random.randrange(0, 1000)/1000.0 <= twinkleProbability:
		  		layer.setPixelColor(x, pxb.Color(255,255,255))
			else:
				layer.setPixelColor(x, None)
		layer.show()
		sleep(wait_ms/1000.0)
	layer.dead = 0


# entry function
def NeoFX(master, *args):
	twinkleColor(master, *args)

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

