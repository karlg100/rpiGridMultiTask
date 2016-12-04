#include "PietteTech_DHT/PietteTech_DHT.h"
#include "blynk/blynk.h"
bool isFirstConnect = true;

// system defines
#define DHTTYPE  DHT22              // Sensor type DHT11/21/22/AM2301/AM2302
#define DHTPIN   4         	    // Digital pin for communications
//#define DHT_SAMPLE_INTERVAL   60000  // Sample every minute
#define DHT_SAMPLE_INTERVAL   10000  // Sample every minute
#define READ_INTERVAL 60000
#define NOTIFICATION_INTERVAL   10000  // How often should we send a push notification?

// Light Sensor power and input pins
#define PHR A0
#define PHRPWR A5
#define SPEAKER D0

// chirp durations
#define LONG_CHIRP 100
#define SHORT_CHIRP 50
#define CHIRP_DELAY 50
#define CHIRP_SLEEP 10000
int lastChirp = 0;

// Blynk output pins
#define BLK_TEMP V1
#define BLK_HUMIDITY V2
#define BLK_DEWPOINT V3
#define BLK_LIGHT V4

#define BLK_DOOR_LAST_OPENED V50
#define BLK_DOOR_LAST_CLOSED V51

#define BLK_DOOR_LED V10
#define BLK_TEMP_LED V11
#define BLK_HUMIDITY_LED V12
#define BLK_FROST_LED V13

#define BLK_TERMINAL V0

// Blynk Virtual input pins
#define BLK_TEMP_ALM_LOW V99
#define BLK_TEMP_ALM_HIGH V100
#define BLK_DOOR_ALM V102

#define BLK_DEBUG_LEVEL V127

// what % of light level is considered the door to be open
#define DOOR_OPEN_LEVEL 50          

//declaration
void dht_wrapper(); // must be declared before the lib initialization

// Lib instantiate
PietteTech_DHT DHT(DHTPIN, DHTTYPE, dht_wrapper);

// globals
WidgetTerminal terminal(BLK_TERMINAL);
//WidgetLCD lcd(V50);
unsigned int DHTnextSampleTime;	    // Next time we want to start sample
bool bDHTstarted;		            // flag to indicate we started acquisition
//int n;                              // counter
int debugLevel = 0;                 // debug level for the terminal output
int doorOpen = 0;                   // dtection flag for the door open
int tempAlarmThreshLow = 9999;      // alarm threshold from blynk
int tempAlarmThreshHigh = 9999;     // alarm threshold from blynk
int doorAlarmThresh = 0;            // alarm threshold from blynk
int humidAlarmThreshHigh = 90;      // alarm threshold from blynk
int blkLastAlarm = 0;
int blkNextAlarm = 0;
int blinkCounter = 0;

char deviceName[255] = "unset";

//this is coming from http://www.instructables.com/id/Datalogging-with-Spark-Core-Google-Drive/?ALLSTEPS
//char resultstr[64]; //String to store the sensor data

//DANGER - DO NOT SHARE!!!!
char auth[255];

char getBlynkID() {
    if ( System.deviceID() == "26003a001747353236343033" )                      // zombie_raptor
        sprintf(auth, "%s", "b8e3678ba54a4810bd0a7e7777c87df5");
    else if ( System.deviceID() == "3c003e001247353236343033")                  // bobcat_cowboy
        sprintf(auth, "%s", "b799f1e0d0b747a881a671f331e3da39");
}
//char auth['26003a001747353236343033'][30] = "b8e3678ba54a4810bd0a7e7777c87df5"; // zombie_raptor
//char auth['3c003e001247353236343033'][30] = "b8e3678ba54a4810bd0a7e7777c87df5"; // bobcat_cowboy


//DANGER - DO NOT SHARE!!!!

// DHT Version
char VERSION[64] = "0.04";

// Blynk input blocks
// pull the current alarm threathold from blynk, and test
BLYNK_WRITE(V99)
{
    char msg[255];
    tempAlarmThreshLow = param.asInt();
    sprintf(msg, "Temp Alarm Low changed to %d", tempAlarmThreshLow);
    terminal.println(msg);
    terminal.flush();

}

// High Temp Alarm Threshold
BLYNK_WRITE(V100)
{
    char msg[255];
    tempAlarmThreshHigh = param.asInt();
    sprintf(msg, "Temp Alarm High changed to %d", tempAlarmThreshHigh);
    terminal.println(msg);
    terminal.flush();
}

