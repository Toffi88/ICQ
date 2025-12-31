"""
Test-Script zum Prüfen der Blickrichtung (Facing) in WoW
Liest die Blickrichtung aus den WeakAura-Pixeln und zeigt sie an
"""

import cv2
import dxcam
import numpy as np
import time
import pygetwindow as gw

# Windows API für Mausstatus-Prüfung
try:
    import win32api
    import win32gui
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("[WARNUNG] win32api nicht verfügbar.")

WINDOW_TITLE = "World of Warcraft"

def decode_24bit_pixel(pixel_bgr, normalize=True):
    """Dekodiert einen 24-Bit-Pixel-Wert aus BGR-Farbwerten.
    
    Args:
        pixel_bgr: BGR-Farbe als (B, G, R) Tupel oder numpy array
        normalize: Wenn True, normalisiert auf 0.0-1.0, sonst gibt Ro-Wert zurück
        
    Returns:
        Normalisierter Wert zwischen 0.0 und 1.0, oder Ro-Wert (0-16777215)
    
    WICHTIG: WeakAura-Code zeigt:
    - r = math.floor(raw / 65536) / 255  (obere 8 Bits, als 0-1 normalisiert)
    - g = math.floor(bit.band(raw, 0xFF00) / 256) / 255  (Bits 8-15)
    - b = bit.band(raw, 0xFF) / 255  (Bits 0-7)
    
    WeakAura-Code für Koordinaten:
    - local raw = math.floor(pos.x * 16777215)  [24-Bit-Wert]
    - r = math.floor(raw / 65536) / 255
    - g = math.floor(bit.band(raw, 0xFF00) / 256) / 255
    - b = bit.band(raw, 0xFF) / 255
    """
    if pixel_bgr is None or len(pixel_bgr) < 3:
        return None
    
    # BGR Format (OpenCV Standard)
    b, g, r = int(pixel_bgr[0]), int(pixel_bgr[1]), int(pixel_bgr[2])
    
    # WeakAura-Code analysieren:
    # raw = math.floor(pos.x * 16777215)  [24-Bit-Wert]
    # r = math.floor(raw / 65536) / 255
    #   -> r * 255 = math.floor(raw / 65536) = (raw >> 16) & 0xFF  [Bits 16-23]
    # g = math.floor(bit.band(raw, 0xFF00) / 256) / 255
    #   -> g * 255 = (raw & 0xFF00) >> 8 = (raw >> 8) & 0xFF  [Bits 8-15]
    # b = bit.band(raw, 0xFF) / 255
    #   -> b * 255 = raw & 0xFF  [Bits 0-7]
    
    # WICHTIG: r, g, b sind Ro-Werte (0-255) von OpenCV, nicht normalisiert!
    # WeakAura speichert normalisierte Werte (0.0-1.0), also müssen wir die Ro-Werte
    # als normalisierte Werte interpretieren: r_norm = r / 255.0
    
    # Normalisiere BGR-Werte auf 0.0-1.0 (wie WeakAura sie speichert)
    r_norm = r / 255.0
    g_norm = g / 255.0
    b_norm = b / 255.0
    
    # Rekonstruiere den 24-Bit-Wert
    # r_norm * 255 gibt uns die oberen 8 Bits (Bits 16-23)
    # g_norm * 255 gibt uns die mittleren 8 Bits (Bits 8-15)
    # b_norm * 255 gibt uns die unteren 8 Bits (Bits 0-7)
    raw_upper_8 = int(r_norm * 255)  # Bits 16-23
    raw_middle_8 = int(g_norm * 255)  # Bits 8-15
    raw_lower_8 = int(b_norm * 255)   # Bits 0-7
    
    # Rekonstruiere: (upper_8 << 16) | (middle_8 << 8) | lower_8
    value_24bit = (raw_upper_8 << 16) | (raw_middle_8 << 8) | raw_lower_8
    
    if normalize:
        # Skaliere auf 0.0 bis 1.0
        # 24-Bit = 0 bis 16777215 (2^24 - 1)
        return value_24bit / 16777215.0
    else:
        # Gib Ro-Wert zurück (für Koordinaten, die direkt als WoW-Koordinaten interpretiert werden)
        return float(value_24bit)

