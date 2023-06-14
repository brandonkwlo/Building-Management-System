# Libraries
import threading
import RPi.GPIO as GPIO
from datetime import datetime, timedelta
import time
from urllib.request import urlopen, Request
import urllib
import json
from PCF8574 import PCF8574_GPIO
from Adafruit_LCD1602 import Adafruit_CharLCD
import Freenove_DHT as DHT

# Setup
GPIO.setwarnings(False)		
GPIO.setmode(GPIO.BOARD)

LED_G = 40
LED_R = 32 
LED_B = 33
HEAT_BTN = 35
AC_BTN = 37
SECURE_BTN = 31 
PIR_SENSOR = 38
DHTPIN = 11

# Constants
AC_POWER = 18000
HEAT_POWER = 36000
ELECTRICITY_COST = 0.5

# Variables
total_energy_consumed = 0
total_cost = 0
l_status = False	# Light status (depend on input from PIR) ,false when no person detected
dw_status = True	# Door/window status (True for closed, False for open)
dw_update = False	# Door/window status change displayed or not
dw_msg = 'SAFE'     # Door/window status message (default is 'SAFE' for closed)
hvac_update = False	# HVAC status change displayed or not
hvac_msg = 'OFF '	# HVAC status (off by default, other two are AC and HEAT)
terminated = False
humidity = None		# Humidity (Will be updated by CIMIS data)
weather_index = 0		# current temperature (Will be updated by DHT)
des_temp = 75		# desired temperature (75 degrees Farenheit by default)
fname = 'log.txt'	# file name

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
        print ('I2C Address Error !')
        exit(1)
# Create LCD, passing in MCP GPIO adapter.
lcd = Adafruit_CharLCD(pin_rs=0, pin_e=2, pins_db=[4,5,6,7], GPIO=mcp)
mcp.output(3, 1) # Turns on lcd backlight
lcd.begin(16, 2) # Set lcd mode

# Update energy consumption and cost
def update_energy_cost(power, duration):
	global total_energy_consumed, total_cost
	energy_consumed = (power * duration) / 1000 # Convert watt-seconds to kWh
	total_energy_consumed += energy_consumed
	total_cost = total_energy_consumed * ELECTRICITY_COST


def get_hum(hr, curr):
	global humidity
	date_str = ''
	if((hr <= 0) or (curr.hour > time.localtime(time.time()).tm_hour)):
		date_str = datetime.strftime(curr - timedelta(days=1), '%Y-%m-%d')
	else:
		date_str = curr.strftime('%Y-%m-%d')
		
	req_url ='http://et.water.ca.gov/api/data?appKey='+appKey+'&targets='+target+'&startDate='
	req_url = req_url+date_str+'&endDate='+date_str+'&dataItems='+items
	print('[CIMIS] URL ready')
	content = None
	data = None
	req = Request(req_url, headers={"Accept": "application/json"})
	try: 
		print('[CIMIS] Start requesting')
		content = urlopen(req)
		assert(content is not None)
		
	except urllib.error.HTTPError as e:
		print('[CIMIS] Failed to resolve HTTP request')
		msg = e.read()
		print(msg)
	except urllib.error.URLError:
		print('[CIMIS] Failed to access CIMIS database')
	except:
		print('[CIMIS] CIMIS data request is rejected')
	data = json.load(content)
	assert(data is not None)
	# print(data)
	hly_data = data['Data']['Providers'][0]['Records']
	humidity = hly_data[hr - 1]['HlyRelHum']['Value']
	# Continue running unless a valid humidity reading is found
	while(humidity is None):
		hr -= 1
		if (hr > 0):
			humidity = hly_data[hr - 1]['HlyRelHum']['Value']
		else:
			get_hum(hr, curr)
	print('[CIMIS] Successfully retrieve local humidity')
	print('[CIMIS] Local humidity is: ', humidity)

