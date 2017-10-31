#include "application.h"

// Setup an app watchdog to reset if loop hangs on mqtt
ApplicationWatchdog wd(120000, System.reset);

// This #include statement was automatically added by the Particle IDE.
#include <MQTT.h>
void callback(char* topic, uint8_t* payload, unsigned int length);

//#define BLYNK_DEBUG // Optional, this enables lots of prints
//#define BLYNK_PRINT Serial

// This #include statement was automatically added by the Particle IDE.
//#include <blynk.h>

/*-------------------------------------------------------------------------
  Spark Core, Particle Photon, P1, Electron and RedBear Duo library to control
  WS2811/WS2812 based RGB LED devices such as Adafruit NeoPixel strips.

  Supports:
  - 800 KHz and 400kHz bitstream WS2812, WS2812B and WS2811
  - 800 KHz bitstream SK6812RGBW (NeoPixel RGBW pixel strips)
    (use 'SK6812RGBW' as PIXEL_TYPE)

  Also supports:
  - Radio Shack Tri-Color Strip with TM1803 controller 400kHz bitstream.
  - TM1829 pixels

  PLEASE NOTE that the NeoPixels require 5V level inputs
  and the Spark Core, Particle Photon, P1, Electron and RedBear Duo only
  have 3.3V level outputs. Level shifting is necessary, but will require
  a fast device such as one of the following:

  [SN74HCT125N]
  http://www.digikey.com/product-detail/en/SN74HCT125N/296-8386-5-ND/376860

  [SN74HCT245N]
  http://www.digikey.com/product-detail/en/SN74HCT245N/296-1612-5-ND/277258

  Written by Phil Burgess / Paint Your Dragon for Adafruit Industries.
  Modified to work with Particle devices by Technobly.
  Contributions by PJRC and other members of the open source community.

  Adafruit invests time and resources providing this open source code,
  please support Adafruit and open-source hardware by purchasing products
  from Adafruit!
  --------------------------------------------------------------------*/

/* ======================= includes ================================= */

#include <neopixel.h> // use for Build IDE
// #include "neopixel.h" // use for local build

/* ======================= prototypes =============================== */

void colorAll(uint32_t c, uint8_t wait);
uint32_t Wheel(byte WheelPos);

bool stripOn = true;
bool isFirstConnect = true;

int r = 25;       // r
int g = 7;        // g
int b = 0;        // b

int prvR, prvB, prvG;
int nxtR, nxtB, nxtG;
unsigned long fadeDuration = 0;
unsigned long fadeLength = 0;

//uint8_t mqtt_server[] = { 192,168,001,234 };
uint8_t mqtt_server[] = { 192,168,001,166 };
//IPAddress mqtt_serverIP(mqtt_server[0], mqtt_server[1], mqtt_server[2], mqtt_server[4]);
MQTT client(mqtt_server, 1883, callback);


/* ======================= extra-examples.cpp ======================== */

/**
 * if want to use IP address,
 * byte server[] = { XXX,XXX,XXX,XXX };
 * MQTT client(server, 1883, callback);
 * want to use domain name,
 * MQTT client("www.sample.com", 1883, callback);
 **/
// recieve mqtt message
void callback(char* topic, uint8_t* payload, unsigned int length) {
    char p[length + 1];
    memcpy(p, payload, length);
    p[length] = NULL;
    String sTopic(topic);
    String message(p);

    Serial.println(topic);
    Serial.println(message);

    if (sTopic.equals("front_lights/color/r")) {
        nxtR = atoi(message.c_str());
        client.publish("front_lights/debug/nextR", "set");
    } else if (sTopic.equals("front_lights/color/g")) {
        nxtG = atoi(message.c_str());
        client.publish("front_lights/debug/nextG", "set");
    } else if (sTopic.equals("front_lights/color/b")) {
        nxtB = atoi(message.c_str());
        client.publish("front_lights/debug/nextB", "set");
    } else if (sTopic.equals("front_lights/command") && message.equals("go")) {
        prvR = r;
        prvG = g;
        prvB = b;
        fadeLength = random(2000, 5000);
        fadeDuration = millis() + fadeLength;
    } else if (sTopic.equals("front_lights/command") && message.equals("on")) {
        stripOn = true;
    } else if (sTopic.equals("front_lights/command") && message.equals("off")) {
        stripOn = false;
    }
}