// Door Alarm Threshold
BLYNK_WRITE(V102)
{
    char msg[255];
    doorAlarmThresh = param.asInt();
    sprintf(msg, "Door Alarm changed to %d", doorAlarmThresh);
    terminal.println(msg);
    terminal.flush();
}

// reboot button
BLYNK_WRITE(V126)
{
    char msg[255];
    if (param.asInt() == 1) {
        sprintf(msg, "Reboot command received");
        terminal.println(msg);
        terminal.flush();
        System.reset();
    }
}

// safe mode button
BLYNK_WRITE(V125)
{
    char msg[255];
    if (param.asInt() == 1) {
        sprintf(msg, "Switching to safe mode");
        terminal.println(msg);
        terminal.flush();
        System.enterSafeMode();
    }
}

// Debug level slider
BLYNK_WRITE(V127)
{
    char msg[255];
    debugLevel = param.asInt();
    sprintf(msg, "Debug Level changed to %d", debugLevel);
    terminal.println(msg);
    terminal.flush();
}

BLYNK_CONNECTED() // runs every time Blynk connection is established
{
    digitalWrite(D7, LOW);
    if (isFirstConnect) {
        // Request server to re-send latest values for all pins
        Blynk.syncAll();
        isFirstConnect = false;
    }
}

BLYNK_DISCONNECTED() // runs every time Blynk connection is established
{
    digitalWrite(D7, HIGH);
}

STARTUP(
    WiFi.selectAntenna(ANT_AUTO)   // Auto select antenna for best coverage
    );

void handler(const char *topic, const char *data) {
    if (debugLevel >= 0) terminal.println("received " + String(topic) + ": " + String(data));
    strcpy(deviceName, data);
    //Particle.publish("debug", deviceName, 60, PRIVATE);
}

void setup()
{
    pinMode(D7, OUTPUT);
    digitalWrite(D7, HIGH);

    Time.zone(-4);                   // Eastern Time Zone
    //Serial.begin(9600);
    getBlynkID();
    Blynk.begin(auth);

    DHTnextSampleTime = 0;  // Start the first sample immediately
    //Particle.variable("result", resultstr, STRING);

    Particle.publish("DHT22 - firmware version", VERSION, 60, PRIVATE);
 
    //lcd.clear();

    // setup the photoresistor
    pinMode(PHR, INPUT);
    pinMode(PHRPWR, OUTPUT);
    pinMode(SPEAKER, OUTPUT);
    digitalWrite(PHRPWR, HIGH);

  // reset alarm times
    blkLastAlarm = 0;
    blkNextAlarm = 0;
    lastChirp = 0;
/*
    for (int i=0; i++; i>10) {
        digitalWrite(D7, HIGH);
        delay(500);
        digitalWrite(D7, LOW);
        delay(500);
    }

    while (!Blynk.connected())
      delay(100);
*/
    delay(5000);
    Particle.subscribe("spark/", handler);
    Particle.publish("spark/device/name");

    // get our name from the Cloud
}

// This wrapper is in charge of calling
// must be defined like this for the lib work
void dht_wrapper() {
  DHT.isrCallback();
}

// Blynk sleep function, better than using delay()
void blynkDelay(int sleepFor) {
  int duration = millis() + sleepFor;
  while (millis() < duration)
    Blynk.run();
}

float blynkHumid(int pin) {
    char tempInChar[32];
    char msg[255];
    float humid = (float)DHT.getHumidity();
    sprintf(tempInChar,"%0.2f", humid);
    sprintf(msg, "Humidity %s%%", tempInChar);
    if (debugLevel >= 2) terminal.println(msg);
    Blynk.virtualWrite(pin, tempInChar);
}

float blynkTemp(int pin) {
    char tempInChar[32];
    char msg[255];
    float temp = (float)DHT.getFahrenheit();
    sprintf(tempInChar,"%0.2f", temp);
    sprintf(msg, "Temperature %sF", tempInChar);
    if (debugLevel >= 2) terminal.println(msg);
    Blynk.virtualWrite(pin, tempInChar);
    return temp;
}

float blynkDewPoint(int pin) {
    char tempInChar[32];
    char msg[255];
    // Dew Point
    float dewPoint = (float)DHT.getDewPoint();
    sprintf(tempInChar,"%0.2f", dewPoint);
    sprintf(msg, "Dew Point %sF", tempInChar);
    if (debugLevel >= 2) terminal.println(msg);
    Blynk.virtualWrite(pin, tempInChar);
    return dewPoint;
}

int lightLevel() {
    int lightLevel = round(analogRead(PHR)*100/4096);
    return lightLevel;
}

