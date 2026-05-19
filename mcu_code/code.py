import struct
import time
import board
import pwmio
import analogio
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.services import Service
from adafruit_ble.characteristics import Characteristic
from adafruit_ble.characteristics.int import Uint8Characteristic
from adafruit_ble.uuid import VendorDefinedUUID

# ----- Configuration -----

PWM_PIN = board.D2  # GPIO pin driving both DRV8833 IN lines
ADC_PIN = board.D0  # GPIO pin reading the battery voltage divider

PWM_FREQ = 1000  # Hz

R1 = 100000.0  # ohm -- top leg of voltage divider
R2 = 360000.0  # ohm -- bottom leg of voltage divider

ADC_VREF = 3.3
ADC_MAX = 65535

ADC_OVERSAMPLE = 16

BATTERY_SAMPLE_INTERVAL = 0.5  # seconds

# LDO dropout at 3.18V, hard cutoff at 3.1V
LDO_DROPOUT = 3.18
BATTERY_CUTOFF = 3.1

# ----- GATT Service -----
#
# Speed char        (client -> device): uint8, 0-100 %
# Device status char (device -> client): 4 bytes little-endian
#   [0:2] battery voltage in mV  (uint16)
#   [2]   speed percent          (uint8)
#   [3]   battery critical flag  (uint8, 0 or 1)

_SVC_UUID = VendorDefinedUUID("a8b40001-c4b9-4b5c-9d6e-1f2a3c4d5e6f")
_SPEED_UUID = VendorDefinedUUID("a8b40002-c4b9-4b5c-9d6e-1f2a3c4d5e6f")
_DEVICE_STATUS_UUID = VendorDefinedUUID("a8b40003-c4b9-4b5c-9d6e-1f2a3c4d5e6f")


class VTSService(Service):
    uuid = _SVC_UUID
    speed = Uint8Characteristic(
        uuid=_SPEED_UUID,
        properties=Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE,
        initial_value=0,
    )
    device_status = Characteristic(
        uuid=_DEVICE_STATUS_UUID,
        properties=Characteristic.READ | Characteristic.NOTIFY,
        max_length=4,
        fixed_length=True,
        initial_value=bytes(4),
    )


# ----- Hardware init -----

pwm = pwmio.PWMOut(PWM_PIN, duty_cycle=0, frequency=PWM_FREQ)
adc = analogio.AnalogIn(ADC_PIN)

time.sleep(0.1)  # let supply rails settle before any motor current flows

# ----- BLE init -----

ble = BLERadio()
ble.name = "VTS"
vts_service = VTSService()
advertisement = ProvideServicesAdvertisement(vts_service)

# ----- State -----

target_duty = 0.0
battery_critical = False
last_battery_time = time.monotonic()
_battery_voltage = 3.7  # cached battery voltage; initialised to a safe mid-range value
_advertising = False

# ----- Battery -----


def battery_read_voltage():
    total = sum(adc.value for _ in range(ADC_OVERSAMPLE))
    adc_voltage = (total / ADC_OVERSAMPLE) / ADC_MAX * ADC_VREF
    return adc_voltage * (R1 + R2) / R2


def battery_is_critical(battery_voltage):
    return battery_voltage <= BATTERY_CUTOFF


# ----- Motor -----


def motor_update_battery(voltage):
    global _battery_voltage
    _battery_voltage = voltage


def motor_set_duty(target):
    effective = target
    if _battery_voltage < LDO_DROPOUT:
        # Boost duty to compensate for reduced motor voltage when LDO sags
        effective = target * (LDO_DROPOUT / _battery_voltage)
    effective = max(0.0, min(1.0, effective))
    pwm.duty_cycle = int(effective * 65535)


def motor_stop():
    pwm.duty_cycle = 0


# ----- Status characteristic -----


def push_status():
    battery_voltage_millivolts = int(_battery_voltage * 1000)
    speed_percent = int(target_duty * 100)
    critical = 1 if battery_critical else 0
    vts_service.device_status = struct.pack("<HBB", battery_voltage_millivolts, speed_percent, critical)


# ----- Main loop -----

print("Starting BLE advertising as VTS")

try:
    while True:
        if not ble.connected:
            motor_stop()  # stop motors whenever the client disconnects
            if not _advertising:
                ble.start_advertising(advertisement)
                _advertising = True
            time.sleep(0.01)
            continue

        # First connection event: stop advertising
        if _advertising:
            ble.stop_advertising()
            _advertising = False

        # Apply speed written by the client
        percent = vts_service.speed
        if percent is not None:
            target_duty = max(0, min(100, int(percent))) / 100.0

        now = time.monotonic()

        if now - last_battery_time >= BATTERY_SAMPLE_INTERVAL:
            last_battery_time = now
            battery_voltage = battery_read_voltage()

            if battery_is_critical(battery_voltage):
                battery_critical = True
                motor_stop()
                push_status()
                continue

            battery_critical = False
            motor_update_battery(battery_voltage)
            push_status()

        if battery_critical:
            continue

        motor_set_duty(target_duty)
finally:
    motor_stop()
