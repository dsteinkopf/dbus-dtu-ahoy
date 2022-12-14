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

        self._fetch_AHOYData()
 
        logging.debug("%s /DeviceInstance = %d" %
                      (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path(
            '/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 789 )  ## Keine Ahnung was hier stehen muss!?!
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
        self._dbusservice.add_path('/Serial', 2)
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
        gobject.timeout_add(1000, self._update)

        # add _signOfLife 'timer' to get feedback in log every 5minutes
        gobject.timeout_add(self._getSignOfLifeInterval() * 60*1000, self._signOfLife)

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

    def _getDTU_AHOY_Path(self):
        value = self._config['DEFAULT']['DTU_AHOY_HOSTPATH']
        return value

    def _fetch_AHOYData(self):
        URL = self._getDTU_AHOY_Path() + "/api/live" 
        inverter = requests.request("GET", URL)

        # check for response
        if not inverter:
            raise ConnectionError("No response from AHOY_DTU - %s" % (URL))

        live_data = inverter.json()
        devicename = self._getDTU_AHOY_DEVICENAME()
        
        all_inverters = live_data['inverter']
        self._inverter_data = list(filter(lambda arr: arr['name'] == devicename, all_inverters))[0]
        ac_data_index = self._inverter_data['ch_names'].index('AC')
        self._ac_data = self._inverter_data['ch'][ac_data_index]
        
        self._ac_data_field_names = live_data['ch0_fld_names']

        # check for Json
        if not self._inverter_data:
            raise ValueError("Converting response to JSON failed")
    
    def _getFieldByName(self, fieldname):
        index = self._ac_data_field_names.index(fieldname)
        return self._ac_data[index]

    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s" % (self._lastUpdate))
        logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/Ac/Power']))
        logging.info("--- End: sign of life ---")
        return True

    def _update(self):
        try:
            self._fetch_AHOYData()
            
            # send data to DBus

             # positive: consumption, negative: feed into grid
            self._dbusservice['/Ac/Energy/Forward'] = self._getFieldByName('YieldDay') / 1000 # YieldDay = W
            self._dbusservice['/Ac/Power'] = self._getFieldByName('P_AC')
            self._dbusservice['/ErrorCode'] = 0
            
            self._dbusservice['/Ac/MaxPower'] = 300
            # self._dbusservice['/Ac/PowerLimit'] = 300 # this makes Multiplus change its zero injection behaviour

            # TODO: make L2 configurable            
            self._dbusservice['/Ac/L2/Energy/Forward'] =  self._getFieldByName('YieldDay') / 1000 # YieldDay = W
            self._dbusservice['/Ac/L2/Voltage'] = self._getFieldByName('U_AC')
            self._dbusservice['/Ac/L2/Current'] = self._getFieldByName('I_AC')
            self._dbusservice['/Ac/L2/Power'] = self._getFieldByName('P_AC')
                       
            #logging.info("voltage = %s" % self._getFieldByName('U_AC'))                    
            #logging.info("YieldDay = %s kWh, P_AC: %s W" % (
            #    self._getFieldByName('YieldDay') / 1000, 
            #    self._getFieldByName('P_AC')))

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
                # We should not send 0 as initial value - this might just be wrong during normal operation (daylight)
                '/Ac/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/Power': {'initial': None, 'textformat': _w},
                '/ErrorCode': {'initial': 0, 'textformat': _w},
                '/Ac/MaxPower': {'initial': 300, 'textformat': _w},
                #no '/Ac/PowerLimit': {'initial': 300, 'textformat': _w},
                				 
                '/Ac/L2/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/L2/Voltage': {'initial': None, 'textformat': _v},
                '/Ac/L2/Current': {'initial': None, 'textformat': _a},
                '/Ac/L2/Power': {'initial': None, 'textformat': _w},	
            })

        logging.info(
            'Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()
    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)


if __name__ == "__main__":
    main()
    