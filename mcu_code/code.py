import os
import json
import time
import board
import pwmio
import analogio
import wifi
import socketpool
from adafruit_httpserver import Server, Request, Response

# ── Configuration ─────────────────────────────────────────────────────────────

PWM_PIN = board.D2  # GPIO pin driving both DRV8833 IN lines
ADC_PIN = board.D0  # GPIO pin reading the battery voltage divider (same physical pin as A0)

PWM_FREQ    = 1000  # Hz — motor drive frequency; above mechanical response, below audible range
SERVER_PORT = 8080  # port 80 is restricted on ESP32; 8080 is the standard alternative

R1 = 100000.0       # Ω — top leg of voltage divider, between battery+ and D0
R2 = 360000.0       # Ω — bottom leg of voltage divider, between D0 and GND

ADC_VREF = 3.3      # V — ESP32 ADC full-scale reference voltage
ADC_MAX  = 65535    # counts — analogio normalises all ADC reads to 16-bit regardless of hardware resolution

ADC_OVERSAMPLE = 16 # readings averaged per battery sample to reduce ADC noise

BATTERY_SAMPLE_INTERVAL = 0.5  # seconds — how often the battery voltage is checked

LDO_DROPOUT    = 3.18  # V — below this the LDO can't regulate; PWM is scaled up to compensate
BATTERY_CUTOFF = 3.0   # V — minimum LiPo voltage; motors stop at or below this

# ── Hardware init ─────────────────────────────────────────────────────────────

pwm = pwmio.PWMOut(PWM_PIN, duty_cycle=0, frequency=PWM_FREQ)
adc = analogio.AnalogIn(ADC_PIN)

time.sleep(0.1)  # let supply rails settle before any motor current flows

# ── WiFi ──────────────────────────────────────────────────────────────────────

wifi.radio.hostname = "vst"  # reachable at http://vst.local via mDNS
wifi.radio.connect(os.getenv("WIFI_SSID"), os.getenv("WIFI_PASSWORD"))
print("Connected. IP:", wifi.radio.ipv4_address)

pool   = socketpool.SocketPool(wifi.radio)
server = Server(pool)

# ── State ─────────────────────────────────────────────────────────────────────

# 0.5 = half rated voltage (1.5V avg) → ~6,000 RPM on a 12,000 RPM @ 3.0V motor
target_duty       = 0.5
battery_critical  = False
last_battery_time = time.monotonic()
_v_bat            = 3.7  # cached battery voltage; initialised to a safe mid-range value

# ── Battery ───────────────────────────────────────────────────────────────────

def battery_read_voltage():
    """Oversample ADC and apply voltage-divider scale. Returns battery voltage in volts."""
    total = sum(adc.value for _ in range(ADC_OVERSAMPLE))
    v_adc = (total / ADC_OVERSAMPLE) / ADC_MAX * ADC_VREF
    return v_adc * (R1 + R2) / R2

def battery_is_critical(v_bat):
    """Returns True if v_bat is at or below the hard cutoff threshold."""
    return v_bat <= BATTERY_CUTOFF

# ── Motor ─────────────────────────────────────────────────────────────────────

def motor_update_battery(v):
    """Push a fresh battery reading so motor_set_duty() can compensate correctly."""
    global _v_bat
    _v_bat = v

def motor_set_duty(target):
    """
    Drive motors at normalised duty [0.0, 1.0] with low-battery PWM compensation.
    Below LDO_DROPOUT the duty is scaled up to maintain roughly constant torque.
    """
    effective = target
    if _v_bat < LDO_DROPOUT:
        effective = target * (BATTERY_CUTOFF / _v_bat)
    effective = max(0.0, min(1.0, effective))
    pwm.duty_cycle = int(effective * 65535)

def motor_stop():
    """Immediately stop both motors."""
    pwm.duty_cycle = 0

# ── Routes ────────────────────────────────────────────────────────────────────

@server.route("/")
def index(request: Request):
    with open("index.html") as f:
        return Response(request, f.read(), content_type="text/html")

@server.route("/setSpeed")
def set_speed(request: Request):
    """Accept ?value=0-100 and update target_duty."""
    global target_duty
    try:
        pct = float(request.query_params.get("value", 50))
    except ValueError:
        pct = 50.0
    target_duty = max(0.0, min(100.0, pct)) / 100.0
    return Response(request, "OK")

@server.route("/status")
def get_status(request: Request):
    """Return current battery voltage, critical flag, and speed as JSON."""
    return Response(
        request,
        json.dumps({
            "v_bat":     round(_v_bat, 2),
            "critical":  battery_critical,
            "speed_pct": int(target_duty * 100),
        }),
        content_type="application/json",
    )

# ── Main loop ─────────────────────────────────────────────────────────────────

server.start("0.0.0.0", SERVER_PORT)
print("Listening at http://" + str(wifi.radio.ipv4_address) + ":" + str(SERVER_PORT))

while True:
    server.poll()  # handle any pending HTTP request before anything else

    now = time.monotonic()

    if now - last_battery_time >= BATTERY_SAMPLE_INTERVAL:
        last_battery_time = now
        v_bat = battery_read_voltage()

        if battery_is_critical(v_bat):
            battery_critical = True
            motor_stop()
            continue

        battery_critical = False
        motor_update_battery(v_bat)

    if battery_critical:
        continue

    motor_set_duty(target_duty)
