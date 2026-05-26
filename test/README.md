# Usage

```sh
(ve) $ python3 rigol-trace-extract.py
Available resources: ('USB0::6833::1101::DHO8A261303122::0::INSTR',)
Connecting to: USB0::6833::1101::DHO8A261303122::0::INSTR
Connected: RIGOL TECHNOLOGIES,DHO814,DHO8A261303122,00.01.04
Requested time_scale: 1e-05, Actual: 1.000000E-5
Configured: CH1, 0.5V range, 0.01ms/div, 10000 pts, 5.000000E+5 Sa/s, trigger: CHAN2 @ 1.5V
[...]
```

# Configuration

Create a virtual environment and install dependencies:

```sh
python3 -m venv ve
source ve/bin/activate
pip install -r requirements.txt
```

Configure udev rules as follows:

```sh
# Raw USB device (needed for pyusb / libusb)
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="1ab1", ATTRS{idProduct}=="044d", GROUP="plugdev", MODE="0660"' | sudo tee /etc/udev/rules.d/99-rigol.rules

# USBTMC device node
echo 'KERNEL=="usbtmc[0-9]*", ATTRS{idVendor}=="1ab1", ATTRS{idProduct}=="044d", GROUP="plugdev", MODE="0660"' | sudo tee -a /etc/udev/rules.d/99-rigol.rules

# Reload rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then unplug and reconnect the USB cable. Verify that the correct file permissions have been applied:

```sh
$ lsusb | grep -i rigol
Bus 003 Device 014: ID 1ab1:044d Rigol Technologies DHO814
$ ls -la /dev/bus/usb/003/014
crw-rw---- 1 root plugdev 189, 269 May 26 15:35 /dev/bus/usb/003/014
$ ls -ltra /dev/usbtmc0
crw-rw---- 1 root plugdev 180, 0 May 26 15:35 /dev/usbtmc0
```

# Troubleshooting

Confirm that the oscilloscope is correctly identified:

```sh
$ lsusb -d 1ab1:044d -v 2>/dev/null | grep -i "idVendor\|idProduct\|bConfigurationValue"
  idVendor           0x1ab1 Rigol Technologies
  idProduct          0x044d DHO814
    bConfigurationValue     1
```

Obtain its serial number using `pyusb`:

```sh
$ pip install pyusb
$ python3 -c "
import usb.core
dev = usb.core.find(idVendor=0x1ab1, idProduct=0x044d)
print('Serial:', dev.serial_number)
"
Serial: DHO8A261303122
```

Connect to the oscilloscope using `pyvisa` and its serial number:

```sh
$ python3 -c "
serial_no = 'DHO8A261303122'
import pyvisa
rm = pyvisa.ResourceManager('@py')
scope = rm.open_resource(f'USB::0x1AB1::0x044D::{serial_no}::INSTR')
print(scope.query('*IDN?'))
"
RIGOL TECHNOLOGIES,DHO814,DHO8A261303122,00.01.04
```

Connect without specifying the serial number:

```sh
$ python3 -c "
import pyvisa
rm = pyvisa.ResourceManager('@py')
resources = rm.list_resources('USB?*')
print('USB resources:', resources)
if resources:
    scope = rm.open_resource(resources[0])
    print(scope.query('*IDN?'))
"
USB resources: ('USB0::6833::1101::DHO8A261303122::0::INSTR',)
RIGOL TECHNOLOGIES,DHO814,DHO8A261303122,00.01.04
```