# Check temperature difference
def check_temp():
	global hvac_msg
	global hvac_update
	global weather_index
	global des_temp
	global dw_status
	global fname
	old_msg = hvac_msg
	diff = weather_index - des_temp
	if((diff >= 3) and (dw_status)):
		hvac_msg = 'AC  '
		GPIO.output(LED_B, GPIO.HIGH)
		GPIO.output(LED_R, GPIO.LOW)
	elif((diff <= -3) and (dw_status)):
		hvac_msg = 'HEAT'
		GPIO.output(LED_B, GPIO.LOW)
		GPIO.output(LED_R, GPIO.HIGH)
	else:
		hvac_msg = 'OFF '
		GPIO.output(LED_B, GPIO.LOW)
		GPIO.output(LED_R, GPIO.LOW)
	if(hvac_msg != old_msg):
		hvac_update = True
		f = open(fname, 'a+')
		time_str = datetime.now().strftime('%H:%M:%S')
		time_str = time_str + ' HVAC ' + hvac_msg + '\n'
		f.write(time_str)
		f.close()
	if (hvac_msg == 'AC  '):
		update_energy_cost(AC_POWER, 1)
	elif (hvac_msg == 'HEAT'):
		update_energy_cost(HEAT_POWER, 1)
		
def hum_thread():
	global humidity
	global terminated
	init = True
	start_time = time.time()
	while(not terminated):
		if((init) or (time.time() - start_time >= 3600)):
			curr = datetime.now()
			hr = curr.hour
			get_hum(hr, curr)
			init = False
		time.sleep(5)
	print('[Main] CIMIS Thread terminated')
		
def DHT_thread(lock):
	global weather_index
	global des_temp
	global humidity
	global terminated
	t_init = True
	i = 0
	t_arr = [0, 0, 0]
	while(not terminated):
		for j in range (0, 15):
			chk = dht.readDHT11()
			if(chk is dht.DHTLIB_OK):
				break
			time.sleep(0.1)
		t_arr[i] = dht.temperature
		if(i == 2):
			i = 0
		else:
			i += 1
		assert(humidity is not None)
		m = (sum(t_arr) / 3.0) * 1.8 + 32.0 + 0.05 * float(humidity) #weather index calc
		weather_index = int(m)
		time.sleep(1)
	print('[Main] DHT Thread terminated')

def PIR_thread(lock):
	count = 0
	global l_status
	global fname
	global terminated
	print('[Main] PIR thread starts')
	while(not terminated):
		time.sleep(2)
		if(GPIO.input(PIR_SENSOR) == GPIO.HIGH):
			count = 0
			GPIO.output(LED_G, True)
			old_status = l_status
			l_status = True
			print('[PIR] Movement detected')
			if(old_status != l_status):
				f = open(fname, 'a+')
				time_str = datetime.now().strftime('%H:%M:%S')
				time_str = time_str + ' LIGHTS ON\n'
				f.write(time_str)
				f.close()
		else:
			count += 1
			
		if(count == 5):
			GPIO.output(LED_G, False)
			old_status = l_status
			l_status = False
			print('[PIR] No movement detected in the past 10 seconds')
			if(old_status != l_status):
				f = open(fname, 'a+')
				time_str = datetime.now().strftime('%H:%M:%S')
				time_str = time_str + ' LIGHTS OFF\n'
				f.write(time_str)
				f.close()
			count = 0
	print('[Main] PIR Thread terminated')

def lcd_display():
	global weather_index
	global des_temp
	global dw_status
	global hvac_msg
	global l_status
	global lcd
	global dw_msg

	lcd.setCursor(0, 0)
	lcd.message(str(weather_index)+'/'+str(des_temp))
	lcd.message('   D:')

	if(dw_status):
		lcd.message(dw_msg)
	else:
		lcd.message('OPEN \n')
	lcd.message('H:')
	lcd.message(hvac_msg)
	lcd.message('    L:')
	if(l_status):
		lcd.message('ON ')
	else:
		lcd.message('OFF')

