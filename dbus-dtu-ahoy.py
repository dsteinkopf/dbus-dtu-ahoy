#!/usr/bin/env python
#
# 10.2022 hfhausen
# als Vorlage diente  dbus-iobroker-smartmeter.py
# vgl. https://www.mikrocontroller.net/topic/525778?page=14 "von Ha F. (harry_f)17.10.2022 17:35"
#
# Updated by DSTK_2022-12-14 for new ahoy api

#https://github.com/victronenergy/venus/wiki/dbus#pv-inverters
#https://github.com/victronenergy/venus/wiki/dbus#grid-and-genset-meter
#https://github.com/victronenergy/venus/wiki/dbus-api
#
# copy to device:
#   rsync -rltv --exclude '.git' --exclude 'pics' --exclude '.DS_Store' ../dbus-dtu-ahoy/ root@venus.steinkopf.net:/data/dbus-dtu-ahoy/
#
# install an run:
#   ssh root@venus bash /data/dbus-dtu-ahoy/install.sh


#import normal packages
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import dbus
import dbus.service
import logging
import sys
import os
import json

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

if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject


class DbusDTUAHOYService:
    def __init__(self, servicename, deviceinstance, paths, connection='DTU AHOY HTTP JSON service'):
        self._dbusservice = VeDbusService(servicename)
        self._paths = paths

        self._config = self._getConfig()

        self._fetch_AHOYData()
 
        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path(
            '/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', 789 )  ## Keine Ahnung was hier stehen muss!?!
        self._dbusservice.add_path('/ProductName', self._getConfigValue('DTU_AHOY_DEVICENAME'))
        self._dbusservice.add_path('/CustomName', self._getConfigValue('DTU_AHOY_DEVICENAME'))
        #self._dbusservice.add_path('/Latency', None)
        self._dbusservice.add_path('/FirmwareVersion', 0.1)
        self._dbusservice.add_path('/HardwareVersion', 0)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Role', 'inverter')
        # normaly only needed for pvinverter
        # DSTK_2022-10-24 Position was 1. Changed to 0
        self._dbusservice.add_path('/Position', int(self._getConfigValue('DTU_AHOY_POSITION')))
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

        # call _update every 1000ms
        gobject.timeout_add(1000, self._update)

        # add _signOfLife 'timer' to get feedback in log every configured minutes
        gobject.timeout_add(self._getSignOfLifeInterval() * 60*1000, self._signOfLife)

    def _getConfig(self):
        config = configparser.ConfigParser()
        config.read("%s/config.ini" %
                    (os.path.dirname(os.path.realpath(__file__))))
        return config

    def _getConfigValue(self, configentryname):
        return self._config['DEFAULT'][configentryname]

    def _getSignOfLifeInterval(self):
        value = self._getConfigValue('SignOfLifeLog')
        return int(value) if value else 1
        
    def _fetch_AHOYData(self):
        URL = self._getConfigValue('DTU_AHOY_HOSTPATH') + "/api/live"
        inverter = requests.request("GET", URL, timeout=5.0)

        # check for response
        if not inverter:
            raise ConnectionError("No response from AHOY_DTU - %s" % (URL))

        live_data = inverter.json()
        if not live_data:
            raise ValueError("Converting response to JSON failed: inverter=%s" % inverter)
        
        devicename = self._getConfigValue('DTU_AHOY_DEVICENAME')        
        all_inverters = live_data['inverter']
        self._inverter_data = list(filter(lambda arr: arr['name'] == devicename, all_inverters))[0]
        ts_last_success = self._inverter_data['ts_last_success']
        if time.time() - ts_last_success > 5*60:
            self._has_recent_data = False
            return False
        ac_data_index = self._inverter_data['ch_names'].index('AC')
        self._ac_data = self._inverter_data['ch'][ac_data_index]
        
        self._ac_data_field_names = live_data['ch0_fld_names']

        self._has_recent_data = True
        return True
    
    def _getFieldByName(self, fieldname):
        if self._has_recent_data:
            index = self._ac_data_field_names.index(fieldname)
            return self._ac_data[index]
        else:
            return None

    def _signOfLife(self):
        logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/Ac/Power']))
        return True

    def _update(self):
        try:
            got_recent_data = self._fetch_AHOYData()
            
            # send data to DBus

            yield_day_wh = self._getFieldByName('YieldDay')
            yield_day_kwh = yield_day_wh / 1000 if yield_day_wh else None

            # positive: consumption, negative: feed into grid

            self._dbusservice['/Ac/Energy/Forward'] = yield_day_kwh
            self._dbusservice['/Ac/Power'] = self._getFieldByName('P_AC')
            self._dbusservice['/ErrorCode'] = 0
            
            self._dbusservice['/Ac/MaxPower'] = int(self._getConfigValue('DTU_AHOY_MAX_POWER'))
            # self._dbusservice['/Ac/PowerLimit'] = 300 # this makes Multiplus change its zero injection behaviour

            # TODO: make L2 configurable            
            self._dbusservice['/Ac/L2/Energy/Forward'] =  yield_day_kwh
            self._dbusservice['/Ac/L2/Voltage'] = self._getFieldByName('U_AC')
            self._dbusservice['/Ac/L2/Current'] = self._getFieldByName('I_AC')
            self._dbusservice['/Ac/L2/Power'] = self._getFieldByName('P_AC') if got_recent_data else 0
                       
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

        except json.decoder.JSONDecodeError as e:
            logging.error('JSONDecodeError in _update', exc_info=e)
            # fall through...

        except ValueError as e:
            logging.error('ValueError in _update', exc_info=e)
            # fall through...

        except requests.exceptions.ConnectionError as e:
            logging.error('ConnectionError in _update', exc_info=e)
            # fall through...

        except requests.exceptions.ReadTimeout as e:
            logging.error('ReadTimeout in _update', exc_info=e)
            # fall through...

        except Exception as e:
            logging.critical('Error at %s. Now sleep and exit...', '_update', exc_info=e)
            time.sleep(10)
            sys.exit(4)

        # return true, otherwise add_timeout will be removed from GObject
        #  - see docs http://library.isr.ist.utl.pt/docs/pygtk2reference/gobject-functions.html#function-gobject--timeout-add
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
            servicename='com.victronenergy.pvinverter.ahoy_1',
            deviceinstance=79,
            
            paths={
                # We should not send 0 as initial value - this might just be wrong during normal operation (daylight)
                '/Ac/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/Power': {'initial': None, 'textformat': _w},
                '/ErrorCode': {'initial': 0, 'textformat': _w},
                '/Ac/MaxPower': {'initial': None, 'textformat': _w},
                #no '/Ac/PowerLimit': {'initial': 300, 'textformat': _w},
                				 
                '/Ac/L2/Energy/Forward': {'initial': None, 'textformat': _kwh},
                '/Ac/L2/Voltage': {'initial': None, 'textformat': _v},
                '/Ac/L2/Current': {'initial': None, 'textformat': _a},
                '/Ac/L2/Power': {'initial': None, 'textformat': _w},	
            })

        logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
        mainloop = gobject.MainLoop()
        mainloop.run()
    except Exception as e:
        logging.critical('Error here: %s', 'main', exc_info=e)
        time.sleep(10)
        sys.exit(3)

if __name__ == "__main__":
    main()
    