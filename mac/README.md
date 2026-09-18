# WindowsDuo macOS Port

macOS implementation of WindowsDuo using native lid sensor and OpenGL Core profile rendering.

## Overview

This is a **software-only** port that uses your MacBook's built-in lid angle sensor (no ESP32 hardware needed). When you close the lid partway, the screen content undergoes the same "Duo" glass effect as the Windows version — spatial blur, darkening, and geometric distortion driven by the closing angle.

## Key Features

- **Native lid sensor**: MacBook's built-in HID sensor (0.01° precision, ~27Hz)
- **Intent recognition**: State machine prevents false triggers when lid is stationary
- **OpenGL Core profile**: Rewritten shaders compatible with macOS (4.1 via Metal backend)
- **Self-exclusion**: Uses `kCGWindowListOptionOnScreenBelowWindow` to prevent overlay feedback
- **Effect parameters**: Fully aligned with WindowsDuo original (eye_dist_h=2.0, darkening=0.001, refresh_hz=3)

## Installation

```bash
# Install dependencies
python3 -m venv .venv-mac
source .venv-mac/bin/activate
pip install PyQt6 PyOpenGL numpy pyobjc-framework-Cocoa pyobjc-framework-Quartz

# Grant screen recording permission
# System Settings → Privacy & Security → Screen Recording → Add Terminal/Python
```

## Usage

### Automatic mode (default)
```bash
python mac/glass_overlay_mac.py
```
Effect triggers automatically when closing lid below 90°.

### Manual mode (keyboard control)
```bash
python mac/glass_overlay_mac.py --manual
```
- `↑`/`w`: +3% intensity
- `↓`/`s`: -3% intensity
- `→`/`d`: max (100%)
- `←`/`a`: clear (0%)
- `r`: toggle auto/manual
- `ESC`/`q`: quit

### Selftest
```bash
python mac/glass_overlay_mac.py --selftest
```
Checks sensor, permissions, capture, and OpenGL without showing overlay.

## Configuration

Edit `mac/config.json` to adjust parameters:

- **Intent recognition**: `threshold_angle`, `span_angle`, `hysteresis`, `closing_speed`, `opening_speed`
- **Geometry**: `eye_dist_h` (viewing distance in screen heights)
- **Appearance**: `blur_spread`, `darkening`
- **Performance**: `refresh_hz`, `poll_hz`, `smoothing`

## Project Structure

```
mac/
├── glass_overlay_mac.py     # Main application
├── lid_sensor.py            # HID sensor reader
├── lid_policy.py            # Intent recognition state machine
├── capture.py               # CGWindowListCreateImage wrapper
├── shaders.py               # OpenGL Core 3.3 shaders (WindowsDuo projection)
├── gl_core.py               # VAO/VBO/texture utilities
├── offscreen_test.py        # Offline shader validation
├── test_lid_policy.py       # Intent recognition unit tests
├── config.json              # Effect parameters (aligned with Windows version)
└── README.md                # This file
```

## Testing

```bash
# Intent recognition tests
python mac/test_lid_policy.py

# Shader validation (offscreen rendering)
python mac/offscreen_test.py
```

## Technical Notes

### Sensor Protocol

MacBook lid angle sensor: HID 0x05AC (Apple) / usage page 0x00FF (vendor-specific) / usage 0x0020. Reports raw angle in 0.01° units via IOHIDDeviceGetValue. No special permissions required.

### Effect Parameters

Fully aligned with WindowsDuo original:
- `eye_dist_h=2.0` (Windows default, eye distance in screen heights)
- `darkening=0.001` (Windows default, subtle darkening)
- `refresh_hz=3` (Windows default, frame rate)
- `blur_spread=0.42` (blur spread coefficient)
- `max_tilt_deg=88.0` (maximum tilt angle)

### Self-Exclusion

Uses `kCGWindowListOptionOnScreenBelowWindow` with the overlay's own CGWindowID to capture only content below the overlay, preventing feedback loops.

## Troubleshooting

**Effect not showing**: Check screen recording permission in System Settings.

**Sensor not available**: Your MacBook model may not have the built-in sensor. Use `--manual` mode for keyboard control.

**Effect too subtle/strong**: Adjust `blur_spread` or `eye_dist_h` in `config.json`.

## License

MIT (same as WindowsDuo)

## Credits

- WindowsDuo original by KaedeharaKazuha1029
- macOS port sensor protocol reference: Mac-Duo by sumimakito (Apache-2.0)
- Intent recognition logic adapted from Mac-Duo's state machine