int blynkLightLevel(int pin) {
    char tempInChar[32];
    char msg[255];
    int lightSensor = lightLevel();
    sprintf(tempInChar,"%d", lightSensor);
    sprintf(msg, "Light Level %s%%", tempInChar);
    if (debugLevel >= 2) terminal.println(msg);
    Blynk.virtualWrite(pin, tempInChar);
    return lightSensor;
}

void checkDoor(int lightSensor) {
    char msg[255];
    if (lightSensor > DOOR_OPEN_LEVEL) {
        if (doorOpen == 0) {
            strncpy(msg, Time.timeStr(), sizeof(Time.timeStr()-1));
            sprintf(msg, "Door Opened %s", msg);
            if (debugLevel >= 2) terminal.println(msg);
            Blynk.virtualWrite(BLK_DOOR_LAST_OPENED, Time.format(Time.now(), TIME_FORMAT_DEFAULT));
            doorOpen = millis();
        }
    } else if (doorOpen > 0) {
        strncpy(msg, Time.timeStr(), sizeof(Time.timeStr()-1));
        sprintf(msg, "Door Closed %s", msg);
    if (debugLevel >= 2) terminal.println(msg);
        Blynk.virtualWrite(BLK_DOOR_LAST_CLOSED, Time.format(Time.now(), TIME_FORMAT_DEFAULT));
        doorOpen = 0;
    }
}

bool blynkNotify(char msg[255]) {
    char msg2[255], msg3[255];
    sprintf(msg3, "%s : %s", deviceName, msg);
    if (Blynk.connected()) {
        if (millis() < blkNextAlarm) {
            sprintf(msg2, "blynkNotify() - waitng for next time window %d < %d", millis(), blkNextAlarm);
            if (debugLevel >= 1) terminal.println(msg2);
        } else {
            Blynk.notify(msg3);
            sprintf(msg2, "blynkNotify() - notification sent");
            if (debugLevel >= 1) terminal.println(msg2);
        }
        return true;
    } else {
        return false;
    }
}


void doChirp(int cycles) {
    char msg[255];
    if (millis() > lastChirp)
        return;
    sprintf(msg, "doChirp(%d) - %d", cycles, lastChirp);
    if (debugLevel >= 4) terminal.println(msg);
    digitalWrite(SPEAKER, HIGH);
    delay(LONG_CHIRP);
    digitalWrite(SPEAKER, LOW);
    for (int i=0; i<cycles; i++) {
        delay(CHIRP_DELAY);
        digitalWrite(SPEAKER, HIGH);
        delay(SHORT_CHIRP);
        digitalWrite(SPEAKER, LOW);
        delay(LONG_CHIRP);
    }
}

void checkAlarms(float temp) {
    char msg[255];
    bool alarmState = false;
    //sprintf(msg, "checkAlarms() - start - %d %d", millis(), blkNextAlarm);
    //if (debugLevel >= 0) terminal.println(msg);
    sprintf(msg, "checkAlarms() - alarm check time");
    if (debugLevel >= 1) terminal.println(msg);
    if (doorOpen > 0 && (millis()-doorOpen)/1000 > (float)doorAlarmThresh) {
        sprintf(msg, "Door has been open for %d seconds", round((millis()-doorOpen)/1000));
        if (debugLevel >= 0) terminal.println(msg);
        doChirp(1);
        alarmState = blynkNotify(msg);
    }
    if (temp <= (float)tempAlarmThreshLow) {
        sprintf(msg, "Temperature is too low! %0.2f F < %d F", temp, tempAlarmThreshLow);
        if (debugLevel >= 0) terminal.println(msg);
        doChirp(2);
        alarmState = blynkNotify(msg);
    }
    if (temp >= (float)tempAlarmThreshHigh) {
        sprintf(msg, "Temperature is too high! %0.2f F > %d F", temp, tempAlarmThreshHigh);
        if (debugLevel >= 0) terminal.println(msg);
        doChirp(3);
        alarmState = blynkNotify(msg);
    }
    if (alarmState == true) {
        if (blkNextAlarm < millis()) {
            blkLastAlarm = millis();
            blkNextAlarm = millis()+1000*60*30;
        }
        if (millis() > lastChirp) lastChirp = millis() + CHIRP_SLEEP;
        sprintf(msg, "checkAlarms() - alarm state true, vars %d %d", blkLastAlarm, blkNextAlarm);
        if (debugLevel >= 1) terminal.println(msg);
    } else {
        blkLastAlarm = 0;
        blkNextAlarm = 0;
        if (debugLevel >= 1) terminal.println("checkAlarms() - no alarm states or blynk not connected");
    }
}

