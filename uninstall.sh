#!/bin/bash

rm /service/dbus-dtu-ahoy
kill $(pgrep -f 'supervise dbus-dtu-ahoy')
chmod a-x /data/dbus-dtu-ahoy/service/run
./restart.sh
