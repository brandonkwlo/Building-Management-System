# Libraries
import threading
import RPi.GPIO as GPIO
import time
import requests
import json
import Freenove_DHT as DHT
from datetime import datetime, timedelta
from PCF8574 import PCF8574_GPIO
from Adafruit_LCD1602 import Adafruit_CharLCD

# Setup
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BOARD)

# Constants
AC_POWER = 18
HEAT_POWER = 36
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
l_status = False
dw_status = True
dw_update = False
hvac_update = False
hvac_msg = 'OFF '
terminated = False
humidity = None
weather_index = 0
des_temp = 75
fname = 'log.txt'

GPIO.setup([LED_G,LED_B,LED_R], GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(PIR_SENSOR, GPIO.IN)
GPIO.setup([AC_BTN,HEAT_BTN,SECURE_BTN], GPIO.IN, pull_up_down=GPIO.PUD_UP)
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

def update_energy_cost(power):
	global total_energy_consumed, total_cost
	energy_consumed = power / 3600 
	total_energy_consumed += energy_consumed
	total_cost = (total_energy_consumed * ELECTRICITY_COST) 

'''
def get_hum(hr, curr):
	global humidity
	date_str = ''
	if((hr <= 0) or (curr.hour > time.localtime(time.time()).tm_hour)):
		date_str = datetime.strftime(curr - timedelta(days=1), '%Y-%m-%d')
	else:
		date_str = curr.strftime('%Y-%m-%d')

	url ='http://et.water.ca.gov/api/data?appKey=94c69e9a-5942-4315-9277-d758af3202ec&targets=75&startDate='
	url = url + date_str
	url = url + '&endDate='
	url = url + date_str
	url = url + '&dataItems=hly-rel-hum'
	response_API = requests.get(url)
	data = response_API.text
	parse_json = json.loads(data)
	humidity = parse_json['Data']['Providers'][0]['Records'][hr-1]['HlyRelHum']['Value']
	while(humidity is None):
		hr-=1
		if(hr>0):
			humidity = parse_json['Data']['Providers'][0]['Records'][hr-1]['HlyRelHum']['Value']
		else:
			get_hum(hr,curr)
'''

def check_temp():
	global hvac_msg
	global hvac_update
	global weather_index 
	global des_temp
	global dw_status
	global fname
	old_msg = hvac_msg
	diff = weather_index - des_temp
	if( weather_index <= 95):
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
			GPIO.output([LED_B,LED_R], GPIO.LOW)
	else:
		GPIO.output([LED_B, LED_R, LED_G], GPIO.HIGH)
		time.sleep(1)
		GPIO.output([LED_B, LED_R, LED_G], GPIO.LOW)
		time.sleep(1)
	if(hvac_msg != old_msg):
		hvac_update = True
		f = open(fname, 'a+')
		time_str = datetime.now().strftime('%H:%M:%S')
		time_str = time_str + ' HVAC ' + hvac_msg + '\n'
		f.write(time_str)
		f.close()
	if(hvac_msg == 'AC  '):
		update_energy_cost(AC_POWER)
	if(hvac_msg == 'HEAT'):
		update_energy_cost(HEAT_POWER)
'''
def hum_func():
	global humidity
	global terminated
	init = True
	start_time = time.time()
	while(not terminated):
		if((init) or (time.time() - start_time >= 3600)):
			curr = datetime.now()
			hr = curr.hour
				et_hum(hr, curr)
			init = False
		time.sleep(5)
'''

def dht_func(lock):
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
		humidity = dht.humidity
		w_calc = (sum(t_arr) / 3.0) * 1.8 + 32.0 + 0.05 * float(humidity)
		weather_index= int(w_calc)
		time.sleep(1)

def pir_func(lock):
	global l_status
	global fname
	global terminated
	count = 0
	while(not terminated):
		time.sleep(2)
		if(GPIO.input(PIR_SENSOR) == GPIO.HIGH):
			count = 0
			GPIO.output(LED_G, GPIO.HIGH)
			old_status = l_status
			l_status = True
			time.sleep(10)
			print('Motion detected!')
			if(old_status != l_status):
				f = open(fname, 'a+')
				time_str = datetime.now().strftime('%H:%M:%S')
				time_str = time_str + ' LIGHTS ON\n'
				f.write(time_str)
				f.close()
		else:
			count+=1
			
		if(count==5):
			GPIO.output(LED_G, GPIO.LOW)
			old_status = l_status
			l_status = False
			print('No motion in last 10 seconds')
			if(old_status != l_status):
				f = open(fname, 'a+')
				time_str = datetime.now().strftime('%H:%M:%S')
				time_str = time_str + ' LIGHTS OFF\n'
				f.write(time_str)
				f.close()
			count = 0

def lcd_display():
	global weather_index 
	global des_temp
	global dw_status
	global hvac_msg
	global l_status
	global lcd
	lcd.setCursor(0, 0)
	lcd.message(str(weather_index)+'/'+str(des_temp))
	lcd.message('    D:')
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

def lcd_func(lock):
	global mcp
	global lcd
	global hvac_update
	global dw_update
	global dw_status
	global weather_index 
	global des_temp
	global l_status
	global terminated

	old_status = l_status
	old_des_t = des_temp
	old_hvac_msg = hvac_msg
	old_total_cost = total_cost
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
			lcd.message(hvac_msg)
			time.sleep(2)
			lcd.clear()
			lcd.setCursor(0,0)
			lcd.message('Total kWh: {:.2f}\n'.format(total_energy_consumed))
			lcd.message('  Cost: ${:.2f}'.format(total_cost))
			hvac_update = False
			time.sleep(3)
			lcd.clear()
		elif weather_index > 95:
			lcd.clear()
			lcd.setCursor(0,0)
			lcd.message('  EVACUATE!  \n')
			lcd.message('DOOR/WINDOW OPEN')
			dw_update = False
			hvac_update = False
		else:
			lcd_display()
			time.sleep(0.1)

def handle(pin):
	global des_temp
	global dw_status
	global dw_update
	global fname
	if(pin == SECURE_BTN):
		dw_status = not dw_status
		if(dw_status):
			print('Door/window closed')
			f = open(fname, 'a+')
			time_str = datetime.now().strftime('%H:%M:%S')
			time_str = time_str + ' DOOR/WINDOW SAFE\n'
			f.write(time_str)
			f.close()
		else:
			print('Door/window open')
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

GPIO.add_event_detect(SECURE_BTN, GPIO.RISING, callback=handle, bouncetime=300)
GPIO.add_event_detect(HEAT_BTN, GPIO.RISING, callback=handle, bouncetime=300)
GPIO.add_event_detect(AC_BTN, GPIO.RISING, callback=handle, bouncetime=300)


if __name__ == '__main__':
	try: 
		print('Starting...')
		lock = threading.Lock()
		#hum_t = threading.Thread(target=hum_func)
		#hum_t.start()
		#while(humidity is None):
			#time.sleep(1)
		print('Starting PIR Sensor...')
		dht_t = threading.Thread(target=dht_func, args=(lock,))
		dht_t.start()
		print('Temp Calcuating...')
		time.sleep(3)
		print('Temperature ready')
		lcd_t = threading.Thread(target=lcd_func, args=(lock,))
		lcd_t.start()
		time.sleep(30)
		print('PIR Sensor ready')
		pir_t = threading.Thread(target=pir_func, args=(lock,))
		pir_t.start()
	except KeyboardInterrupt:
		GPIO.cleanup()
