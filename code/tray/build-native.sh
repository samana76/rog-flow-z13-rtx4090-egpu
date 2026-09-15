#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
read -r -a qt_flags <<< "$(pkg-config --cflags --libs Qt6Widgets)"
g++ -shared -fPIC -O2 native-tray.cpp -o native-tray.so \
  -I/usr/include/KF6/KStatusNotifierItem -lKF6StatusNotifierItem "${qt_flags[@]}"