// IMPORTANT: Set pixel COUNT, PIN and TYPE
#define PIXEL_COUNT 632
#define PIXEL_PIN D0
#define PIXEL_TYPE WS2812B
#define IMPACT_INPUT D6


unsigned long sleepPxl[PIXEL_COUNT] = {0};

// Parameter 1 = number of pixels in strip
//               note: for some stripes like those with the TM1829, you
//                     need to count the number of segments, i.e. the
//                     number of controllers in your stripe, not the number
//                     of individual LEDs!
// Parameter 2 = pin number (most are valid)
//               note: if not specified, D2 is selected for you.
// Parameter 3 = pixel type [ WS2812, WS2812B, WS2812B2, WS2811,
//                             TM1803, TM1829, SK6812RGBW ]
//               note: if not specified, WS2812B is selected for you.
//               note: RGB order is automatically applied to WS2811,
//                     WS2812/WS2812B/WS2812B2/TM1803 is GRB order.
//
// 800 KHz bitstream 800 KHz bitstream (most NeoPixel products
//               WS2812 (6-pin part)/WS2812B (4-pin part)/SK6812RGBW (RGB+W) )
//
// 400 KHz bitstream (classic 'v1' (not v2) FLORA pixels, WS2811 drivers)
//                   (Radio Shack Tri-Color LED Strip - TM1803 driver
//                    NOTE: RS Tri-Color LED's are grouped in sets of 3)

Adafruit_NeoPixel strip = Adafruit_NeoPixel(PIXEL_COUNT, PIXEL_PIN, PIXEL_TYPE);

// IMPORTANT: To reduce NeoPixel burnout risk, add 1000 uF capacitor across
// pixel power leads, add 300 - 500 Ohm resistor on first pixel's data input
// and minimize distance between Arduino and first pixel.  Avoid connecting
// on a live circuit...if you must, connect GND first.

int turnOn(String extra) {
    stripOn = true;
    client.publish("front_lights/debug","turnOn()");
    return 1;
}

int turnOff(String extra) {
    stripOn = false;
    client.publish("front_lights/debug","turnOff()");
    return 1;
}

void toggleOnOff() {
    stripOn = !stripOn;
    client.publish("front_lights/debug","toggle on/off triggered");
}

void randomColor() {
    for(int x = 0; x <= PIXEL_COUNT; x++) {
        if (millis() > sleepPxl[x]) {
            int flicker = random(0,40);
            int r1 = r-flicker;
            int g1 = g-flicker;
            int b1 = b-flicker;
            if(g1<0) g1=0;
            if(r1<0) r1=0;
            if(b1<0) b1=0;
            strip.setPixelColor(x,r1,g1, b1);
            sleepPxl[x] = millis()+random(40,150);
            //sleepPxl[x] = millis()+10000;
        }
    }
    strip.show();
}

void doFade() {
    char msg[25];
    float progress = fadeDuration-millis();
    float pct = 1-((progress)/fadeLength);
    //Serial.print("fadeDuration : ");
    //Serial.println(fadeDuration);
    //Serial.print("pct : ");
    //Serial.println(pct);
 
 /*
    sprintf(msg, "(%d - %d)/%d=%f", fadeDuration, millis(), fadeLength, pct);
    client.publish("front_lights/debug", msg);
    //Serial.println(msg);
    sprintf(msg, "p:%d n:%d sub:%d step:%d", prvR, nxtR, prvR-nxtR, int((nxtR - prvR)*pct));
    //Serial.println(msg);
    client.publish("front_lights/debug", msg);
    sprintf(msg, "current: r:%d g:%d b:%d", r, g, b);
    client.publish("front_lights/debug", msg);
*/
    r = int(prvR + int((nxtR - prvR)*pct));
    g = int(prvG + int((nxtG - prvG)*pct));
    b = int(prvB + int((nxtB - prvB)*pct));
}

