#include "application.h"

//#define BLYNK_DEBUG // Optional, this enables lots of prints
//#define BLYNK_PRINT Serial

// Setup an app watchdog to reset if loop hangs on mqtt
ApplicationWatchdog wd(120000, System.reset);

// This #include statement was automatically added by the Particle IDE.
#include <vector>

#include <blynk.h>

#include <neopixel.h> // use for Build IDE

// This #include statement was automatically added by the Particle IDE.
#include <MQTT.h>
void callback(char* topic, uint8_t* payload, unsigned int length);

/**
 * if want to use IP address,
 * byte server[] = { XXX,XXX,XXX,XXX };
 * MQTT client(server, 1883, callback);
 * want to use domain name,
 * MQTT client("www.sample.com", 1883, callback);
 **/
// recieve mqtt message

void updateGraveYardR(int r);
void updateGraveYardG(int g);
void updateGraveYardB(int b);
void updateGraveYardFade();
bool stripOn = true;
bool startleCommanded = false;
//int reconnectTimer = 0;

void callback(char* topic, uint8_t* payload, unsigned int length) {
    char p[length + 1];
    memcpy(p, payload, length);
    p[length] = NULL;
    int r,g,b;
    String sTopic(topic);
    String message(p);

    Serial.println(topic);
    Serial.println(message);

    if (sTopic.equals("graveyard/color/r")) {
        r = atoi(message.c_str());
        updateGraveYardR(r);
    } else if (sTopic.equals("graveyard/color/g")) {
        g = atoi(message.c_str());
        updateGraveYardG(g);
    } else if (sTopic.equals("graveyard/color/b")) {
        b = atoi(message.c_str());
        updateGraveYardB(b);
    } else if (sTopic.equals("graveyard/command") && message.equals("go")) {
        updateGraveYardFade();
    } else if (sTopic.equals("graveyard/command") && message.equals("on")) {
        stripOn = true;
    } else if (sTopic.equals("graveyard/command") && message.equals("off")) {
        stripOn = false;
    } else if (sTopic.equals("ghosts/command") && message.equals("startle")) {
        startleCommanded = true;
    } else if (sTopic.equals("graveyard/command") && message.equals("reset")) {
        System.reset();
    }
}

//uint8_t mqtt_server[] = { 192,168,001,234 };
uint8_t mqtt_server[] = { 192,168,001,166 };

//IPAddress mqtt_serverIP(mqtt_server[0], mqtt_server[1], mqtt_server[2], mqtt_server[4]);
MQTT client(mqtt_server, 1883, callback);



/* ======================= prototypes =============================== */

void colorAll(Adafruit_NeoPixel* strip, int r, int g, int b, uint8_t wait);
void colorWipe(uint32_t c, uint8_t wait);
void rainbow(uint8_t wait);
void rainbowCycle(uint8_t wait);
uint32_t Wheel(Adafruit_NeoPixel* strip, byte WheelPos);

/* ======================= extra-examples.cpp ======================== */

// IMPORTANT: Set pixel COUNT, PIN and TYPE
#define PIXEL_PIN D0
#define PIXEL_TYPE WS2812B

// Setup the LEDs
// Ghost tree
#define PIXEL_COUNT1 30
#define PIXEL_PIN1 D0
Adafruit_NeoPixel strip0 = Adafruit_NeoPixel(PIXEL_COUNT1, PIXEL_PIN1, PIXEL_TYPE);

// Cemetary
#define PIXEL_COUNT2 30
#define PIXEL_PIN2 D1
Adafruit_NeoPixel strip1 = Adafruit_NeoPixel(PIXEL_COUNT2, PIXEL_PIN2, PIXEL_TYPE);

// Paralax Imact sensor
#define IMPACT_INPUT D4
int ledOffset[] = {0, 0};          // keep track of next LED in the stack

//void fade(int duration, Color )
// modes for the cluster classes
#define C_DELAY 0
#define C_FADE 1
#define C_SPOOK 2

class Ghost {
    private:
        int startPxl = 0;
        int size = 0;
        unsigned long delay = 0;
        int r, g, b;
        int prvR, prvB, prvG;
        int nxtR, nxtB, nxtG;
        unsigned long fadeDuration = 0;
        int fadeLength = 0;
        int mode;
        Adafruit_NeoPixel* strip;

