#!/usr/bin/python

import pxlBuffer as pxb
import random
import math
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

def pixRange(layer, color, start, end):
	if start > end:
		t = end
		end = start
		start = t

	#print "%s - %s %s" % (color, start, end)
	for pixel in range(start, end+1):
		layer.setPixelColor(pixel, color)

def calcParticle(layer, angle):
	#print "%s - %s" % (pixStart, pixEnd)

	# this will just shut off unused LEDs
	#layer["obj"][::] = None

	# fade out the unused LEDs to give them a tail
	for pixel in range(layer["obj"].numPixels()):
		layer["obj"].pixelBrightness(pixel, -0.1)

	layer["pixEnd"] = layer["pixStart"]
	#pixEnd=int((math.cos(math.radians(angle))*(layer.numPixels()-1)/2)+layer.numPixels()/2)
	layer["pixStart"]=int((math.sin(math.radians(angle))*(layer["obj"].numPixels()-1)/2)+layer["obj"].numPixels()/2)
	pixRange(layer["obj"], layer["color"], layer["pixStart"], layer["pixEnd"])
	#pixRange(layer["obj"], wheel((math.sin(math.radians(angle))+1)/2*255, 1), layer["pixStart"], layer["pixEnd"])
	#print int(wheel((math.sin(math.radians(angle)+.5)*255+255/2), 1))
	#pixRange(layer["obj"], int(wheel(math.sin(math.radians(angle)*255+255/2), 1)), pixStart, pixEnd)
	layer["obj"].show()

def particles(master, wait_ms=.01, bandwidth=5, runtime=60):
	layer = { 0: {},
		  1: {},
		  2: {},
		  3: {},
		}
	layer[0]["obj"] = master.newLayer()
	layer[0]["pixStart"] = int(layer[0]["obj"].numPixels()/2)
	layer[0]["pixEnd"] = int(layer[0]["obj"].numPixels()/2)
	layer[0]["color"] = pxb.Color(255,0,0)
	layer[1]["obj"] = master.newLayer()
	layer[1]["pixStart"] = int(layer[1]["obj"].numPixels()/2)
	layer[1]["pixEnd"] = int(layer[1]["obj"].numPixels()/2)
	layer[1]["color"] = pxb.Color(0,255,0)
	layer[2]["obj"] = master.newLayer()
	layer[2]["pixStart"] = int(layer[2]["obj"].numPixels()/2)
	layer[2]["pixEnd"] = int(layer[2]["obj"].numPixels()/2)
	layer[2]["color"] = pxb.Color(0,0,255)
	layer[3]["obj"] = master.newLayer()
	layer[3]["pixStart"] = int(layer[3]["obj"].numPixels()/2)
	layer[3]["pixEnd"] = int(layer[3]["obj"].numPixels()/2)
	layer[3]["color"] = pxb.Color(255,255,255)

        endTime=time.time()+runtime
        while time.time() < endTime:
		for a in range(3600):
			angle=a/10.0
			calcParticle(layer[0], angle)
			calcParticle(layer[1], angle+90)
			calcParticle(layer[2], angle+180)
			calcParticle(layer[3], angle+270)
			sleep(wait_ms/1000.0)
			
	
	

# entry function
def NeoFX(master, *args):
	particles(master, *args)

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

