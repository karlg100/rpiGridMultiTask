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
	def __init__(self, size, value=None):
		self.size = size-1
		self.leds = [value]*size	# the shown values
		self.ledsBuffer = self.leds[:]	# memory buffer until show() is called
		self.offset = 0			# offset from 0 where the layer should start (unimplimented)
		self.bufLocked = False		# lock the buffer while copying
		self.dead = False		# when the thread dies, set to 1 so it can be cleaned up by the master

	def __getitem__(self, pos):
		"""Return the 24-bit RGB color value at the provided position or slice
		of positions.
		"""
		# Handle if a slice of positions are passed in by grabbing all the values
		# and returning them in a list.
		#pprint(pos)
		if isinstance(pos, slice):
			return self.ledsBuffer[pos]
		# Else assume the passed in value is a number to the position.
		else:
			return self.ledsBuffer

	def __setitem__(self, pos, value):
		"""Set the 24-bit RGB color value at the provided position or slice of
		positions.
		"""
		#pprint(pos)
		#pprint(self.ledsBuffer.__getitem__(pos))
		# Handle if a slice of positions are passed in by setting the appropriate
		# LED data values to the provided values.
		self.setPixelColor(pos, value)

	def show(self):
		self.bufLocked = True
		self.leds = self.ledsBuffer[:]
		self.bufLocked = False

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
			self.ledsBuffer[n] = [color]*len(self.ledsBuffer[n])
		else:
			self.ledsBuffer[n] = color
		#pprint(self.ledsBuffer)

	def setPixelColorRGB(self, n, red, green, blue):
		"""Set LED at position n to the provided red, green, and blue color.
		Each color component should be a value from 0 to 255 (where 0 is the
		lowest intensity and 255 is the highest intensity).
		"""
		self.setPixelColor(n, Color(red, green, blue))

	def getPixels(self):
		while self.bufLocked is True:
			sleep(.001)
		return self.leds[:]

	def getPixelsBuffer(self):
		"""Return an object which allows access to the LED display data as if 
		it were a sequence of 24-bit RGB values.
		"""
		return self.ledsBuffer

	def numPixels(self):
		"""Return the number of pixels in the display."""
		return self.size+1

	def getPixelColor(self, n):
		"""Get the 24-bit RGB color value for the LED at position n."""
		return self.ledsBuffer[n]


class pixelMaster(object):
	def __init__(self, strip):
		"""
		   merges the layers and pushes to the ws281x strand
		"""
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

		# layers struct
		self.layerLock = threading.RLock()
		self.layers = {0: pixelLayer(self.size, 0)}

	def flattenLayers(self):
		self.layerLock.acquire()
		try:
			for k in self.layers.keys():
				bfr = self.layers[k].getPixels()
				if self.layers[k].dead is not False:
					if self.layers[k].dead < 100:
						self.layers[k].dead += 1
					else:
						del self.layers[k]
						continue
					alpha=100-self.layers[k].dead
				else:
					alpha=100
				for pxl in range(self.size):
					if bfr[pxl] is not None:
						r1,g1,b1 = RGB(self.ledsColorBuffer[pxl])
						r2,g2,b2 = RGB(bfr[pxl])
						self.ledsColorBuffer[pxl] = Color((r1+r2)/2*alpha, (g1+g2)/2*alpha, (b1+b2)/2*alpha)
						#rt,gt,bt = RGB(self.ledsColorBuffer[pxl])
						#print "%s - r %s/%s = %s g %s/%s = %s b %s/%s = %s" % (k, r1, r2, rt, g1, g2, gt, b1, b2, bt)
		finally:
			self.layerLock.release()

	def show(self):
		"""Update the display with the data from the LED buffer."""
		self.flattenLayers()
		count = 0
		for v in self.ledsColorBuffer:
			self.strip.setPixelColor(count, v)
			count += 1
		self.strip.show()

	def newLayer(self, number=None):
		self.layerLock.acquire()
		try:
			newLayer = pixelLayer(self.size)
			if number is None:
				self.layers[self.layers.keys()[-1]+1] = newLayer
			else:
				self.layers[number] = newLayer
			return newLayer
		finally:
			self.layerLock.release()

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