        void randColor() {
            r = random(0,255);
            g = random(0,255);
            b = random(0,255);
        }

        void randNextColor() {
            nxtR = random(0,255);
            nxtG = random(0,255);
            nxtB = random(0,255);
            prvR = r;
            prvG = g;
            prvB = b;
            fadeLength = random(1000, 10000);
            fadeDuration = millis() + fadeLength;
        }

        void colorCluster() {
            for (int x = startPxl; x<startPxl+size; x++) {
                strip->setPixelColor(x,r,g,b);
            }
            //strip.show();
        }

        void doFade() {
            //char msg[25];
            float progress = fadeDuration-millis();
            float pct = 1-((progress)/fadeLength);
            //Serial.print("fadeDuration : ");
            //Serial.println(fadeDuration);
            //Serial.print("pct : ");
            //Serial.println(pct);
            //sprintf(msg, "(%d - %d)/%d=%f", fadeDuration, millis(), fadeLength, pct);
            //Serial.println(msg);
            r = int(prvR + int((nxtR - prvR)*pct));
            //sprintf(msg, "p:%d n:%d sub:%d step:%d", prvR, nxtR, prvR-nxtR, int((nxtR - prvR)*pct));
            //Serial.println(msg);
            g = int(prvG + int((nxtG - prvG)*pct));
            b = int(prvB + int((nxtB - prvB)*pct));
            colorCluster();
        }

        void checkState() {
            //Serial.println("check state started");
            if (mode == C_SPOOK) {
                if (millis() > delay) {
                    mode=C_DELAY;
                    delay = millis() + random(500, 3000);
                } else {
                    randColor();
                    colorCluster();
                }
            } else if (mode == C_FADE) {
                digitalWrite(D7, HIGH);
                if (millis() > fadeDuration) {                  // if we are done fading, pause for up to 5 seconds
                    //Serial.print("fade mode reset ");
                    mode = C_DELAY;
                    delay = millis() + random(500, 3000);
                    r = nxtR;
                    g = nxtG;
                    b = nxtB;
                } else {                                        // we are fading, calcuate next color to move to and do it
                //Serial.println("fading");
                    doFade();
                }
            } else if (mode == C_DELAY && millis() > delay) {           // if we are done pausing, set next random color and duration
                mode = C_FADE;
                randNextColor();
                delay = 0;
            } else if (mode == C_DELAY) {
                digitalWrite(D7, LOW);
//                Serial.println("waiting for delay to pass");
//                Serial.print("waiting for delay to pass : ");
//                Serial.print(millis());
//                Serial.print(" < ");
//                Serial.print(delay);
            }
        }

    public:

        void startle() {
            //Serial.println("Ghost Startled!");
            mode = C_SPOOK;
            randColor();
            delay = millis()+random(10,500);
            colorCluster();
        }

        Ghost(Adafruit_NeoPixel* tmpstrip, int id, int num) {
            //Serial.println("Ghost Defined");
            strip = tmpstrip;
            startPxl = ledOffset[id];
            size = num;
            ledOffset[id] += num;
            startle();
        }
        
//            strip.setPixelColor(x,r1,g1, b1);

        void run() {
            checkState();
        }
};

class Tree {
    private:
        int startPxl = 0;
        int size = 0;
        int r = 255;
        int g = 255;
        int b = 255;
        Adafruit_NeoPixel* strip;

        void colorCluster() {
            for (int x = startPxl; x<startPxl+size; x++) {
                strip->setPixelColor(x,r,g,b);
            }
            //strip.show();
        }

    public:
    
        Tree(Adafruit_NeoPixel* tmpstrip, int id, int num) {
            strip = tmpstrip;
            startPxl = ledOffset[id];
            size = num;
            ledOffset[id] += num;
            colorCluster();
        }

        void run() {
            colorCluster();
        }
};