void controlDoorLED(int light) {
    if (light > DOOR_OPEN_LEVEL)
        Blynk.virtualWrite(BLK_DOOR_LED, 1023);
    else
        Blynk.virtualWrite(BLK_DOOR_LED, 0);
}

void controlSensorLEDs(float temp, float humid, float dewPoint) {
    if (temp >= tempAlarmThreshHigh)
        Blynk.virtualWrite(BLK_TEMP_LED, 1023);
    else
        Blynk.virtualWrite(BLK_TEMP_LED, 0);

    if (temp <= tempAlarmThreshLow)
        Blynk.virtualWrite(BLK_TEMP_LED, 1023);
    else
        Blynk.virtualWrite(BLK_TEMP_LED, 0);

    if (humid >= humidAlarmThreshHigh)
        Blynk.virtualWrite(BLK_HUMIDITY_LED, 1023);
    else
        Blynk.virtualWrite(BLK_HUMIDITY_LED, 0);

    if (temp <= dewPoint)
        Blynk.virtualWrite(BLK_FROST_LED, 1023);
    else
        Blynk.virtualWrite(BLK_FROST_LED, 0);
}

void loop() {
    char msg[255];
    char tempInChar[32];
    float temp, humid, dewPoint, lightSensor;

    if (debugLevel >= 4) { sprintf(msg, "loop() - Start - %d", millis()); terminal.println(msg); }
    Blynk.run(); // all the Blynk magic happens here

    // Check if we need to start the next sample
    if (millis() > DHTnextSampleTime) {
	    if (!bDHTstarted) {		// start the sample
            if (debugLevel >= 2) terminal.println("loop() - DHT Sampling");
	        DHT.acquire();
	        bDHTstarted = true;
	    }

        if (!DHT.acquiring()) {		// has sample completed?
            if (debugLevel >= 2) terminal.println("loop() - DHT sample acquiried");
            temp = blynkTemp(BLK_TEMP);
            humid = blynkHumid(BLK_HUMIDITY);
            dewPoint = blynkDewPoint(BLK_DEWPOINT);
            bDHTstarted = false;  // reset the sample flag so we can take another
            DHTnextSampleTime = millis() + DHT_SAMPLE_INTERVAL;  // set the time for next sample
            controlSensorLEDs(temp, humid, dewPoint);
            // check Alarm threatholds and send if notificaiton if there's an alarm state
            checkAlarms(temp);
        } else {
            sprintf(msg, "loop() - DHT no sample");
            if (debugLevel >= 2) terminal.println(msg);
        }

        lightSensor = blynkLightLevel(BLK_LIGHT);

        //Blynk.virtualWrite(V50, Time.format(Time.now(), TIME_FORMAT_DEFAULT));
        //Blynk.virtualWrite(V51, Time.format(Time.now(), TIME_FORMAT_DEFAULT));
        checkDoor(lightSensor);
        controlDoorLED(lightSensor);

        sprintf(msg,"doorOpen %d - %d seconds", doorOpen, round((millis()-doorOpen)/1000));
        if (debugLevel >= 3) terminal.println(msg);
        sprintf(msg,"tempAlarmThreshHigh %d F", tempAlarmThreshHigh);
        if (debugLevel >= 3) terminal.println(msg);
        sprintf(msg,"tempAlarmThreshLow %d F", tempAlarmThreshLow);
        if (debugLevel >= 3) terminal.println(msg);
        sprintf(msg,"doorAlarmThresh %d seconds", doorAlarmThresh);
        if (debugLevel >= 3) terminal.println(msg);
    }

/*
    while (blynkLightLevel(BLK_LIGHT) < DOOR_OPEN_LEVEL && DHTnextSampleTime < millis() && doorOpen == 0) {
        int sleepFor = DHTnextSampleTime - millis();
        sprintf(msg, "No light detected, Next attempt in %d milliseconds", sleepFor);
        if (debugLevel >= 3) terminal.println(msg);
        terminal.flush();
        blynkDelay(100);
    }
    */
    if (lightLevel() > DOOR_OPEN_LEVEL)
        DHTnextSampleTime = millis();
        //sprintf(msg, "Light detected [%0.1f] or door marked open, sample now", lightSensor);
        //if (debugLevel == 1) terminal.println(msg);
        //DHTnextSampleTime = millis();
        //blynkDelay(100);
      //}

    terminal.flush();
    blynkDelay(1000);
}
