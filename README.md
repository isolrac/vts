# vts

A DIY open-source wearable device for vibrotactile stimulation (VTS) therapy for spasmodic dysphonia, based on research at the University of Minnesota.

---

## Overview

Spasmodic dysphonia is a neurological voice disorder that causes involuntary spasms in the throat muscles during speech, resulting in a strained or broken voice. The standard treatment is Botox injections, offering temporary relief.

Researchers at the University of Minnesota have shown that placing small vibration motors against the skin over the voice box can produce short-term improvements in voice quality and ease of speaking by "[modulating] neruonal synchonization over sensorimotor cortex". This project is a DIY functional equivalent of the wearable device used in those studies, built for personal in-home use.

This project is independent from and is not affiliated with the aforementioned university, team, or individuals.

---

## Foundational Research

1. **Proof-of-concept feasibility study (2019)**
   Konczak et al. — *Scientific Reports*
   Single-session VTS (29 min); 13 participants with adductor LD.
   → https://www.nature.com/articles/s41598-019-54396-4

2. **UMN Lab overview — laryngeal vibration research**
   Overview of the VTS research program and links to publications.
   → https://hsc.umn.edu/vibro-tactile-stimulation-topic/laryngeal-vibration-treatment-voice-disorder

3. **11-week randomized controlled trial (2024)**
   Konczak et al. — *Frontiers in Neurology* (ClinicalTrials.gov: NCT03746509)
   39 participants; crossover design; 40 Hz and 100 Hz; self-administered in-home.
   → https://www.frontiersin.org/journals/neurology/articles/10.3389/fneur.2024.1403050/full

4. **In-home usability and feasibility study (2025)**
   Amini et al. — *Journal of Voice*
   Self-administered in-home VTS; usability and feasibility outcomes.
   → https://www.sciencedirect.com/science/article/abs/pii/S0892199725003297

---

## System Architecture

```

┌──────────────────────────┐
│  Collar Hardware         │  2× ERM vibration motors at thyroid cartilage
│  XIAO nrF + DRV8833      │  PWM control, LiPo power, battery monitoring
└────────────┬─────────────┘
             │ Bluetooth Low Energy (BLE)
             │ custom GATT characteristic
┌────────────▼─────────────┐
│  Web UI                  │  Speed slider, connect/disconnect
│  GitHub Pages (HTTPS)    │  Loads once, then works offline
│  Chrome / Bluefy         │  Web Bluetooth API
└──────────────────────────┘
```


## Charging / Power overview
```
                         USB-C
                           |
                           v
              +----------------------------+
              |     XIAO nRF52840          |
              |  (onboard USB charger)     |
              +-------------+--------------+
                            | BAT pad (shared VBAT node)
              +-------------+---------------+
              |                             |
              v                             v
    [ SW1 power switch ]              [ 3.3v buck ]
              |                             |
              v                             |
  [ protected 1S 2200 mAh                   v
    Li-ion battery ]              [C1 220 uF + C2 10 uF decoupling caps]
                                            |
                                            v
                                    [ DRV8833 motor driver ]
      XIAO control I/O:                |          |
      | D2 / PWM         ------------> |          |
      | D1 / nFAULT      <------------ |          |
      | 3V3 / nSLEEP + pull-up ------> |          |
      | GND                            |          |
      +----------- common GND ---------+          |
                                       |          |
                             24-26 AWG twisted pairs
                                       |          |
                                 [Motor 1]    [Motor 2]
                                  C3 100 nF    C4 100 nF snubber caps
                                 at terminals  at terminals
```
---

## Hardware

### Bill of Materials

| Component | Description | Notes |
|---|---|---|
| Seeed Studio XIAO nRF52840 | Microcontroller | non-Sense variant; CircuitPython 10.2.x |
| AILUOMI DRV8833 breakout | Motor driver | Active-low nFAULT wired to XIAO D1 through R1 |
| 3.3 V buck | Motor regulator | ~2 A capable; enters 100% duty near end of discharge, so the motor rail sags with the battery from that point on |
| Adafruit 1781 | Protected 1S 2200 mAh Li-ion battery | Integral protection replaces the earlier external PCM + fuse; verify JST-PH polarity before first connection |
| 2x Vybronics VZ7AL2B169208T | ERM vibration motors | 7x25mm cylindrical; 3.0 V nameplate, driven from the 3.3 V rail; 12,000 RPM |
| Panasonic EEUFR1A221 | 220 uF driver bulk cap (C1) | Low-ESR aluminum electrolytic; mount at DRV8833 VM/GND |
| 10 uF tantalum, >=10 V rating | Driver bulk cap (C2) | Mount at DRV8833 VM/GND |
| 2x 100 nF X7R ceramic (KEMET C330C104M5U5TA or equiv) | Motor snubber caps (C3, C4) | Mount directly across the motor terminals, not at the controller end |
| Yageo CFR-25JR-52-10K | 10 kohm nFAULT pull-up resistor (R1) | Pulls DRV8833 nFAULT to XIAO 3V3 |

