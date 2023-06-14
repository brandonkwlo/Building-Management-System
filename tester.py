import threading
import RPi.GPIO as GPIO
import time
import urllib
import json
import Freenove_DHT as DHT
from time import sleep
from urllib.request import urlopen, Request
from PCF8574 import PCF8574_GPIO
from Adafruit_LCD1602 import Adafruit_CharLCD
from datetime import datetime, timedelta

# Setup
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)

# Constants
AC_POWER = 18000
HEAT_POWER = 36000
ELECTRICITY_COST = 0.5

LED_G = 40
LED_R = 32
LED_B = 33
HEAT_BTN = 35
AC_BTN = 37
SECURE_BTN = 31
PIR_SENSOR = 38
DHTPIN = 11

# Variables
total_energy_consumed = 0
total_cost = 0
l_status = False  # Light status (depend on input from PIR), false when no person detected
dw_status = True  # Door/window status (True for closed, False for open)
dw_update = False  # Door/window status change displayed or not
hvac_update = False  # HVAC status change displayed or not
hvac_msg = 'OFF '  # HVAC status (off by default, other two are AC and HEAT)
terminated = False
humidity = None  # Humidity (Will be updated by CIMIS data)
weather_index = 0  # current temperature (Will be updated by DHT)
des_temp = 75  # desired temperature (75 degrees Fahrenheit by default)
fname = 'log.txt'  # file name
emergency_triggered = False

# CIMIS URL Parameters
appKey = '94c69e9a-5942-4315-9277-d758af3202ec'
target = '75'
items = 'hly-rel-hum'