void fire() {
    //int r = 255;        // r
    //int g = r-40;       // g
    //int b = 40;         // b

    for(int x = 0; x <= PIXEL_COUNT; x++) {
//        if (millis() > sleepPxl[x]) {
            int flicker = random(0,90);
            int r1 = r-flicker;
            int g1 = g-flicker;
            int b1 = b-flicker;
            if(g1<0) g1=0;
            if(r1<0) r1=0;
            if(b1<0) b1=0;
            strip.setPixelColor(x,r1,g1, b1);
//            sleepPxl[x] = millis()+random(0,40);
//        }
    }
//    strip.show();
}

// Set all pixels in the strip to a solid color, then wait (ms)
void colorAll(uint32_t c, uint8_t wait) {
  uint16_t i;

  for(i=0; i<strip.numPixels(); i++) {
    strip.setPixelColor(i, c);
  }
  strip.show();
  delay(wait);
}

// Input a value 0 to 255 to get a color value.
// The colours are a transition r - g - b - back to r.
uint32_t Wheel(byte WheelPos) {
  if(WheelPos < 85) {
   return strip.Color(WheelPos * 3, 255 - WheelPos * 3, 0);
  } else if(WheelPos < 170) {
   WheelPos -= 85;
   return strip.Color(255 - WheelPos * 3, 0, WheelPos * 3);
  } else {
   WheelPos -= 170;
   return strip.Color(0, WheelPos * 3, 255 - WheelPos * 3);
  }
}

int fireCount = 0;
int showCount = 0;
void runFire() {
  if (stripOn) {
    if (fadeLength > 0 && millis() < fadeDuration) {                  // if we are done fading, pause for up to 5 seconds
        doFade();
    } else if (fadeLength > 0) {
        prvR = r;
        prvG = g;
        prvB = b;
        nxtR = r;
        nxtG = g;
        nxtB = b;
        fadeLength = 0;
        fadeDuration = 0;
    }
    fire();
  } else {
    colorAll(0,0);
  }
  fireCount++;
}

void showStrip() {
    strip.show();
    showCount++;
}

void showDebug() {
    int fps;
    char msg[50];
    fps = fireCount / (millis()/1000);
    sprintf(msg, "fireFPS: %d", fps);
    client.publish("front_lights/debug",msg);
    fps = showCount / (millis()/1000);
    sprintf(msg, "showFPS: %d", fps);
    client.publish("front_lights/debug",msg);
    sprintf(msg, "current: r:%d g:%d b:%d", r, g, b);
    client.publish("front_lights/debug", msg);
    sprintf(msg, "current: nxtR:%d nxtG:%d nxtB:%d", nxtR, nxtG, nxtB);
    client.publish("front_lights/debug", msg);
}

Timer runFireTimer(25, runFire);
Timer runStripTimer(25, showStrip);
Timer showDebugTimer(1000, showDebug);

void setup() {
    Serial.begin(115200);
    //pinMode(D7, OUTPUT);
    //digitalWrite(D7, HIGH);

    // Explose functions for ITTT support for sunset/sunrise
    Particle.function("turnOn", turnOn);
    Particle.function("turnOff", turnOff);

    static String auth = "2bdc601d328e4c7f9c22ca34135c847d";
    strip.begin();
    strip.show(); // Initialize all pixels to 'off'
    runFireTimer.start();
    runStripTimer.start();
    showDebugTimer.start();

    // connect to the server
    client.connect("front_lights");
    // publish/subscribe
    client.publish("front_lights/debug","rebooted - setup() ran");
    if (client.isConnected()) {
        client.subscribe("front_lights/color/#");
        client.subscribe("front_lights/command");
    }
}

void loop() {
    //Blynk.run();
    if (WiFi.ready()) {
        if (client.isConnected()) {
            client.loop();
        } else {
            //System.reset();
//            if (Network.ping(mqtt_serverIP)) {
            Serial.println("mqtt disconnected, rebooting");
            client.disconnect();
            client.connect("front_lights");
            if (client.isConnected()) {
                client.subscribe("front_lights/color/#");
                client.subscribe("front_lights/command");
                client.publish("front_lights/debug","reconnected");
            }
//            } else {
//                Serial.println("mqtt server unreachable");
//            }

        }
    }
}



