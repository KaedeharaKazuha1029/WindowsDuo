import winreg

root = winreg.HKEY_LOCAL_MACHINE

# 1) USB-serial devices (CH340 VID_1A86 / CP210x VID_10C4 / ESP32 native USB VID_303A)
base = r"SYSTEM\CurrentControlSet\Enum\USB"
try:
    k = winreg.OpenKey(root, base)
    i = 0
    while True:
        try:
            vid = winreg.EnumKey(k, i)
        except OSError:
            break
        i += 1
        vu = vid.upper()
        if not (vu.startswith("VID_1A86") or vu.startswith("VID_10C4") or vu.startswith("VID_303A")):
            continue
        kj = winreg.OpenKey(k, vid)
        j = 0
        while True:
            try:
                pid = winreg.EnumKey(kj, j)
            except OSError:
                break
            j += 1
            path = base + "\\" + vid + "\\" + pid
            try:
                kdev = winreg.OpenKey(root, path)
                desc = winreg.QueryValueEx(kdev, "FriendlyName")[0]
            except OSError:
                desc = "?"
            # try to find port number
            for sub in ("Device Parameters", "Device Parameters\\"):
                try:
                    kdp = winreg.OpenKey(kdev, "Device Parameters")
                    port = winreg.QueryValueEx(kdp, "PortName")[0]
                    print(f"FOUND {desc}  ->  {port}  ({path})")
                    break
                except OSError:
                    continue
except OSError as e:
    print("enum err", e)

# 2) all COM ports
k = winreg.OpenKey(root, r"HARDWARE\DEVICEMAP\SERIALCOMM")
i = 0
while True:
    try:
        v, val, _ = winreg.EnumValue(k, i)
        print(f"PORT {v} -> {val}")
        i += 1
    except OSError:
        break
