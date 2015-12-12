# Drived from the rpi_ws281x library.  A buffer class used to create layers for then passing
# a flattened set of values to rxi_ws281x for dsiplay on the neoPixels
# this is so that multiple simultanious animiation elements can be complied together easily
# Author: Karl Grindley (karlg100@gmail.com)

from neopixel import *
import threading
from pprint import pprint
from time import sleep

def Color(red, green, blue):
	return (int(red) << 16) | (int(green) << 8) | int(blue)

def RGB(color):
	return ((color >> 16) & 255, (color >> 8) & 255, color & 255)

class pixelLayer(object):
	"""A layer of pixels
	   values are stored in a list which is initizlaized to nulls
	   a null is a transparent value.  When compiled, the underlying layer
	   will take precidence.  otherwise the value in the upper layer will take precidnce.
	   note that like the way that other neopixel libraries work, you have to call show()
	   to trigger the update to the array
	"""
	def __init__(self, q, size, layer, value=None):
		self.q = q
		self.size = size
		self.leds = [value]*size	# the shown values
		self.offset = 0			# offset from 0 where the layer should start (unimplimented)
		#self.bufLocked = False		# lock the buffer while copying
		self.status = True		# when the thread dies, set to 1 so it can be cleaned up by the master
		self.layer = layer		# layer number

	def __getitem__(self, pos):
		"""Return the 24-bit RGB color value at the provided position or slice
		of positions.
		"""
		# Handle if a slice of positions are passed in by grabbing all the values
		# and returning them in a list.
		#pprint(pos)
		if isinstance(pos, slice):
			return self.leds[pos]
		# Else assume the passed in value is a number to the position.
		else:
			return self.leds

	def __setitem__(self, pos, value):
		"""Set the 24-bit RGB color value at the provided position or slice of
		positions.
		"""
		#pprint(pos)
		#pprint(self.leds.__getitem__(pos))
		# Handle if a slice of positions are passed in by setting the appropriate
		# LED data values to the provided values.
		self.setPixelColor(pos, value)

	def show(self):
		#self.bufLocked = True
		#self.leds = self.leds[:]
		self.q.put(	{"layer": self.layer,
				"status": self.status,
				"leds": self.leds,
				}
				)
		#self.bufLocked = False

	def pixelBrightness(self, pos, amount=0.01):
		if self.getPixelColor(pos) == 0:
			self.setPixelColor(pos, None)
		if self.getPixelColor(pos) == None:
			return False
		r,g,b = RGB(self.getPixelColor(pos))
		self.setPixelColorRGB(pos, r+r*amount, g+g*amount, b+b*amount)

	def setPixelColor(self, n, color):
		"""Set LED at position n to the provided 24-bit color value (in RGB order).
		"""
		#print "pxl %s = %s" % (n, color)
		if isinstance(n, slice):
			self.leds[n] = [color]*len(self.leds[n])
		else:
			if n >= 0 or n <= self.size:
				self.leds[n] = color
		#pprint(self.leds)

	def setPixelColorRGB(self, n, red, green, blue):
		"""Set LED at position n to the provided red, green, and blue color.
		Each color component should be a value from 0 to 255 (where 0 is the
		lowest intensity and 255 is the highest intensity).
		"""
		self.setPixelColor(n, Color(red, green, blue))

	def getPixels(self):
		#while self.bufLocked is True:
			#sleep(.001)
		return self.leds[:]

	def getPixelsBuffer(self):
		"""Return an object which allows access to the LED display data as if 
		it were a sequence of 24-bit RGB values.
		"""
		return self.leds

	def numPixels(self):
		"""Return the number of pixels in the display."""
		return self.size

	def getPixelColor(self, n):
		"""Get the 24-bit RGB color value for the LED at position n."""
		return self.leds[n]

	def die(self):
		self.status = False
		self.show()


class pixelMaster(object):
	def __init__(self, strip, q):
		"""
		   merges the layers and pushes to the ws281x strand
		"""

		# multiprocessing que
		self.q = q

		self.strip = strip
		# Create NeoPixel object with appropriate configuration.
		#self.strip = Adafruit_NeoPixel(size, pin, freq_hz, dma, invert, brightness, channel)
		#self.strip.begin()
		#self.strip = strip

		# total pixels
		self.size = strip.numPixels()
		# LED memory buffer
		self.ledsColorBuffer = [0]*self.size
		#self.ledsBrightness = brightness

		self.die = False

		# layers struct
		self.layers = {0: {	"layer": 0,
					"status": True,
					"leds":[0]*self.size,
					}
				}

	def flattenLayers(self):
		#self.layerLock.acquire()
		for k in self.layers.keys():
			if self.layers[k]["status"] is not True:
				#if self.layers[k].status < 100:
					#self.layers[k].status += 1
				#else:
					del self.layers[k]
					continue
		#try:
		for k in self.layers.keys():
			bfr = self.layers[k]["leds"]
			if self.layers[k]["status"] is not True:
				alpha=(100-self.layers[k]["status"])/100.0
			else:
				alpha=1
			if k == 0:
				self.ldsColorBuffer = bfr
			for pxl in range(self.size):
				if bfr[pxl] is not None:
					r1,g1,b1 = RGB(self.ledsColorBuffer[pxl])
					r2,g2,b2 = RGB(bfr[pxl])
					self.ledsColorBuffer[pxl] = Color(((r1*alpha)+r2)/2, ((g1*alpha)+g2)/2, ((b1*alpha)+b2)/2)
					#rt,gt,bt = RGB(self.ledsColorBuffer[pxl])
					#print "%s - r %s/%s = %s g %s/%s = %s b %s/%s = %s" % (k, r1, r2, rt, g1, g2, gt, b1, b2, bt)
		#finally:
			#self.layerLock.release()

	def processQueue(self):
		#print "processing queue"
		while not self.q.empty():
			msg = self.q.get()
			if msg == "die":
				self.die = True
			else:
				self.layers[msg["layer"]] = msg

	def show(self):
		"""Update the display with the data from the LED buffer."""
		self.processQueue()
		self.flattenLayers()
		count = 0
		for v in self.ledsColorBuffer:
			self.strip.setPixelColor(count, v)
			count += 1
		self.strip.show()

	def newLayer(self, number=None):
		#self.layerLock.acquire()
		#try:
		newLayer = [None]*self.size
		if number is None:
			self.layers[self.layers.keys()[-1]+1] = newLayer
		else:
			self.layers[number] = newLayer

	def setBrightness(self, brightness):
		"""Scale each LED in the buffer by the provided brightness.  A brightness
		of 0 is the darkest and 255 is the brightest.
		"""
		self.led_brightness = brightness
		self.strip.setPrightness(self.led_brightness)

	def getPixels(self):
		"""Return an object which allows access to the LED display data as if 
		it were a sequence of 24-bit RGB values.
		"""
		return self.strip.ledsColorBuffer

	def numPixels(self):
		"""Return the number of pixels in the display."""
		return self.size

