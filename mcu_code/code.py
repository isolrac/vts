import struct
import time
import board
import digitalio
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
NFAULT_PIN = board.D3  # active-low DRV8833 nFAULT; external 10k pull-up on the schematic

PWM_FREQ = 1000  # Hz

BATTERY_ADC_PIN = board.VBATT  # XIAO nRF52840 internal VBAT sense (P0.31)
BATTERY_ENABLE_PIN = board.READ_BATT_ENABLE  # drive low to power the divider (P0.14)
# ponytail: nominal 1M/510k divider ratio; trim against a multimeter if voltage reads off.
BATTERY_DIVIDER_RATIO = (1000.0 + 510.0) / 510.0

ADC_MAX = 65535

ADC_OVERSAMPLE = 16

BATTERY_SAMPLE_INTERVAL = 0.5  # seconds

# LDO dropout at 3.18V, hard cutoff at 3.1V
LDO_DROPOUT = 3.18
BATTERY_CUTOFF = 3.1

# ----- GATT Service -----
#
# Speed char        (client -> device): uint8, 0-100 %
# Device status char (device -> client): 5 bytes little-endian
#   [0:2] battery voltage in mV  (uint16)
#   [2]   speed percent          (uint8)
#   [3]   battery critical flag  (uint8, 0 or 1)
#   [4]   motor fault latched    (uint8, 0 or 1)

_SVC_UUID = VendorDefinedUUID("30c41c6a-fb6d-43f6-9452-360b85ebc2c2")
_SPEED_UUID = VendorDefinedUUID("895a81a6-01a7-4643-b93b-e5969464ab83")
_DEVICE_STATUS_UUID = VendorDefinedUUID("fb9eb7c9-7720-48bd-923e-c0f53174d950")


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
        max_length=5,
        fixed_length=True,
        initial_value=bytes(5),
    )


# ----- Hardware init -----

pwm = pwmio.PWMOut(PWM_PIN, duty_cycle=0, frequency=PWM_FREQ)

_batt_enable = digitalio.DigitalInOut(BATTERY_ENABLE_PIN)
_batt_enable.direction = digitalio.Direction.OUTPUT
_batt_enable.value = False  # active-low: pull low to connect the VBAT divider
adc = analogio.AnalogIn(BATTERY_ADC_PIN)

# R1 (10k) supplies the external pull-up; no internal pull needed.
nfault = digitalio.DigitalInOut(NFAULT_PIN)
nfault.direction = digitalio.Direction.INPUT

time.sleep(0.1)  # let supply rails settle before any motor current flows

# ----- BLE init -----

ble = BLERadio()
ble.name = "VTS"
vts_service = VTSService()
advertisement = ProvideServicesAdvertisement(vts_service)

# ----- State -----

target_duty = 0.0
battery_critical = False
motor_fault_latched = False  # set on active-low nFAULT; cleared only by power cycle
last_battery_time = time.monotonic()
_battery_voltage = 3.7  # cached battery voltage; initialised to a safe mid-range value
_advertising = False

# ----- Battery -----


def battery_read_voltage():
    total = sum(adc.value for _ in range(ADC_OVERSAMPLE))
    adc_voltage = (total / ADC_OVERSAMPLE) / ADC_MAX * adc.reference_voltage
    return adc_voltage * BATTERY_DIVIDER_RATIO


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
    fault = 1 if motor_fault_latched else 0
    vts_service.device_status = struct.pack("<HBBB", battery_voltage_millivolts, speed_percent, critical, fault)


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

        # Active-low DRV8833 fault: latch and keep motors off until power cycle.
        if not nfault.value:
            motor_fault_latched = True

        if motor_fault_latched:
            motor_stop()
            push_status()
            continue

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