def decode_facing_pixel(pixel_bgr):
    """Dekodiert einen Blickrichtung-Pixel und konvertiert zu Grad."""
    normalized = decode_24bit_pixel(pixel_bgr, normalize=True)
    if normalized is None:
        return None
    
    # WeakAura: GetPlayerFacing() gibt 0 bis 2π zurück
    # Normalisiert auf 0.0-1.0, dann * 360° für Grad
    # WICHTIG: GetPlayerFacing() gibt Winkel in Radian zurück, wo 0 = Norden
    facing_degrees = normalized * 360.0
    
    # KORREKTUR: Osten und Westen sind um 180° verschoben
    # Norden (0°) und Süden (180°) passen, aber Osten (90°) und Westen (270°) sind vertauscht
    # Lösung: Wenn der Winkel im Osten/Westen-Bereich ist, um 180° verschieben
    # Osten-Bereich: 45°-135° -> sollte 90° sein, aber zeigt ~270° (Westen)
    # Westen-Bereich: 225°-315° -> sollte 270° sein, aber zeigt ~90° (Osten)
    
    # Prüfe ob wir im Osten/Westen-Bereich sind (45°-135° oder 225°-315°)
    if (45.0 <= facing_degrees < 135.0) or (225.0 <= facing_degrees < 315.0):
        # Verschiebe um 180°
        facing_degrees = (facing_degrees + 180.0) % 360.0
    
    return facing_degrees

def get_direction_name(angle):
    """Konvertiert Winkel in Himmelsrichtung."""
    # In WoW: 0° = Norden, 90° = Osten, 180° = Süden, 270° = Westen
    if angle < 22.5 or angle >= 337.5:
        return "Norden"
    elif angle < 67.5:
        return "Nord-Osten"
    elif angle < 112.5:
        return "Osten"
    elif angle < 157.5:
        return "Süd-Osten"
    elif angle < 202.5:
        return "Süden"
    elif angle < 247.5:
        return "Süd-Westen"
    elif angle < 292.5:
        return "Westen"
    else:
        return "Nord-Westen"

def validate_region(region, screen_width, screen_height):
    """Validiert und korrigiert die Region, damit sie innerhalb des Bildschirms liegt."""
    if region is None:
        return None
    
    left, top, right, bottom = region
    
    # Stelle sicher, dass die Koordinaten innerhalb des Bildschirms liegen
    left = max(0, min(left, screen_width - 1))
    top = max(0, min(top, screen_height - 1))
    right = max(left + 1, min(right, screen_width))
    bottom = max(top + 1, min(bottom, screen_height))
    
    # Stelle sicher, dass right > left und bottom > top
    if right <= left or bottom <= top:
        return None
    
    return (left, top, right, bottom)

def get_wow_region(screen_width, screen_height):
    """Holt die Region des WoW-Fensters."""
    try:
        windows = gw.getWindowsWithTitle(WINDOW_TITLE)
        if len(windows) == 0:
            return None
        win = windows[0]
        region = (win.left, win.top, win.left + win.width, win.top + win.height)
        
        # Validiere die Region
        validated_region = validate_region(region, screen_width, screen_height)
        
        return validated_region
    except Exception as e:
        print(f"[FEHLER] Fehler beim Abrufen des WoW-Fensters: {e}")
        return None

