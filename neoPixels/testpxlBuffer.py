#!/usr/bin/python

import os
import time
import threading
from time import sleep
import pxlBuffer as pxb
import random
from neopixel import *

from pprint import pprint

# target FPS
#TARGET_FPS = 1
TARGET_FPS = 24

# LED strip configuration:
LED_COUNT      = 240      # Number of LED pixels.
LED_PIN        = 18      # GPIO pin connected to the pixels (must support PWM!).
LED_FREQ_HZ    = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA        = 5       # DMA channel to use for generating signal (try 5)
LED_BRIGHTNESS = 128     # Set to 0 for darkest and 255 for brightest
LED_INVERT     = False   # True to invert the signal (when using NPN transistor level shift)




#layer=pxb.pixelLayer(25)

#layer[2] = pxb.Color(255,0,0)
#pprint(layer.ledsBuffer)
#layer[4:10:2] = pxb.Color(255,0,0)

#pprint(layer.ledsBuffer)
#pprint(layer[4:10:2])

#pprint(layer.leds)
#layer.show()
#pprint(layer.leds)

def masterThread():
	global master
	master.show()
	sleep(1)


def wheel(pos):
	"""Generate rainbow colors across 0-255 positions."""
	if pos < 85:
		return pxb.Color(pos * 3, 255 - pos * 3, 0)
	elif pos < 170:
		pos -= 85
		return pxb.Color(255 - pos * 3, 0, pos * 3)
	else:
		pos -= 170
		return pxb.Color(0, pos * 3, 255 - pos * 3)

def theaterChaseRainbow(wait_ms=1/float(TARGET_FPS)/2, rounds=1000):
	global master
	layer = master.newLayer()
	"""Rainbow movie theater light style chaser animation."""
	for i in range(rounds):
		for j in range(256):
			for q in range(9):
				for i in range(0, layer.numPixels()-q, 9):
					layer.setPixelColor(i+q, wheel((j) % 255))
				layer.show()
				#pprint(layer.getPixels())
				sleep(1)
				#sleep(wait_ms/1000.0)
				for i in range(0, layer.numPixels()-q, 9):
					layer.setPixelColor(i+q, None)

def blinkColor(wait_ms=500, color=pxb.Color(255,0,0)):
	global master
	layer = master.newLayer()
	while True:
		layer[0:layer.size] = color;
		layer.show()
		sleep(wait_ms)
		layer[0:layer.size] = None;
		layer.show()
		sleep(wait_ms)

def twinklePxl(color, origR, origG, origB, swing):
	rand=random.randrange(-1,20)
	r, g, b = pxb.RGB(color)
	#print "r %s g %s b%s" % (r,g,b)
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


def twinkleColor(red, green, blue, wait_ms=1, twinkleSwing=100, p1=5):
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

# Create NeoPixel object with appropriate configuration.
strip = Adafruit_NeoPixel(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS)
# Intialize the library (must be called once before other functions).
strip.begin()

master = pxb.pixelMaster(strip)
master.show()
pprint(master.layers)

#layer1 = master.newLayer()
#layer1[10:20:2] = pxb.Color(255,0,0)
#layer1.show()
#layer2 = master.newLayer()
#layer2[9:21:2] = pxb.Color(0,255,0)
#layer2.show()
#master.show()

pprint(master.ledsColorBuffer)

#theaterChaseRainbow()

threads = []

t = threading.Thread(target=masterThread)
t.daemon=True
t.start()

#d = threading.Thread(target=blinkColor)
#d.daemon=True
#d.start()

c = threading.Thread(target=theaterChaseRainbow)
c.daemon=True
c.start()

e = threading.Thread(target=twinkleColor, args=(200,0,0))
e.daemon=True
e.start()


#sleep(1)
startTime=time.time()
iterTime=startTime
count=1

#try:
while True:
	runTime=(time.time()-startTime)
	count += 1
	master.show()
	#os.system('clear')
	print "Time: %2.3f FPS: %2.3f" % (runTime, count/runTime)
	#skew=1/float(TARGET_FPS)-count/float(runTime)/
	#pprint(master.layers)
	#pprint(master.layers[0].leds)
	#pprint(master.ledsColorBuffer)
	sleepTime=1/float(TARGET_FPS+0.5)-(time.time()-iterTime)
	#print("%3.10f - %s = %s" % (.0333, time.time()-iterTime, sleepTime))
	#print sleepTime
        if sleepTime > 0:
		sleep(sleepTime)
	iterTime=time.time()
#except KeyboardInterrupt:
	#t.kill_recieved = True
	#c.kill_recieved = True

