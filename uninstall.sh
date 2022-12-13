#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

rm /service/dbus-dtu-ahoy
kill $(pgrep -f 'supervise dbus-dtu-ahoy')
chmod a-x /data/dbus-dtu-ahoy/service/run
bash $SCRIPT_DIR/restart.sh # = kill
