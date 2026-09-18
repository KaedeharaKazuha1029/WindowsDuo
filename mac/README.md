# WindowsDuo macOS Port

macOS implementation of WindowsDuo, combining Mac-Duo's native macOS interfaces with WindowsDuo's shader-based rendering.

## What is this?

This is a **software-only** port that uses your MacBook's built-in lid angle sensor (no ESP32 hardware needed). When you close the lid partway, the screen content recedes backward with spatial blur and fade-to-dark — the same "Duo" effect as the Windows version and iPhone's native implementation.

## Key differences from Windows version

- **No hardware**: Uses MacBook's built-in HID lid angle sensor (0.01° precision, no permissions required)
- **Native screen capture**: CGWindowListCreateImage with self-exclusion (overlay doesn't capture itself)
- **OpenGL Core profile**: Shaders rewritten for Core 3.3+ (macOS doesn't support compatibility profile)
- **Recession geometry**: Default shader uses Mac-Duo's "recede backward" projection instead of Windows' "push off top edge"
- **Intent recognition**: Mac-Duo's state machine prevents false triggers when lid is stationary at normal angles

## Requirements

- macOS with built-in lid angle sensor (any MacBook with HID report 0x05AC/0x20/0x8A)
- Python 3.9+
- Screen Recording permission (granted on first run)

## Installation

```bash
# Create virtual environment
python3 -m venv .venv-mac
source .venv-mac/bin/activate

# Install dependencies
pip install PyQt6 PyOpenGL numpy mss pyserial Pillow \
    pyobjc-framework-Cocoa pyobjc-framework-Quartz
```

## Usage

```bash
# Self-test (sensor, permissions, screenshot, OpenGL)
python mac/glass_overlay_mac.py --selftest

# Manual mode (keyboard control: up/down for intensity, ESC to exit)
python mac/glass_overlay_mac.py --manual

# Normal mode (lid angle driven)
python mac/glass_overlay_mac.py
```

## Configuration

Edit `mac/config.json` to tune:

- **Intent recognition**: `threshold_angle`, `span_angle`, `hysteresis`, `dwell_duration`
- **Geometry**: `eye_dist_h` (viewing distance in screen heights), `recession` (recession rate)
- **Appearance**: `blur_spread`, `max_dim`, `dim_floor`, `dim_reach`, `dim_curve`
- **Shader**: `"recede"` (default, content shrinks backward) or `"duo"` (Windows original, content pushed off top)

## Project structure

```
mac/
├── glass_overlay_mac.py    # Main application
├── lid_sensor.py            # IOKit HID lid angle reader
├── capture.py               # CGWindowListCreateImage with self-exclusion
├── shaders.py               # Core profile shader implementations
├── gl_core.py               # VAO/VBO/texture utilities
├── lid_policy.py            # Intent recognition state machine
├── depth_geometry.py        # Recession projection math
├── config.json              # Tunable parameters
├── test_lid_policy.py       # Policy unit tests
├── offscreen_test.py        # Shader validation (offline)
└── recede_test.py           # Quantitative spatial effect verification
```

## Testing

```bash
# Intent recognition (15 tests)
python mac/test_lid_policy.py

# Shader output validation
python mac/offscreen_test.py

# Spatial properties (shrink, blur gradient, fade-to-dark)
python mac/recede_test.py
python mac/recede_test.py --compare  # Compare recede vs duo shaders
```

## License and attribution

This macOS port is released under the same MIT license as WindowsDuo.

The geometry model and intent recognition logic reference [Mac-Duo](https://github.com/sumimakito/Mac-Duo) (Apache-2.0, commit 4568442) for protocol facts and parameters. No Mac-Duo code was copied; all implementation is original Python/GLSL.

## Technical notes

- **Self-capture prevention**: `kCGWindowListOptionOnScreenBelowWindow` excludes the overlay from its own screenshots (macOS 10.13+)
- **Lid sensor**: Direct IOKit HID read, no polling — sensor reports at 27Hz when lid moves
- **Shader math**: Same perspective+blur logic as Windows version, rewritten for explicit VAO/VBO/attributes
- **Default parameters**: `eye_dist_h=6.0` (Mac-Duo's default) reduces out-of-bounds black area at extreme angles vs Windows' `2.0`

## Troubleshooting

**Screen shows only desktop wallpaper**: Grant Screen Recording permission in System Settings → Privacy & Security → Screen Recording, then restart the app.

**Sensor not found**: Your MacBook model may not expose lid angle via HID. Run `--selftest` to confirm.

**Effect too subtle/strong**: Adjust `recession`, `blur_spread`, `max_dim` in `config.json`.

**Effect triggers too easily**: Increase `hysteresis`, raise `dwell_duration`, or adjust `threshold_angle` in `config.json`.