class Pumpkin {
    private:
        unsigned long startPxl = 0;
        int size = 0;
        int r = 255;
        int g = r-40;
        int b = 40;
        int origR = r;
        int origG = g;
        int origB = b;
        int prvR, prvB, prvG;
        int nxtR, nxtB, nxtG;
        bool fade = false;
        unsigned long fadeDuration = 0;
        int fadeLength = 0;
        unsigned long nextChange = 0;
        unsigned long idleTimer = 0;
        unsigned long idleLength = 300000;
        std::vector<int> sleepPxl;
        unsigned long flickerTimer = 0;
        Adafruit_NeoPixel* strip;

        void colorCluster() {
            for (int x = startPxl; x<startPxl+size; x++) {
                strip->setPixelColor(x,r,g,b);
            }
            //strip.show();
        }

        void doFade() {
            //char msg[25];
            float progress = fadeDuration-millis();
            float pct = 1-((progress)/fadeLength);
            //Serial.print("fadeDuration : ");
            //Serial.println(fadeDuration);
            //Serial.print("pct : ");
            //Serial.println(pct);
            //sprintf(msg, "(%d - %d)/%d=%f", fadeDuration, millis(), fadeLength, pct);
            //Serial.println(msg);
            r = int(prvR + int((nxtR - prvR)*pct));
            //sprintf(msg, "p:%d n:%d sub:%d step:%d", prvR, nxtR, prvR-nxtR, int((nxtR - prvR)*pct));
            //Serial.println(msg);
            g = int(prvG + int((nxtG - prvG)*pct));
            b = int(prvB + int((nxtB - prvB)*pct));
            colorCluster();
            //client.publish("graveyard/debug","doFade - fading");
        }

        void candle() {
            //int r = 255;        // r
            //int g = r-40;       // g
            //int b = 40;         // b

            if (flickerTimer < millis()) {
                for (int x = startPxl; x<startPxl+size; x++) {
                //if (millis() > sleepPxl[x-startPxl]) {
                    //int flicker = random(0,40);
                    int flicker = random(0,150);
                    int r1 = r-flicker;
                    int g1 = g-flicker;
                    int b1 = b-flicker;
                    if(g1<0) g1=0;
                    if(r1<0) r1=0;
                    if(b1<0) b1=0;
                    strip->setPixelColor(x,r1,g1, b1);
//                    sleepPxl[x-startPxl] = millis()+random(0,40);
                }
            flickerTimer = millis()+random(0,40);
            }
        }

    public:
        Pumpkin(Adafruit_NeoPixel* tmpstrip, int id, int num) {
            strip = tmpstrip;
            startPxl = ledOffset[id];
            size = num;
            ledOffset[id] += num;
            sleepPxl.resize(num);
            colorCluster();
        }

        void triggerFade(bool external = true) {
            fadeLength = random(500, 3000);
            fadeDuration = millis() + fadeLength;
            if (external)
                idleTimer = millis();
        }
        
        void changeColorR(int newR) {
            //client.publish("graveyard/debug","new R");
            prvR = r;
            nxtR = newR;
        }

        void changeColorG(int newG) {
            //client.publish("graveyard/debug","new G");
            prvG = g;
            nxtG = newG;
        }


        void changeColorB(int newB) {
            //client.publish("graveyard/debug","new B");
            prvB = b;
            nxtB = newB;
        }

        void run(bool fade = true) {
            if (fade) {
                if (millis() < fadeDuration) {                  // if we are done fading, pause for up to 5 seconds
                    doFade();
                }

                // if we haven't changed color in a long time, let's choose a new one    
                if ( (millis() > idleLength && idleTimer < millis()-idleLength) && nextChange < millis()) {
                    client.publish("graveyard/debug","choosing new random color");
                    changeColorR(random(0,255));
                    changeColorG(random(0,255));
                    changeColorB(random(0,255));
                    nextChange=millis()+random(500,5000);
                    triggerFade(false);
                }
            }

            candle();
        }
};

/*
// Other globals
bool isFirstConnect = true;

BLYNK_CONNECTED() // runs every time Blynk connection is established
{
    digitalWrite(D7, LOW);
    Blynk.syncAll();

//    if (isFirstConnect) {
//        // Request server to re-send latest values for all pins
//        isFirstConnect = false;
//    }
}

BLYNK_DISCONNECTED() // runs every time Blynk connection is established
{
    digitalWrite(D7, HIGH);
}

BLYNK_WRITE(V10)
{
    stripOn = param.asInt();
    Serial.print("strip power : ");
    Serial.println(stripOn);
}
*/