def lcd_thread(lock):
	global mcp
	global lcd
	global hvac_update
	global dw_update
	global dw_status
	global weather_index
	global des_temp
	global l_status
	global terminated
	global dw_msg

	old_hvac_msg = hvac_msg #new
	old_total_cost = total_cost #new
	old_status = l_status
	old_des_t = des_temp
	while(not terminated):
		check_temp()
		if(dw_update):
			lcd.clear()
			lcd.setCursor(0,0)
			if(dw_status):
				lcd.message('DOOR/WINDOW SAFE\n')
				lcd.message('   HVAC RESUMED')
			else:
				lcd.message('DOOR/WINDOW OPEN\n')
				lcd.message('   HVAC HALTED')
			dw_update = False
			hvac_update = False
			time.sleep(3)
			lcd.clear()
		elif(hvac_update):
			lcd.clear()
			lcd.setCursor(0,0)
			lcd.message('  HVAC ')
			lcd.setCursor(0,1)
			lcd.message('Total kWh: {:.2f}'.format(total_energy_consumed))
			lcd.message('  Cost: {:.2f}'.format(total_cost))
			hvac_update = False
			time.sleep(3)
			lcd.clear()
		else:
			lcd_display()
			time.sleep(0.1)
	print('[Main] LCD Thread terminated')

def display_warning():
    lcd.clear()
    lcd.message('DOOR/WINDOW OPEN!\n')
    lcd.message('HVAC OFF')
    time.sleep(3)
    lcd.clear()
    
def handle(pin):
	global des_temp
	global dw_status
	global dw_update
	global fname

	if(pin == SECURE_BTN):
		dw_status = not dw_status
		if(dw_status):
			print('[Main] Door/window closed')
			dw_msg = 'SAFE'  # Update the door/window status message
			f = open(fname, 'a+')
			time_str = datetime.now().strftime('%H:%M:%S')
			time_str = time_str + ' DOOR/WINDOW SAFE\n'
			f.write(time_str)
			f.close()
		else:
			print('[Main] Door/window open')
			dw_msg = 'OPEN'  # Update the door/window status message
			f = open(fname, 'a+')
			time_str = datetime.now().strftime('%H:%M:%S')
			time_str = time_str + ' DOOR/WINDOW OPEN\n'
			f.write(time_str)
			f.close()
		dw_update = True
	elif(pin == AC_BTN):
		if(des_temp > 65):
			des_temp -= 1
	elif(pin == HEAT_BTN):
		if(des_temp < 95):
			des_temp += 1


# Button events detection
GPIO.add_event_detect(SECURE_BTN, GPIO.RISING, callback=handle, bouncetime=300)
GPIO.add_event_detect(HEAT_BTN, GPIO.RISING, callback=handle, bouncetime=300)
GPIO.add_event_detect(AC_BTN, GPIO.RISING, callback=handle, bouncetime=300)

	
if __name__ == '__main__':
	try: 
		print('Starting....')
		# line below prevents race conditions and ensures thread safety
		lock = threading.Lock()
		print('CIMIS Thread Start')
		t0 = threading.Thread(target=hum_thread)
		t0.start()
		while(humidity is None):
			time.sleep(1)
		print('Initializing PIR sensor....')
		t1 = threading.Thread(target=DHT_thread, args=(lock,))
		t1.start()
		print('Temperature being calculated....')
		time.sleep(5)
		print('Current temperature is ready')
		t2 = threading.Thread(target=lcd_thread, args=(lock,))
		t2.start()
		time.sleep(55)
		print('PIR is ready')
		t3 = threading.Thread(target=PIR_thread, args=(lock,))
		t3.start()
		msg = input('[Main] Press <Enter> key to exit the program: \n')
		terminated = True
		t0.join()
		t1.join()
		t2.join()
		t3.join()
		mcp.output(3,0)
		lcd.clear()
		GPIO.cleanup()
		print('END')
	except KeyboardInterrupt:
		terminated = True
		t0.join()
		t1.join()
		t2.join()
		t3.join()
		mcp.output(3,0)
		lcd.clear()
		GPIO.cleanup()
		print('END')

