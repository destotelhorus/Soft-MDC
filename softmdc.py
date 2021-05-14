import websocket
try:
    import thread
except ImportError:
    import _thread as thread
import time
import json
import argparse
import sys
from pyMIZFile.MIZFile import MIZFile
import inquirer
from inquirer.themes import GreenPassion
from datetime import datetime
import math
import os

sent_mdc = False
address_buffer = 0
count_buffer = 0
data_buffer = 0
state = "WAIT_FOR_SYNC"
sync_byte_count = 0
debug_packages = False

switch_addr = 0x4424
switch_mask = 0x0030
switch_shift = 4
switch_triggerval = 0

mdc = None

key_sleep = 0.2

parser = argparse.ArgumentParser(description='Loads MDC/DTC data into the F-16 through DCS-BIOS.')
parser.add_argument('mdcfile', help='json file with mdc/dtc data for the F-16', default=argparse.SUPPRESS, nargs='?')
parser.add_argument('-e', '--extractfrom', help='if specified will export flightdata from the specified MIZfile', nargs='?')

args = parser.parse_args()

def extractfrom(file, target):
    sourceMIZ = MIZFile(file, True)
    mission = sourceMIZ.getMission()
    
    groups = []
    for coalition_idx, coalition in mission["coalition"].items():
        if coalition_idx != 'blue':
            continue
        for country_idx, country in coalition["country"].items():
            for unittype in ["plane"]:
                if not unittype in country:
                    continue
                for group_idx, group in country[unittype]["group"].items():
                    if ( len(group["units"]) > 0 ) and ( list(group["units"].values())[0]["skill"] == "Client" ):
                        groups.append(group["name"])
                        
    flightquestion = [
        inquirer.Text(name='mission', message='Mission name', default=file),
        inquirer.Text(name='creator', message='MDC creator', default=os.getenv('username')),
        inquirer.Text(name='date', message='MDC date', default=datetime.today().strftime('%Y-%m-%d')),       
        inquirer.List(name='flight',
                      message="Flight to export waypoints from",
                      choices=groups,
                     ),
        inquirer.Text(name='alow', message='ALOW: alow'),
        inquirer.Text(name='msl_floor', message='ALOW: msl floor'),
        inquirer.Text(name='bingo', message='Bingo')
    ]
    flightanswer = inquirer.prompt(flightquestion, theme=GreenPassion())

    exportflight = None
    for coalition_idx, coalition in mission["coalition"].items():
        if coalition_idx != 'blue':
            continue
        for country_idx, country in coalition["country"].items():
            for unittype in ["plane"]:
                if not unittype in country:
                    continue
                for group_idx, group in country[unittype]["group"].items():
                    if group["name"] == flightanswer['flight']:
                        exportflight = group
    
    exportjson = {}
    exportjson['mission'] = flightanswer['mission']
    exportjson['creator'] = flightanswer['creator']
    exportjson['date'] = flightanswer['date']
    exportjson['data'] = {}
    exportjson['data']['waypoints'] = {}
    exportjson['data']['alow'] = {}
    if not hasattr(flightanswer, 'alow') and flightanswer['alow'] != None and flightanswer['alow'] != "":
        exportjson['data']['alow']['alow'] = flightanswer['alow']
    if not hasattr(flightanswer, 'msl_floor') and flightanswer['msl_floor'] != None and flightanswer['msl_floor'] != "":
        exportjson['data']['alow']['msl_floor'] = flightanswer['msl_floor']
    if not hasattr(flightanswer, 'bingo') and flightanswer['bingo'] != None and flightanswer['bingo'] != "":
        exportjson['data']['bingo'] = flightanswer['bingo']
    
    
    for waypoint_idx, waypoint in group["route"]["points"].items():
        lat, lon = sourceMIZ.getProjectedLatLon(waypoint['x'], waypoint['y'])
        lat_d = math.floor(lat)
        lat_m = round(lat%1*60*1000)
        lon_d = math.floor(lon)
        lon_m = round(lon%1*60*1000)
        exportjson['data']['waypoints'][waypoint_idx] = {}
        exportjson['data']['waypoints'][waypoint_idx]['ns'] = ('s','n')[lat_d >= 0]
        exportjson['data']['waypoints'][waypoint_idx]['lat_d'] = abs(lat_d)
        exportjson['data']['waypoints'][waypoint_idx]['lat_m'] = lat_m
        exportjson['data']['waypoints'][waypoint_idx]['we'] = ('w','e')[lat_d >= 0]
        exportjson['data']['waypoints'][waypoint_idx]['lon_d'] = abs(lon_d)
        exportjson['data']['waypoints'][waypoint_idx]['lon_m'] = lon_m
        exportjson['data']['waypoints'][waypoint_idx]['altitude'] = math.floor(waypoint['alt']*3.28084)
    
    with open(target, 'w') as outfile:
        json.dump(exportjson, outfile)

