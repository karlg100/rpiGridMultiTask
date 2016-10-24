#!/usr/bin/python

import ephem

import time
import datetime

now = datetime.datetime.now()
now = "2016-07-25 01:00:00"

#Make an observer
fred      = ephem.Observer()

#PyEphem takes and returns only UTC times. 15:00 is noon in Fredericton
fred.date = now

#Location of Fredericton, Canada
fred.lon  = str(-71.627986) #Note that lon should be in string format
fred.lat  = str(42.608492)  #Note that lat should be in string format

# 14 Westview Street - 42.608492, -71.627986

#Elevation of Fredericton, Canada, in metres
fred.elev = 324

#To get U.S. Naval Astronomical Almanac values, use these settings
fred.pressure= 0
fred.horizon = '-0:34'

sunrise=fred.previous_rising(ephem.Sun()) #Sunrise
noon   =fred.next_transit   (ephem.Sun(), start=sunrise) #Solar noon
sunset =fred.next_setting   (ephem.Sun()) #Sunset

print sunrise
print noon
print sunset

#We relocate the horizon to get twilight times
fred.horizon = '-6' #-6=civil twilight, -12=nautical, -18=astronomical
beg_twilight=fred.next_rising(ephem.Sun(), use_center=True) #Begin civil twilight
end_twilight=fred.previous_setting   (ephem.Sun(), use_center=True) #End civil twilight

print "now: %s" % now
print "next rising: %s" % beg_twilight
print "next setting: %s" % fred.next_setting(ephem.Sun())
print "NR is lt NS : %s" % (fred.next_rising(ephem.Sun())<fred.next_setting(ephem.Sun()))

print "time to next settng: %s" % (fred.next_setting(ephem.Sun())-datetime.datetime.strptime(now, "%Y-%m-%d %H:%M:%S")).total_seconds()
#print "time to next rising: %s" % (fred.next_rising(ephem.Sun())-now).total_seconds()