int turnOn(String extra) {
    stripOn = true;
    return 1;
}

int turnOff(String extra) {
    stripOn = false;
    return 1;
}

void toggleOnOff() {
    stripOn = !stripOn;
    Blynk.virtualWrite(V10, stripOn);
}
/*
void randomColor() {
    for(int x = 0; x <= PIXEL_COUNT; x++) {
        if (millis() > sleepPxl[x]) {
            int flicker = random(0,150);
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

void slowFade(int startPx, int endPx, int r, int g, int b) {
    for(int x = startPx; x <= endPx; x++) {
}
*/

// Set all pixels in the strip to a solid color, then wait (ms)
void colorAll(Adafruit_NeoPixel* strip, int r, int g, int b, uint8_t wait) {
  uint16_t i;

  for(i=0; i<strip->numPixels(); i++) {
    strip->setPixelColor(i, r, g, b);
  }
  strip->show();
  delay(wait);
}

// Input a value 0 to 255 to get a color value.
// The colours are a transition r - g - b - back to r.
uint32_t Wheel(Adafruit_NeoPixel* strip, byte WheelPos) {
  if(WheelPos < 85) {
   return strip->Color(WheelPos * 3, 255 - WheelPos * 3, 0);
  } else if(WheelPos < 170) {
   WheelPos -= 85;
   return strip->Color(255 - WheelPos * 3, 0, WheelPos * 3);
  } else {
   WheelPos -= 170;
   return strip->Color(0, WheelPos * 3, 255 - WheelPos * 3);
  }
}

int runCount = 0;
int showCount = 0;

// declaire the clusters
// Halloween Treel
Ghost* Ghost1;
Ghost* Ghost2;
//Ghost* Tree1;
Tree* Tree1;
Tree* Tree2;
Pumpkin* Pumpkin1;

// Cemetary
Pumpkin* TombStone1;
Pumpkin* TombStone2;
Pumpkin* TombStone3;
Pumpkin* TombStone4;
Pumpkin* TombStone5;
Pumpkin* TombStone6;

void runStuff() {
    if (stripOn) {
        Ghost1->run();
        Ghost2->run();
        Tree1->run();
        Tree2->run();
        Pumpkin1->run(false);
        TombStone1->run();
        TombStone2->run();
        TombStone3->run();
        TombStone4->run();
        TombStone5->run();
        TombStone6->run();
    } else {
        colorAll(&strip0, 0,0,0,0);
        colorAll(&strip1, 0,0,0,0);
    }
    //runCount++;
}

void checkSoundSensor() {
    bool soundState = digitalRead(IMPACT_INPUT);
    if ((soundState || startleCommanded) && stripOn) {
        client.publish("ghosts","startled");
        Ghost1->startle(); 
        Ghost2->startle();
        startleCommanded = false;
    }
}

void updateGraveYardR(int r) {
    TombStone1->changeColorR(r);
    TombStone2->changeColorR(r);
    TombStone3->changeColorR(r);
    TombStone4->changeColorR(r);
    TombStone5->changeColorR(r);
    TombStone6->changeColorR(r);
}

void updateGraveYardG(int g) {
    TombStone1->changeColorG(g);
    TombStone2->changeColorG(g);
    TombStone3->changeColorG(g);
    TombStone4->changeColorG(g);
    TombStone5->changeColorG(g);
    TombStone6->changeColorG(g);
}

void updateGraveYardB(int b) {
    TombStone1->changeColorB(b);
    TombStone2->changeColorB(b);
    TombStone3->changeColorB(b);
    TombStone4->changeColorB(b);
    TombStone5->changeColorB(b);
    TombStone6->changeColorB(b);
}

void updateGraveYardFade() {
    TombStone1->triggerFade();
    TombStone2->triggerFade();
    TombStone3->triggerFade();
    TombStone4->triggerFade();
    TombStone5->triggerFade();
    TombStone6->triggerFade();
}

