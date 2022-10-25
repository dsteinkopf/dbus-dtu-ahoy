#!/usr/bin/env python
#
#(10.2022 hfhausen)
#/data/dbus-dtu-ahoy/dbus-dtu-ahoy.py
# als Vorlage diente  dbus-iobroker-smartmeter.py

#https://github.com/victronenergy/venus/wiki/dbus#pv-inverters
#https://github.com/victronenergy/venus/wiki/dbus#grid-and-genset-meter
#https://github.com/victronenergy/venus/wiki/dbus-api


#import normal packages
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import dbus
import dbus.service
import inspect
import logging
import argparse
import sys
import os

# Victron packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), './ext/velib_python'))
# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__),
                '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService, VeDbusItemImport
 

import platform
 
import time
import requests  # for http GET
import configparser  # for config/ini file
import struct

if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject


class DbusDTUAHOYService:
    def __init__(self, servicename, deviceinstance, paths, productname='DTU Ahoy', connection='DTU AHOY HTTP JSON service'):
        self._dbusservice = VeDbusService(
            "{}.http_{:02d}".format(servicename, deviceinstance))
        self._paths = paths

        self._config = self._getConfig()

        # get data from Senec
        inverter_data = self._getDTU_AHOYData()
 
        logging.debug("%s /DeviceInstance = %d" %
                      (servicename, deviceinstance))

        # debug:
        #logging.info("Senec serial: %s" % (self._getSenecSerial()))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path(
            '/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 789 )  ## Keine Ahnung was hier stehen muss!?!
        #self._dbusservice.add_path('/DeviceType', 345)  ## Keine Ahnung was hier stehen muss!?!
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', productname)
        #self._dbusservice.add_path('/Latency', None)
        self._dbusservice.add_path('/FirmwareVersion', 0.1)
        self._dbusservice.add_path('/HardwareVersion', 0)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Role', 'inverter')
        # normaly only needed for pvinverter
        # DSTK_2022-10-24 Position was 1. Changed to 0
        self._dbusservice.add_path('/Position', 0)   ## 0=AC input 1; 1=AC output  PV-Wechselrichter ; 2=AC input 2 GENERATOR
        #self._dbusservice.add_path('/Serial', self._getDTU_AHOYSerial())
        self._dbusservice.add_path('/Serial', 1)
        self._dbusservice.add_path('/UpdateIndex', 0)
        self._dbusservice.add_path('/Ac/NumberOfPhases', 1)
        self._dbusservice.add_path('/Ac/NumberOfAcInputs', 1)
        #self._dbusservice.add_path('/Mode', 2)

        # add path values to dbus
        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)

        # last update
        self._lastUpdate = 0

        # add _update function 'timer'
        # pause 1000ms before the next request
        gobject.timeout_add(500, self._update)

        # add _signOfLife 'timer' to get feedback in log every 5minutes
        gobject.timeout_add(self._getSignOfLifeInterval()
                            * 60*1000, self._signOfLife)

    def _getDTU_AHOYSerial(self):
        inverter_data = self._getDTU_AHOYData()

        device_id = next((x for x in inverter_data if x['id'] == self._getDTU_AHOYDeviceId()), None)

        if not device_id[0]:
            raise ValueError(
                "Response does not contain 'DEVICE_ID' attribute")

        serial = device_id[0] 
        return serial

    def _getConfig(self):
        config = configparser.ConfigParser()
        config.read("%s/config.ini" %
                    (os.path.dirname(os.path.realpath(__file__))))
        return config

    def _getSignOfLifeInterval(self):
        value = self._config['DEFAULT']['SignOfLifeLog']

        if not value:
            value = 0

        return int(value)
        
    def _getDTU_AHOY_DEVICENAME(self):
        value = self._config['DEFAULT']['DTU_AHOY_DEVICENAME']
        return value        

    def _getDTU_AHOYDeviceId(self):
        value = self._config['DEFAULT']['DTU_AHOY_ID']
        return value

    def _getDTU_AHOY_U_AC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH0_U_AC']
        return value

    def _getDTU_AHOY_I_AC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH0_I_AC']
        return value
        
    def _getDTU_AHOY_P_AC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH0_P_AC']
        return value

    def _getDTU_AHOY_FREQ(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH0_FREQ']
        return value

    def _getDTU_AHOY_CH1_U_DC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH1_U_DC']
        return value

    def _getDTU_AHOY_CH1_P_DC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH1_P_DC']
        return value
        
    def _getDTU_AHOY_CH1_I_DC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH1_I_DC']        
        return value

    def _getDTU_AHOY_CH2_U_DC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH2_U_DC']
        return value

    def _getDTU_AHOY_CH2_P_DC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH2_P_DC']
        return value
        
    def _getDTU_AHOY_CH2_I_DC(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH2_I_DC']
        return value

    def _getDTU_AHOY_YIELDDAY(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH0_YIELDDAY']
        return value

    def _getDTU_AHOY_YIELDTOTAL(self):
        value = self._config['DEFAULT']['DTU_AHOY_CH0_YIELDTOTAL']
        return value

    def _getDTU_AHOY_LAST_MSG(self):
        value = self._config['DEFAULT']['DTU_AHOY_LAST_MSG']
        return value

    def _getDTU_AHOY_Path(self):
        value = self._config['DEFAULT']['DTU_AHOY_HOSTPATH']
        return value

    def _getDTU_AHOYData(self):
        URL = self._getDTU_AHOY_Path() + "/json" 

        headers = {}

        inverter = requests.request("GET", URL, headers=headers)

        # check for response
        if not inverter:
            raise ConnectionError("No response from AHOY_DTU - %s" % (URL))

        inverter_data_x = inverter.json()
        ##inverter_data = inverter_data_x['HM600']
        
        devicename = self._getDTU_AHOY_DEVICENAME()
        #print( devicename )
        inverter_data = inverter_data_x[devicename]
        
       
        ##for k in inverter_data:
        ##    print(k)
        
        # check for Json
        if not inverter_data:
            raise ValueError("Converting response to JSON failed")

        return inverter_data

    def _floatFromHex(self, val):

        return struct.unpack('!f', bytes.fromhex(val[3:]))[0]
        #struct.unpack('!f', (val[3:]).decode('hex'))[0]

    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s" % (self._lastUpdate))
        logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/Ac/Power']))
        logging.info("--- End: sign of life ---")
        return True

    def _update(self):
        try:
            # get data from DTU_AHOY
            inverter_data = self._getDTU_AHOYData()

            # send data to DBus
            last_msg = (inverter_data)[self._getDTU_AHOY_LAST_MSG()]
      
            total_voltage = (inverter_data)[self._getDTU_AHOY_U_AC()][0]
            total_current = (inverter_data)[self._getDTU_AHOY_I_AC()][0]
            total_power = (inverter_data)[self._getDTU_AHOY_P_AC()][0]
            total_frequency = (inverter_data)[self._getDTU_AHOY_FREQ()][0]
            
            #total_ch0_voltage = (inverter_data)[self._getDTU_AHOY_CH1_U_DC()][0]
            #total_ch0_power = (inverter_data)[self._getDTU_AHOY_CH1_P_DC()][0]
            #total_ch0_currnet = (inverter_data)[self._getDTU_AHOY_CH1_I_DC()][0]
            
            #total_ch1_voltage = (inverter_data)[self._getDTU_AHOY_CH2_U_DC()][0]
            #total_ch1_power = (inverter_data)[self._getDTU_AHOY_CH2_P_DC()][0]
            #total_ch1_currnet = (inverter_data)[self._getDTU_AHOY_CH2_I_DC()][0]
             
             
            total_yieldpower = (inverter_data)[self._getDTU_AHOY_YIELDDAY()][0]
            total_yieldtotalpower = (inverter_data)[self._getDTU_AHOY_YIELDTOTAL()][0]
        
             # positive: consumption, negative: feed into grid
            self._dbusservice['/Ac/Energy/Forward'] = 0 # total_yieldpower / 1000
            self._dbusservice['/Ac/Power'] = total_power
            self._dbusservice['/ErrorCode'] = 0
            
            self._dbusservice['/Ac/MaxPower'] = 300
            self._dbusservice['/Ac/PowerLimit'] = 300 
 
            
            self._dbusservice['/Ac/L1/Energy/Forward'] = 0
            self._dbusservice['/Ac/L1/Voltage'] = 0
            self._dbusservice['/Ac/L1/Current'] = 0 
            self._dbusservice['/Ac/L1/Power'] = 0
            
            self._dbusservice['/Ac/L2/Energy/Forward'] = 0
            self._dbusservice['/Ac/L2/Voltage'] = 0
            self._dbusservice['/Ac/L2/Current'] = 0 
            self._dbusservice['/Ac/L2/Power'] = 0
                       
            self._dbusservice['/Ac/L3/Energy/Forward'] = 0 # total_yieldpower / 1000
            self._dbusservice['/Ac/L3/Voltage'] = total_voltage
            self._dbusservice['/Ac/L3/Current'] = total_current
            self._dbusservice['/Ac/L3/Power'] = total_power

            # increment UpdateIndex - to show that new data is available
            index = self._dbusservice['/UpdateIndex'] + 1  # increment index
            if index > 255:   # maximum value of the index
                index = 0       # overflow from 255 to 0
            self._dbusservice['/UpdateIndex'] = index

            # update lastupdate vars
            self._lastUpdate = time.time()
        except Exception as e:
            logging.critical('Error at %s', '_update', exc_info=e)

        # return true, otherwise add_timeout will be removed from GObject - see docs http://library.isr.ist.utl.pt/docs/pygtk2reference/gobject-functions.html#function-gobject--timeout-add
        return True

    def _handlechangedvalue(self, path, value):
        logging.debug("someone else updated %s to %s" % (path, value))
        return True  # accept the change


def main():
    # configure logging
    logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO,
                        handlers=[
                            logging.FileHandler(
                                "%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                            logging.StreamHandler()
                        ])

    try:
        logging.info("Start")

        from dbus.mainloop.glib import DBusGMainLoop
        # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
        DBusGMainLoop(set_as_default=True)

        # formatting
        def _kwh(p, v): return (str(round(v, 2)) + ' KWh')
        def _wh(p, v): return (str(round(v, 2)) + ' Wh')
        def _a(p, v): return (str(round(v, 1)) + ' A')
        def _w(p, v): return (str(round(v, 1)) + ' W')
        def _v(p, v): return (str(round(v, 1)) + ' V')
        def _hz(p, v): return (str(round(v, 2)) + ' Hz')

        # start our main-service
        pvac_output = DbusDTUAHOYService(
            servicename='com.victronenergy.pvinverter',
            deviceinstance=77,
            

            
            paths={
                '/Ac/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/Power': {'initial': 0, 'textformat': _w},
                '/ErrorCode': {'initial': 0, 'textformat': _w},
                '/Ac/MaxPower': {'initial': 0, 'textformat': _w},
                '/Ac/PowerLimit': {'initial': 300, 'textformat': _w},
                
				 
                '/Ac/L1/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/L1/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L1/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L1/Power': {'initial': 0, 'textformat': _w},				 
     
                '/Ac/L2/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/L2/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L2/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L2/Power': {'initial': 0, 'textformat': _w},	
                
                '/Ac/L3/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/L3/Voltage': {'initial': 0, 'textformat': _v},
                '/Ac/L3/Current': {'initial': 0, 'textformat': _a},
                '/Ac/L3/Power': {'initial': 0, 'textformat': _w},	

            })

        logging.info(
            'Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()
    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)


if __name__ == "__main__":
    main()