def process_byte(byte):
    global debug_packages
    global state
    global address_buffer
    global count_buffer
    global data_buffer
    global sync_byte_count
    
    if debug_packages:
        print("Processing ",hex(byte), " State is ", state, " address_buffer is ", hex(address_buffer))

    if state == "WAIT_FOR_SYNC":
        pass
        
    elif state == "ADDRESS_LOW":
        address_buffer = ( 0xff00 & address_buffer ) | (0xff & byte)
        state = "ADDRESS_HIGH"
        
    elif state == "ADDRESS_HIGH":
        address_buffer = ( byte << 8 ) | (0xff & address_buffer)
        if ( address_buffer & 0xffff ) != 0x5555:
            state = "COUNT_LOW"
        else:
            state = "WAITING_FOR_SYNC"
        
    elif state == "COUNT_LOW":
        count_buffer = ( 0xff00 & count_buffer ) | (0xff & byte)
        state = "COUNT_HIGH"
        
    elif state == "COUNT_HIGH":
        count_buffer = ( byte << 8 ) | (0xff & count_buffer)
        state = "DATA_LOW"
        
    elif state == "DATA_LOW":
        data_buffer = ( 0xff00 & data_buffer ) | (0xff & byte)
        count_buffer = (count_buffer & 0xffff) -1
        state = "DATA_HIGH"
    
    elif state == "DATA_HIGH":
        data_buffer = ( byte << 8 ) | (0xff & data_buffer)
        count_buffer = (count_buffer & 0xffff) -1
        process_addr_notification(address_buffer & 0xffff, data_buffer & 0xffff)
        address_buffer = (address_buffer & 0xffff) + 2
        if (count_buffer & 0xffff) == 0:
            state = "ADDRESS_LOW"
        else:
            state = "DATA_LOW"

    if (0xff & byte) == 0x55:
        sync_byte_count = sync_byte_count+1
    else:
        sync_byte_count = 0
    
    if sync_byte_count == 4:
        state = "ADDRESS_LOW"
        sync_byte_count = 0
            
def process_addr_notification(address, data):
    global debug_packages
    global switch_addr
    global switch_mask
    global switch_shift
    global switch_triggerval
    global sent_mdc
    
    if debug_packages:
        print("data for address: ", hex(address & 0xffff), " data: ",  hex(data & 0xffff))

    if address == switch_addr:
        switch_pos = (data & switch_mask) >> switch_shift
        if (sent_mdc == False) and (switch_pos == switch_triggerval):
            send_mdc()

def send_reset_icp():
    send_reset_icp_once()
    send_reset_icp_once()
    
def send_reset_icp_once():
    send('{"datatype":"input_command","data":"ICP_DATA_RTN_SEQ_SW 0"}')
    send('{"datatype":"input_command","data":"ICP_DATA_RTN_SEQ_SW 1"}')

def enter_uhf():
    send_toggle('{"datatype":"input_command","data":"ICP_COM1_BTN TOGGLE"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')

def enter_vhf():
    send_toggle('{"datatype":"input_command","data":"ICP_COM2_BTN TOGGLE"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')

def enter_alow():
    send_digit(2)

def enter_bingo():
    send_toggle('{"datatype":"input_command","data":"ICP_LIST_BTN TOGGLE"}')
    send_digit(2)
    
def enter_tgp():
    send_toggle('{"datatype":"input_command","data":"ICP_LIST_BTN TOGGLE"}')
    send_digit(0)
    send_digit(5)

def send(json):
    global key_sleep
    
    ws.send(json)
    time.sleep(key_sleep)
    
def send_toggle(json):
    global key_sleep
    
    ws.send(json)
    time.sleep(key_sleep)
    ws.send(json)
    time.sleep(key_sleep)
    
