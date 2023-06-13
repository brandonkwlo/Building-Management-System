### Import Python Modules ###
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

### Pin Numbering Declaration (setup channel mode of the Pi to Board values) ###
GPIO.setwarnings(False)		# to disable warnings
GPIO.setmode(GPIO.BOARD)

### Set GPIO pins (for inputs and outputs) and all setups needed based on assignment description ###
LED_G = 40
LED_R = 32 
LED_B = 33
HEAT_BTN = 35
AC_BTN = 37
SECURE_BTN = 31 
PIR_SENSOR = 38
DHTPIN = 11
l_status = False	# Light status (depend on input from PIR) ,false when no person detected
dw_status = True	# Door/window status (True for closed, False for open)
dw_update = False	# Door/window status change displayed or not
hvac_update = False	# HVAC status change displayed or not
hvac_msg = 'OFF '	# HVAC status (off by default, other two are AC and HEAT)
terminated = False
humidity = None		# Humidity (Will be updated by CIMIS data)
curr_temp = 0		# current temperature (Will be updated by DHT)
des_temp = 75		# desired temperature (75 degrees Farenheit by default)
fname = 'log.txt'	# file name

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

def get_hum(hr, curr):
	global humidity
	date_str = ''
	if((hr <= 0) or (curr.hour > time.localtime(time.time()).tm_hour)):
		date_str = datetime.strftime(curr - timedelta(days=1), '%Y-%m-%d')
	else:
		date_str = curr.strftime('%Y-%m-%d')
		
	req_url ='http://et.water.ca.gov/api/data?appKey=94c69e9a-5942-4315-9277-d758af3202ec&targets=75&startDate='
	req_url = req_url + date_str
	req_url = req_url + '&endDate='
	req_url = req_url + date_str
	req_url = req_url + '&dataItems=hly-rel-hum'
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
	global curr_temp
	global des_temp
	global dw_status
	global fname
	old_msg = hvac_msg
	diff = curr_temp - des_temp
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
	global curr_temp
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
		# lock.acquire()
		assert(humidity is not None)
		# print(t_arr)
		m = (sum(t_arr) / 3.0) * 1.8 + 32.0 + 0.05 * float(humidity)
		curr_temp = int(m)
		# lock.release()
		time.sleep(1)
	print('[Main] DHT Thread terminated')

# PIR Sensor Thread
# Due to how this part is implemented, the overhead in updating the variables may result in a small delay when writing the change log
# But the timing of the program is actually correct, which can be verified by the demo video of this project.
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
			# lock.acquire()
			old_status = l_status
			l_status = True
			print('[PIR] Movement detected')
			if(old_status != l_status):
				f = open(fname, 'a+')
				time_str = datetime.now().strftime('%H:%M:%S')
				time_str = time_str + ' LIGHTS ON\n'
				f.write(time_str)
				f.close()
			# lock.release()
		else:
			count += 1
			
		if(count == 5):
			GPIO.output(LED_G, False)
			# lock.acquire()
			old_status = l_status
			l_status = False
			print('[PIR] No movement detected in the past 10 seconds')
			if(old_status != l_status):
				f = open(fname, 'a+')
				time_str = datetime.now().strftime('%H:%M:%S')
				time_str = time_str + ' LIGHTS OFF\n'
				f.write(time_str)
				f.close()
			# lock.release()
			count = 0
	print('[Main] PIR Thread terminated')

def lcd_display():
	global curr_temp
	global des_temp
	global dw_status
	global hvac_msg
	global l_status
	global lcd
	lcd.setCursor(0, 0)
	lcd.message(str(curr_temp)+'/'+str(des_temp))
	lcd.message('   D:')
	if(dw_status):
		lcd.message('SAFE \n')
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
	global curr_temp
	global des_temp
	global l_status
	global terminated
	
	old_status = l_status
	old_des_t = des_temp
	while(not terminated):
		# lock.acquire()
		check_temp()
		# lock.release()
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
			lcd.message(hvac_msg)
			hvac_update = False
			time.sleep(3)
			lcd.clear()
		else:
			# lock.acquire()
			lcd_display()
			# lock.release()
			time.sleep(0.1)
	print('[Main] LCD Thread terminated')

def handle(pin):
	global des_temp
	global dw_status
	global dw_update
	global fname
	if(pin == SECURE_BTN):
		dw_status = not dw_status
		if(dw_status):
			#ADD HVAC turns off
			print('[Main] Door/window closed')
			f = open(fname, 'a+')
			time_str = datetime.now().strftime('%H:%M:%S')
			time_str = time_str + ' DOOR/WINDOW SAFE\n'
			f.write(time_str)
			f.close()
		else:
			print('[Main] Door/window open')
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
		print('[Main] BMS starts')
		lock = threading.Lock()
		curr = datetime.now()
		hr = curr.hour
		print('[Main] CIMIS Thread Start')
		t0 = threading.Thread(target=hum_thread)
		# t0.daemon = True
		t0.start()
		while(humidity is None):
			time.sleep(1)
		print('[Main] Initializing PIR sensor, please allow about 1 minutes to set up')
		t1 = threading.Thread(target=DHT_thread, args=(lock,))
		# t1.daemon = True
		t1.start()
		print('[Main] Waiting for initial temperature being calculated...')
		time.sleep(5)
		print('[Main] Current temperature is ready')
		t2 = threading.Thread(target=lcd_thread, args=(lock,))
		# t2.daemon = True
		t2.start()
		time.sleep(55)
		print('[Main] PIR is ready')
		t3 = threading.Thread(target=PIR_thread, args=(lock,))
		# t3.daemon = True
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
		print('BMS ends')
	except KeyboardInterrupt:
		terminated = True
		t0.join()
		t1.join()
		t2.join()
		t3.join()
		mcp.output(3,0)
		lcd.clear()
		GPIO.cleanup()
		print('BMS ends')
	except:
		terminated = True
		t0.join()
		t1.join()
		t2.join()
		t3.join()
		mcp.output(3,0)
		lcd.clear()
		GPIO.cleanup()
		print('BMS ends')