def main():
    print("=" * 60)
    print("WoW Blickrichtung Test-Script")
    print("=" * 60)
    print(f"Suche nach WoW-Fenster: '{WINDOW_TITLE}'")
    
    # Pixel-Koordinaten für Facing (aus dem Haupt-Script)
    # WICHTIG: Diese Position muss mit der WeakAura-Position übereinstimmen!
    pixel_facing_coord = (60, 700)  # (x, y) für Blickrichtung (Beige)
    
    print(f"Verwende Pixel-Position für Facing: ({pixel_facing_coord[0]}, {pixel_facing_coord[1]})")
    print("Falls der Wert sich nicht ändert, ist die Position möglicherweise falsch!")
    print("Prüfe die BGR-Werte in der Ausgabe - sie sollten sich ändern, wenn du dich drehst.\n")
    
    # Erstelle Kamera
    print("Erstelle DXCAM-Kamera...")
    camera = dxcam.create(output_color="BGR")
    screen_width = camera.width
    screen_height = camera.height
    print(f"Bildschirmauflösung: {screen_width}x{screen_height}")
    
    print("\n" + "=" * 60)
    print("Starte Blickrichtung-Test...")
    print("Schau in verschiedene Himmelsrichtungen (Norden, Osten, Süden, Westen)")
    print("Drücke Ctrl+C zum Beenden")
    print("=" * 60 + "\n")
    
    frame_count = 0
    
    try:
        while True:
            frame_count += 1
            
            region = get_wow_region(screen_width, screen_height)
            if not region:
                if frame_count == 1 or frame_count % 30 == 0:
                    print("[WARNUNG] WoW-Fenster nicht gefunden!")
                time.sleep(1)
                continue
            
            try:
                frame = camera.grab(region=region)
            except Exception as e:
                print(f"[FEHLER] Fehler beim Erfassen des Frames: {e}")
                time.sleep(1)
                continue
            
            if frame is None:
                continue
            
            try:
                h, w = frame.shape[:2]
                
                # Prüfe ob Position innerhalb des Frames liegt
                if (pixel_facing_coord[0] < 0 or pixel_facing_coord[0] >= w or 
                    pixel_facing_coord[1] < 0 or pixel_facing_coord[1] >= h):
                    if frame_count == 1:
                        print(f"[WARNUNG] Facing-Pixel-Position ({pixel_facing_coord[0]}, {pixel_facing_coord[1]}) außerhalb des Frames ({w}x{h})")
                    continue
                
                # Lese Pixel an der konfigurierten Position
                facing_pixel = frame[pixel_facing_coord[1], pixel_facing_coord[0]]
                
                # Debug: Zeige BGR-Werte
                b, g, r = int(facing_pixel[0]), int(facing_pixel[1]), int(facing_pixel[2])
                
                # Dekodiere Wert
                facing_value = decode_facing_pixel(facing_pixel)
                
                if facing_value is not None:
                    # Zeige alle 10 Frames (oder bei Änderung)
                    if frame_count == 1 or frame_count % 10 == 0:
                        direction = get_direction_name(facing_value)
                        # Zeige auch BGR-Werte und normalisierten Wert für Debugging
                        normalized = decode_24bit_pixel(facing_pixel, normalize=True)
                        value_24bit = decode_24bit_pixel(facing_pixel, normalize=False)
                        
                        # Zeige auch die erwartete Himmelsrichtung basierend auf Gradzahl
                        expected_direction = ""
                        if 0 <= facing_value < 22.5 or facing_value >= 337.5:
                            expected_direction = "Norden (0°)"
                        elif 67.5 <= facing_value < 112.5:
                            expected_direction = "Osten (90°)"
                        elif 157.5 <= facing_value < 202.5:
                            expected_direction = "Süden (180°)"
                        elif 247.5 <= facing_value < 292.5:
                            expected_direction = "Westen (270°)"
                        else:
                            expected_direction = f"Zwischenrichtung"
                        
                        print(f"Frame {frame_count}: Blickrichtung = {facing_value:.2f}°")
                        print(f"  Erwartete Richtung (basierend auf Gradzahl): {expected_direction}")
                        print(f"  Angezeigte Richtung (get_direction_name): {direction}")
                        print(f"  BGR=({b}, {g}, {r}), 24-Bit={int(value_24bit)}, Normalisiert={normalized:.6f}")
                        
                        # Warnung entfernt - spammt zu viel
                
            except Exception as e:
                print(f"[FEHLER] Fehler beim Lesen der Blickrichtung: {e}")
                import traceback
                traceback.print_exc()
            
            time.sleep(0.1)  # 10 FPS
            
    except KeyboardInterrupt:
        print("\n\n[STATUS] Test beendet durch Benutzer (Ctrl+C)")
    except Exception as e:
        print(f"\n[FEHLER] Unerwarteter Fehler: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("[STATUS] Test-Script beendet.")

if __name__ == "__main__":
    main()

