#!/usr/bin/env python

# Import the modules used in the script
import random, time
import RPi.GPIO as GPIO

# Assign the hardware PWM pin and name it
leds = {
	6: "", 
	12: "", 
	13: "", 
	16: "", 
	17: "", 
	18: "", 
	19: "", 
       }

for led in leds:
  print led

# Configure the GPIO to BCM and set it to output mode
GPIO.setmode(GPIO.BCM)
for led in leds:
  GPIO.setup(led, GPIO.OUT)
  # Set PWM and create some constants we'll be using
  leds[led] = GPIO.PWM(led, 100)

RUNNING = True
WIND = 9

def brightness():
   """Function to randomly set the brightness of the LED between 5 per cent and 100 per cent power"""
   return random.randint(5, 100)

def flicker():
   """Function to randomly set the regularity of the'flicker effect'"""
   return random.random() / WIND

print "Candle Light. Press CTRL + C to quit"

# The main program loop follows.
# Use 'try', 'except' and 'finally' to ensure the program
# quits cleanly when CTRL+C is pressed to stop it.

try:
   for led in leds:
       # Start PWM with the LED off
       leds[led].start(0)
   while RUNNING:
      for led in leds:
          # Randomly change the brightness of the LED
          leds[led].ChangeDutyCycle(brightness())
      # Randomly pause on a brightness to simulate flickering
      time.sleep(flicker())

# If CTRL+C is pressed the main loop is broken
except KeyboardInterrupt:
   running = False
   print "\nQuitting Candle Light"

# Actions under 'finally' will always be called, regardless of
# what stopped the program (be it an error or an interrupt)
finally:
   # Stop and cleanup to finish cleanly so the pins
   # are available to be used again
   for led in leds:
       leds[led].stop()
   GPIO.cleanup()