def send_digit(number):
    json = ""
    if number == 0:
        json = '{"datatype":"input_command","data":"ICP_BTN_0 TOGGLE"}'
    elif number == 1:
        json = '{"datatype":"input_command","data":"ICP_BTN_1 TOGGLE"}'
    elif number == 2:
        json = '{"datatype":"input_command","data":"ICP_BTN_2 TOGGLE"}'
    elif number == 3:
        json = '{"datatype":"input_command","data":"ICP_BTN_3 TOGGLE"}'
    elif number == 4:
        json = '{"datatype":"input_command","data":"ICP_BTN_4 TOGGLE"}'
    elif number == 5:
        json = '{"datatype":"input_command","data":"ICP_BTN_5 TOGGLE"}'
    elif number == 6:
        json = '{"datatype":"input_command","data":"ICP_BTN_6 TOGGLE"}'
    elif number == 7:
        json = '{"datatype":"input_command","data":"ICP_BTN_7 TOGGLE"}'
    elif number == 8:
        json = '{"datatype":"input_command","data":"ICP_BTN_8 TOGGLE"}'
    elif number == 9:
        json = '{"datatype":"input_command","data":"ICP_BTN_9 TOGGLE"}'
    else:
        return
    
    send_toggle(json)
    
def send_common(channel, frequency):
    if channel > 20 or channel < 1:
        return
    
    send_number(channel, 1, 20)
    send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')
    
    output = False
    
    if frequency // 10000 != 0:
        output = True
        send_digit(frequency // 10000)
        frequency = frequency % 10000
    if output or frequency // 1000 != 0:
        output = True
        send_digit(frequency // 1000)
        frequency = frequency % 1000
    if output or frequency // 100 != 0:
        output = True
        send_digit(frequency // 100)
        frequency = frequency % 100
    if output or frequency // 10 != 0:
        output = True
        send_digit(frequency // 10)
        frequency = frequency % 10
    send_digit(frequency)
    send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 2"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')

def send_number(number, minv, maxv):
    number = int(number)
    if number < minv or number > maxv:
        return
        
    for ch in str(number):
        send_digit(int(ch))

def send_uhf(channel, frequency):
    print("Sending UHF channel", channel, "as", frequency)
    send_common(channel, frequency)
    
def send_vhf(channel, frequency):
    print("Sending VHF channel", channel, "as", frequency)
    send_common(channel, frequency)

def send_waypoint(number, data):
    print("Sending waypoint", number)
    
    if number > 30 or number < 1:
        return
    send_digit(4)
    send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
    send_number(number, 1, 30)
    send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
    
    #lat
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')
    if data['ns'] == 'n':
        send_digit(2)
    else:
        send_digit(8)
    latd = int(data['lat_d'])
    send_digit(latd // 10)
    send_digit(latd % 10)
    
    #lat decimal minutes
    latm = int(data['lat_m'])
    send_digit(latm // 10000)
    latm = latm % 10000
    send_digit(latm // 1000)
    latm = latm % 1000
    send_digit(latm // 100)
    latm = latm % 100
    send_digit(latm // 10)
    latm = latm % 10
    send_digit(latm)
    send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
    
    #lng
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
    send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')
    if data['we'] == 'w':
        send_digit(4)
    else:
        send_digit(6)
    lond = int(data['lon_d'])
    send_digit(lond // 100)
    lond = lond % 100
    send_digit(lond // 10)
    send_digit(lond % 10)
    
    #lon decimal minutes    
    lonm = int(data['lon_m'])
    send_digit(lonm // 10000)
    lonm = lonm % 10000
    send_digit(lonm // 1000)
    lonm = lonm % 1000
    send_digit(lonm // 100)
    lonm = lonm % 100
    send_digit(lonm // 10)
    lonm = lonm % 10
    send_digit(lonm)
    send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}') 

    #altitude
    if 'altitude' in data:
        send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
        send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')
        send_number(data['altitude'], 1, 35000)
        send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}') 
        
    send_reset_icp_once()
    

def send_mdc():
    global sent_mdc
    global mdc
    
    print("Sending MDC to plane ...")
    
    def run(*args):
        sleep_duration = 0.01
        
        send_reset_icp()
        
        if 'waypoints' in mdc['data'] and len(mdc['data']['waypoints']) > 0:
            for number, data in mdc['data']['waypoints'].items():
                send_waypoint(int(number), data)
        
        if 'uhf' in mdc['data'] and len(mdc['data']['uhf']) > 0:
            enter_uhf()
            for channel, freq in mdc['data']['uhf'].items():
                send_uhf(int(channel), int(freq))
            send_reset_icp()
        
        if 'vhf' in mdc['data'] and len(mdc['data']['vhf']) > 0:
            enter_vhf()
            for channel, freq in mdc['data']['vhf'].items():
                send_vhf(int(channel), int(freq))
            send_reset_icp()
            
        if 'alow' in mdc['data'] and len(mdc['data']['alow']) > 0:
            enter_alow()
            if 'alow' in mdc['data']['alow']:
                print("Sending ALOW as", mdc['data']['alow']['alow'])
                send_number(mdc['data']['alow']['alow'], 1, 20000)
                send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
            if 'msl_floor' in mdc['data']['alow']:
                print("Sending MSL FLOOR as", mdc['data']['alow']['msl_floor'])
                send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
                send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')
                send_number(mdc['data']['alow']['msl_floor'], 1, 20000)
                send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
            send_reset_icp()
        
        if 'bingo' in mdc['data']:
            print("Sending BINGO as", mdc['data']['bingo'])
            enter_bingo()
            send_number(mdc['data']['bingo'], 1, 10000)
            send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
            send_reset_icp()
            
        if 'tgp' in mdc['data'] and len(mdc['data']['tgp']) > 0:
            enter_tgp()
            if 'code' in mdc['data']['tgp']:
                print("Sending TGP-code as", mdc['data']['tgp']['code'])
                send_number(mdc['data']['tgp']['code'], 1, 10000)
                send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
            if 'lst' in mdc['data']['tgp']:
                print("Sending TGP-LST as", mdc['data']['tgp']['lst'])
                send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 0"}')
                send('{"datatype":"input_command","data":"ICP_DATA_UP_DN_SW 1"}')
                send_number(mdc['data']['tgp']['lst'], 1, 10000)
                send_toggle('{"datatype":"input_command","data":"ICP_ENTR_BTN TOGGLE"}')
            send_reset_icp()
        
        
        ws.close()
        print("thread terminating...")
    thread.start_new_thread(run, ())
    
    
    sent_mdc = True

def on_message(ws, message):
    for b in message:
        process_byte(b)

def on_error(ws, error):
    print(error)

def on_close(ws):
    print("### closed ###")

def on_open(ws):
    def run(*args):
        ws.send('{"datatype":"live_data","data":{}}')
        print("Waiting for MASTER ARM to be set to SIM to start sending MDC data to plane ...")
    thread.start_new_thread(run, ())

def print_mdc_info(mdc):
    print("  ___    _  __   ___       __ _       __  __ ___   ___ ")
    print(" | __|__/ |/ /  / __| ___ / _| |_ ___|  \/  |   \ / __|")
    print(" | _|___| / _ \ \__ \/ _ \  _|  _|___| |\/| | |) | (__ ")
    print(" |_|    |_\___/ |___/\___/_|  \__|   |_|  |_|___/ \___|")
    print(" ")
    print(" ▄▄▄▄· ▄· ▄▌    ·▄▄▄▄ ▄▄▄ .▄▄▄··▄▄▄▄ ▄▄▄·         ▄▄▌ ")
    print("▐█ ▀█▐█▪██▌    ██▪ ██▀▄.▀▐█ ▀███▪ █▐█ ▄█    ▪    ██•  ")
    print("▐█▀▀█▐█▌▐█▪    ▐█· ▐█▐▀▀▪▄█▀▀█▐█· ▐███▀·▄█▀▄ ▄█▀▄██▪  ")
    print("██▄▪▐█▐█▀·.    ██. ██▐█▄▄▐█ ▪▐██. █▐█▪·▐█▌.▐▐█▌.▐▐█▌▐▌")
    print("·▀▀▀▀  ▀ •     ▀▀▀▀▀• ▀▀▀ ▀  ▀▀▀▀▀▀.▀   ▀█▄▀▪▀█▄▀.▀▀▀ ")
    print("")
    print("")
    print("Mission: ", mdc['mission'])
    print("MDC created by: ", mdc['creator'], " on ", mdc['date'])
    print("")    
    print('+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+')
                                                       


if __name__ == "__main__":
    if not hasattr(args, 'mdcfile'):
        parser.print_help(sys.stderr)
        sys.exit(1)
    
    if hasattr(args, 'extractfrom') and args.extractfrom != None:
        extractfrom(args.extractfrom, args.mdcfile)
    else:
        with open(args.mdcfile) as f:
            mdc = json.load(f)
            print_mdc_info(mdc)

            if debug_packages:
                websocket.enableTrace(True)
            print("Connecting to DCS-BIOS websocket ...")
            ws = websocket.WebSocketApp("ws://localhost:5010/api/websocket",
                                      on_open = on_open,
                                      on_message = on_message,
                                      on_error = on_error,
                                      on_close = on_close)

            ws.run_forever()