> **Note:** This BOM is a work in progress. Everything listed was available from DigiKey in the U.S. at the time of this writing

The XIAO drives both ERM motors together through the DRV8833 from a single PWM pin. A 3.3 V buck regulator supplies the motor rail from the protected LiPo, and the DRV8833's active-low nFAULT is monitored on XIAO D1. Motor spec sheet lists 3.6V max at the motor terminals, and there's some voltage drop over the 3 feet of motor wiring, so we're within tolerances.


### Enclosure / Housing

- 3D printed enclosures for the motors and main unit, customizable to the diameter and length of the ERM motors used, are included in this repository.
- The bulk of the circuitry and battery lives in an external enclosure carried in the user's pocket. Silicone-coated wires powering each motor are twisted into a pair to mitigate interference alongside a length of unextruded TPU to lend mechanical strength, and heat-shrunk together at a few junctures just to keep the bundle cohesive. Each motor is in its own minimal housing that can be quickly put on and removed, reducing bulk around the user's neck.
- **Motor cabling:** 24-26 AWG stranded copper, twisted pair per motor, with mechanical strain relief. Route motor wiring clear of external antenna / USB socket.

---

## Charging & operating policy

- The device is turned on and off by a switch inline in the battery lead. The switch also sits between the battery and the XIAO's onboard charger, so **USB-C charging only works while the switch is on** (with the switch off, USB can still power the XIAO logic over VBUS, but no current reaches the battery and the motor rail is dead).

---

## Firmware

### Requirements

- CircuitPython 10.2.x for XIAO nRF52840
- CircuitPython libraries: `adafruit_ble`, `adafruit_ble_radio`

### Installation

Copy `code.py` to the root of the `CIRCUITPY` drive. On boot, the device immediately begins advertising over BLE.

### Key Behaviors

**PWM motor control**
- Pin: `board.D2`
- Frequency: 1000 Hz
- Resolution: 16-bit duty cycle
- Both motors run identically from a single PWM signal through both DRV8833 channels

**Power & battery management** — the firmware samples VBAT via the XIAO's on-module divider, reports voltage over BLE, and cuts the motors off at a low-battery threshold to protect the cell. The 3.3 V motor rail is regulated by a buck.

**Planned safeguards (TODO)**
- nFAULT sampling on D1 with immediate PWM shutdown on an active-low fault.
- 20-minute maximum continuous activation.
- Motors disabled while USB is plugged in (until load-sharing and thermal behavior are validated).

### BLE / GATT

The device advertises a custom GATT service. The client writes motor speed as a uint8 percentage to the speed characteristic and subscribes to device status notifications.

| | UUID |
|---|---|
| Service | `30c41c6a-fb6d-43f6-9452-360b85ebc2c2` |
| Speed characteristic | `895a81a6-01a7-4643-b93b-e5969464ab83` |
| Device status characteristic | `fb9eb7c9-7720-48bd-923e-c0f53174d950` |

**Speed:** uint8, write, range 0 (stopped) to 100 (full speed).

**Device status:** 4 bytes, little-endian, read/notify.

| Bytes | Type | Field |
|---|---|---|
| 0-1 | uint16 | Battery voltage in mV |
| 2 | uint8 | Speed percent (0-100) |
| 3 | uint8 | Battery critical flag (0 or 1) |

---

## Web UI

The control interface is a static page hosted on GitHub Pages. It uses the Web Bluetooth API to connect directly to the device over BLE.

**To use:**

1. Open the GitHub Pages URL in Chrome on your mobile device
2. Tap **Connect** and select the `vts` device from the browser's BLE picker
3. Use the speed slider to set motor intensity
4. Tap **Disconnect** when the session is complete

---

## Usage

1. Position the motors against the left and right lateral edges of your thyroid cartilage
2. Open the Web UI in Chrome
3. Tap **Connect** and pair with `vts`
4. Set motor speed using the slider — start low and increase until vibration is clearly perceptible but comfortable
5. Tap **Disconnect** when the session is complete

**Recommended protocol (from in-home feasibility study):** 3 sessions per week for the first month, increasing as tolerated.

---

## Disclaimer

This is a personal research project. It is not a medical device, and I am not a Doctor of Medicine. Use at your own risk.

---

## Roadmap / Known Issues

- **iOS Web Bluetooth** — Safari does not support Web Bluetooth
- **Voice activity detection (VAD)** — The lab device can trigger motors only during active vocalization using a neck-contact accelerometer; this project currently uses always-on continuous stimulation, which is also supported by the clinical evidence

---

## License

MIT License — see `LICENSE` for details.
