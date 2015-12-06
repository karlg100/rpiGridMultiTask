#!/usr/bin/python

import pxlBuffer as pxb
import random
import math
from time import sleep
import time
from collections import deque
import pprint


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

def calcStars(layer):
	#print "%s - %s" % (pixStart, pixEnd)

	# light the next star
	if random.randrange(1,100) <= 1:
		layer["buffer"][0] = wheel(random.randrange(0, 255), 255)

	# rotate and paint the led buffer by the speed of the stars
	for q in range(layer["speed"]):
		for pxl in range(layer["obj"].numPixels()):
			if layer["buffer"][pxl] is not None:
				layer["obj"][pxl] = layer["buffer"][pxl]
		layer["buffer"].rotate()

	#pprint(layer["buffer"])

	# fade out the unused LEDs to give them a tail
	for pixel in range(layer["obj"].numPixels()):
		layer["obj"].pixelBrightness(pixel, -.5)

	#layer["pixEnd"] = layer["pixStart"]
	#pixEnd=int((math.cos(math.radians(angle))*(layer.numPixels()-1)/2)+layer.numPixels()/2)
	#layer["pixStart"]=int((math.sin(math.radians(angle))*(layer["obj"].numPixels()-1)/2)+layer["obj"].numPixels()/2)
	#pixRange(layer["obj"], layer["color"], layer["pixStart"], layer["pixEnd"])
	#pixRange(layer["obj"], wheel((math.sin(math.radians(angle))+1)/2*255, 1), layer["pixStart"], layer["pixEnd"])
	#print int(wheel((math.sin(math.radians(angle)+.5)*255+255/2), 1))
	#pixRange(layer["obj"], int(wheel(math.sin(math.radians(angle)*255+255/2), 1)), pixStart, pixEnd)
	layer["obj"].show()

def stars(master, wait_ms=1, bandwidth=5, runtime=60):
	layer = { 0: {},
		  1: {},
		  2: {},
		  3: {},
		}
	layer[0]["obj"] = master.newLayer()
	layer[0]["buffer"] = deque(layer[0]["obj"][::])
	layer[0]["speed"] = random.randrange(1,20)
	#layer[0]["direction"] = random.randrange(1,2)
	layer[1]["obj"] = master.newLayer()
	layer[1]["buffer"] = deque(layer[1]["obj"][::])
	layer[1]["speed"] = random.randrange(1,20)
	#layer[1]["direction"] = random.randrange(1,2)
	layer[2]["obj"] = master.newLayer()
	layer[2]["buffer"] = deque(layer[2]["obj"][::])
	layer[2]["speed"] = random.randrange(1,20)
	#layer[2]["direction"] = random.randrange(1,2)
	layer[3]["obj"] = master.newLayer()
	layer[3]["buffer"] = deque(layer[3]["obj"][::])
	layer[3]["speed"] = random.randrange(1,20)
	#layer[3]["direction"] = random.randrange(1,2)

        endTime=time.time()+runtime
        while time.time() < endTime:
		for a in range(0,3600,8):
			angle=a/10.0
			calcStars(layer[0])
			calcStars(layer[1])
			calcStars(layer[2])
			calcStars(layer[3])
			sleep(wait_ms/1000.0)
			
	layer[0]["obj"].dead = 0
	layer[1]["obj"].dead = 0
	layer[2]["obj"].dead = 0
	layer[3]["obj"].dead = 0
	
	

# entry function
def NeoFX(master, *args):
	stars(master, *args)

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