GPIO.setup(LED_G, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(LED_R, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(LED_B, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIR_SENSOR, GPIO.IN)
GPIO.setup(AC_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(HEAT_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(SECURE_BTN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
dht = DHT.DHT(DHTPIN)

PCF8574_address = 0x27  # I2C address of the PCF8574 chip.
PCF8574A_address = 0x3F  # I2C address of the PCF8574A chip.
# Create PCF8574 GPIO adapter.
try:
    mcp = PCF8574_GPIO(PCF8574_address)
except:
    try:
        mcp = PCF8574_GPIO(PCF8574A_address)
    except:
        print('I2C Address Error !')
        exit(1)
# Create LCD, passing in MCP GPIO adapter.
lcd = Adafruit_CharLCD(pin_rs=0, pin_e=2, pins_db=[4, 5, 6, 7], GPIO=mcp)
mcp.output(3, 1)  # Turns on LCD backlight
lcd.begin(16, 2)  # Set LCD mode

# Lock for thread synchronization
lock = threading.Lock()


def update_energy_cost(power, duration):
    global total_energy_consumed, total_cost
    energy_consumed = (power * duration) / 1000  # Convert to kWh
    cost = energy_consumed * ELECTRICITY_COST
    total_energy_consumed += energy_consumed
    total_cost += cost


def get_cimis_data():
    global humidity
    try:
        url = f'http://et.water.ca.gov/api/data?appKey={appKey}&targets={target}&startDate={datetime.now().strftime("%Y-%m-%d")}&endDate={datetime.now().strftime("%Y-%m-%d")}&items={items}'
        response = urlopen(url)
        data = json.loads(response.read())
        humidity = data['Data']['Providers'][0]['Records']['HlyRelHum'][0]['Value']
    except Exception as e:
        print(f'Error retrieving CIMIS data: {e}')


def log_data(log_string):
    with open(fname, 'a') as f:
        f.write(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} - {log_string}\n')


def get_temperature():
    global weather_index
    try:
        dht.readDHT11()
        weather_index = dht.temperature
    except Exception as e:
        print(f'Error retrieving temperature from DHT11: {e}')


def display_info():
    while not terminated:
        with lock:
            # Display temperature and humidity
            lcd.setCursor(0, 0)
            lcd.message(f'Temp: {weather_index}C')
            lcd.setCursor(0, 1)
            lcd.message(f'Humidity: {humidity}%')

            # Display HVAC status
            lcd.setCursor(9, 0)
            lcd.message(f'{hvac_msg}')

            # Display door/window status
            lcd.setCursor(9, 1)
            if dw_status:
                lcd.message('DW: Closed ')
            else:
                lcd.message('DW: Open   ')

            # Update the display every 2 seconds
            sleep(2)
            lcd.clear()


def control_hvac():
    global hvac_update, hvac_msg, terminated
    while not terminated:
        with lock:
            if hvac_update:
                if hvac_msg == 'AC  ':
                    GPIO.output(LED_B, GPIO.HIGH)
                    GPIO.output(LED_R, GPIO.LOW)
                    GPIO.output(LED_G, GPIO.LOW)
                elif hvac_msg == 'HEAT':
                    GPIO.output(LED_B, GPIO.LOW)
                    GPIO.output(LED_R, GPIO.HIGH)
                    GPIO.output(LED_G, GPIO.LOW)
                else:
                    GPIO.output(LED_B, GPIO.LOW)
                    GPIO.output(LED_R, GPIO.LOW)
                    GPIO.output(LED_G, GPIO.HIGH)

                hvac_update = False


def read_pir_sensor():
    global l_status, terminated
    while not terminated:
        l_status = GPIO.input(PIR_SENSOR)
        sleep(0.1)


def read_dw_status():
    global dw_status, dw_update, terminated
    while not terminated:
        new_status = GPIO.input(SECURE_BTN)
        if new_status != dw_status:
            dw_status = new_status
            dw_update = True
        sleep(0.1)


def read_ac_status():
    global hvac_msg, hvac_update, terminated
    while not terminated:
        if GPIO.input(AC_BTN) == GPIO.LOW:
            hvac_msg = 'AC  '
            hvac_update = True
        sleep(0.1)


def read_heat_status():
    global hvac_msg, hvac_update, terminated
    while not terminated:
        if GPIO.input(HEAT_BTN) == GPIO.LOW:
            hvac_msg = 'HEAT'
            hvac_update = True
        sleep(0.1)


def emergency_shutdown():
    global terminated, emergency_triggered
    while not terminated:
        if GPIO.input(SECURE_BTN) == GPIO.LOW:
            emergency_triggered = True
            terminated = True
            GPIO.cleanup()
        sleep(0.1)


def main():
    global terminated, dw_update, hvac_update, emergency_triggered
    get_cimis_data()
    display_thread = threading.Thread(target=display_info)
    control_hvac_thread = threading.Thread(target=control_hvac)
    pir_thread = threading.Thread(target=read_pir_sensor)
    dw_thread = threading.Thread(target=read_dw_status)
    ac_thread = threading.Thread(target=read_ac_status)
    heat_thread = threading.Thread(target=read_heat_status)
    emergency_thread = threading.Thread(target=emergency_shutdown)

    display_thread.start()
    control_hvac_thread.start()
    pir_thread.start()
    dw_thread.start()
    ac_thread.start()
    heat_thread.start()
    emergency_thread.start()

    while not terminated:
        with lock:
            get_temperature()
            log_data(f'Temperature: {weather_index}C, Humidity: {humidity}%')

            if dw_update:
                if dw_status:
                    log_data('Door/Window closed')
                else:
                    log_data('Door/Window opened')
                dw_update = False

            if hvac_update:
                log_data(f'HVAC status changed to {hvac_msg.strip()}')
                hvac_update = False

            if l_status:
                power = AC_POWER if hvac_msg == 'AC  ' else HEAT_POWER
                duration = 1
                update_energy_cost(power, duration)
                log_data(f'Light detected, power: {power}W, duration: {duration}s')

            sleep(1)

    # Emergency shutdown
    if emergency_triggered:
        log_data('Emergency shutdown triggered')


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Program terminated')
    finally:
        GPIO.cleanup()