void showStrip() {
    strip0.show();
    strip1.show();
    //showCount++;
}

void showDebug() {
    //char msg[50];

    int fps;
    char msg[50];
    fps = runCount / (millis()/1000);
    sprintf(msg, "fireFPS: %d", fps);
    client.publish("graveyard/debug",msg);
    fps = showCount / (millis()/1000);
    sprintf(msg, "showFPS: %d", fps);
    client.publish("graveyard/debug",msg);

/*
    int fps;
    fps = runCount / (millis()/1000);
    Serial.print("runFPS : ");
    Serial.println(fps);
    fps = showCount / (millis()/1000);
    Serial.print("showFPS : ");
    Serial.println(fps);
    //Serial.print("ghostMode : ");
    //Serial.println(Ghost1->mode);
    */
    //sprintf(msg, "last run %d", millis()-runLast);
    //client.publish("graveyard/debug", msg);
    //runLast = millis();
}

Timer runStuffTimer(10, runStuff);
Timer runStripTimer(10, showStrip);
Timer runSoundTimer(25, checkSoundSensor);
Timer showDebugTimer(1000, showDebug);


void setup() {
    Serial.begin(115200);
    pinMode(D7, OUTPUT);
    digitalWrite(D7, LOW);

    uint32_t seed = HAL_RNG_GetRandomNumber();
    srand(seed);

    while (!Particle.connected()) {
        Serial.println("waiting for cloud connection");
        delay(100);
    }

    // Explose functions for ITTT support for sunset/sunrise
    Particle.function("turnOn", turnOn);
    Particle.function("turnOff", turnOff);

    static String auth = "6af3495c11694752b9cd2e683e857b34";
    //Blynk.begin(auth);
    strip0.begin();
    strip1.begin();
    colorAll(&strip0, 255,255,255, 1000);
    colorAll(&strip1, 255,255,255, 1000);
    strip0.show(); // Initialize all pixels to 'off'
    strip1.show(); // Initialize all pixels to 'off'

    // setup input pin for sound impact sensor
    pinMode(IMPACT_INPUT, INPUT);

    // define the clusters
    // Halloween Treel
    Pumpkin1 = new Pumpkin(&strip0, 0, 6);
    Tree1 = new Tree(&strip0, 0, 6);
    //Tree1 = new Ghost(&strip0, 0, 6);
    Ghost1 = new Ghost(&strip0, 0, 6);
    Tree2 = new Tree(&strip0, 0, 3);
    Ghost2 = new Ghost(&strip0, 0, 6);

    // cemetary
    TombStone1 = new Pumpkin(&strip1, 1, 3);
    TombStone2 = new Pumpkin(&strip1, 1, 3);
    TombStone3 = new Pumpkin(&strip1, 1, 3);
    TombStone4 = new Pumpkin(&strip1, 1, 3);
    TombStone5 = new Pumpkin(&strip1, 1, 3);
    TombStone6 = new Pumpkin(&strip1, 1, 3);

    // connect to the server
    client.connect("halloweentree");
    // publish/subscribe
    client.publish("graveyard/debug","rebooted - setup() ran");
    if (client.isConnected()) {
        client.subscribe("graveyard/color/#");
        client.subscribe("graveyard/command");
        client.subscribe("ghosts/command");
        digitalWrite(D7, LOW);
    }
/*
*/

    runSoundTimer.start();
    runStuffTimer.start();
    runStripTimer.start();
    //showDebugTimer.start();
}

void loop() {
    //Blynk.run();

    if (WiFi.ready()) {
        if (client.isConnected()) {
            client.loop();
        } else {
//            if (Network.ping(mqtt_serverIP)) {
//            digitalWrite(D7, HIGH);
            Serial.println("mqtt disconnected, rebooting");
//            system.reset();
            client.disconnect();
            client.connect("halloweentree");

            if (client.isConnected()) {
                client.subscribe("graveyard/color/#");
                client.subscribe("graveyard/command");
                client.subscribe("ghosts/command");
                client.publish("graveyard/debug","reconnected");
                digitalWrite(D7, LOW);
            }
//            } else {
//                Serial.println("mqtt server unreachable");
        }
    }
//    }
}




