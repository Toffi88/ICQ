"""
Tool zum Finden der Pixel-Position für WeakAuras
Zeigt einen Screenshot des WoW-Fensters und lässt dich die Position anklicken
"""

import cv2
import dxcam
import numpy as np
import pygetwindow as gw
import time

WINDOW_TITLE = "World of Warcraft"

def validate_region(region, screen_width, screen_height):
    """Validiert und korrigiert die Region."""
    if region is None:
        return None
    
    left, top, right, bottom = region
    left = max(0, min(left, screen_width - 1))
    top = max(0, min(top, screen_height - 1))
    right = max(left + 1, min(right, screen_width))
    bottom = max(top + 1, min(bottom, screen_height))
    
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
        return validate_region(region, screen_width, screen_height)
    except Exception as e:
        print(f"[FEHLER] Fehler beim Abrufen des WoW-Fensters: {e}")
        return None

def mouse_callback(event, x, y, flags, param):
    """Callback für Mausklicks im OpenCV-Fenster."""
    if event == cv2.EVENT_LBUTTONDOWN:
        # Speichere die Position
        param['clicked'] = True
        param['x'] = x
        param['y'] = y
        print(f"\n[KLICK] Position geklickt: ({x}, {y})")

def main():
    print("=" * 60)
    print("WeakAura Pixel-Position Finder")
    print("=" * 60)
    print(f"Suche nach WoW-Fenster: '{WINDOW_TITLE}'")
    
    # Erstelle Kamera
    print("Erstelle DXCAM-Kamera...")
    camera = dxcam.create(output_color="BGR")
    screen_width = camera.width
    screen_height = camera.height
    print(f"Bildschirmauflösung: {screen_width}x{screen_height}")
    
    # Hole WoW-Fenster
    region = get_wow_region(screen_width, screen_height)
    if not region:
        print("[FEHLER] WoW-Fenster nicht gefunden!")
        return
    
    print(f"WoW-Fenster gefunden: {region}")
    left, top, right, bottom = region
    
    # Mache Screenshot
    print("\nMache Screenshot des WoW-Fensters...")
    try:
        frame = camera.grab(region=region)
    except Exception as e:
        print(f"[FEHLER] Fehler beim Erfassen des Screenshots: {e}")
        return
    
    if frame is None:
        print("[FEHLER] Konnte keinen Screenshot machen!")
        return
    
    h, w = frame.shape[:2]
    print(f"Screenshot erfasst: {w}x{h} Pixel")
    
    # Zeichne Hilfslinien (alle 100 Pixel)
    display_frame = frame.copy()
    for i in range(0, w, 100):
        cv2.line(display_frame, (i, 0), (i, h), (100, 100, 100), 1)
        if i > 0:
            cv2.putText(display_frame, str(i), (i + 5, 20), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    
    for i in range(0, h, 100):
        cv2.line(display_frame, (0, i), (w, i), (100, 100, 100), 1)
        if i > 0:
            cv2.putText(display_frame, str(i), (5, i + 15), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
    
    # Zeichne aktuelle Positionen (KORREKTE Positionen - diese müssen in wow_live_bot.py verwendet werden)
    # Diese Positionen zeigen, wo die WeakAura-Pixel tatsächlich sein sollten
    # X-Koordinate (Lila) - Position (60, 355) relativ zum Fenster
    cv2.circle(display_frame, (60, 355), 10, (255, 0, 255), 2)
    cv2.putText(display_frame, "X (60, 355)", (65, 350), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1)
    
    # Y-Koordinate (Rot) - Position (60, 500) relativ zum Fenster
    cv2.circle(display_frame, (60, 500), 10, (0, 0, 255), 2)
    cv2.putText(display_frame, "Y (60, 500)", (65, 495), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    
    # Facing (Beige) - Position (60, 600) relativ zum Fenster
    cv2.circle(display_frame, (60, 600), 10, (0, 200, 255), 2)
    cv2.putText(display_frame, "F (60, 600)", (65, 595), 
               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
    
    # Parameter für Mausklick
    click_params = {'clicked': False, 'x': 0, 'y': 0}
    
    # Zeige Bild
    print("\n" + "=" * 60)
    print("ANLEITUNG:")
    print("1. Klicke auf die Position der WeakAura-Pixel im Bild")
    print("2. Die Position wird in der Konsole angezeigt")
    print("3. Drücke 'q' im Bild-Fenster zum Beenden")
    print("=" * 60 + "\n")
    
    cv2.namedWindow("WoW Screenshot - Klicke auf Pixel-Position", cv2.WINDOW_NORMAL)
    cv2.setMouseCallback("WoW Screenshot - Klicke auf Pixel-Position", mouse_callback, click_params)
    
    # Skaliere Bild für bessere Ansicht (falls zu groß)
    max_display_width = 1920
    max_display_height = 1080
    scale = min(max_display_width / w, max_display_height / h, 1.0)
    if scale < 1.0:
        new_w = int(w * scale)
        new_h = int(h * scale)
        display_frame = cv2.resize(display_frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        # Skaliere auch die Klick-Positionen
        click_params['scale'] = scale
    else:
        click_params['scale'] = 1.0
    
    while True:
        cv2.imshow("WoW Screenshot - Klicke auf Pixel-Position", display_frame)
        
        if click_params['clicked']:
            # Berechne tatsächliche Position (berücksichtige Skalierung)
            actual_x = int(click_params['x'] / click_params['scale'])
            actual_y = int(click_params['y'] / click_params['scale'])
            
            # Lese Pixel-Wert an dieser Position
            if 0 <= actual_x < w and 0 <= actual_y < h:
                pixel = frame[actual_y, actual_x]
                b, g, r = int(pixel[0]), int(pixel[1]), int(pixel[2])
                
                print(f"\n{'='*60}")
                print(f"Position gefunden: ({actual_x}, {actual_y})")
                print(f"BGR-Werte: ({b}, {g}, {r})")
                print(f"Format für Code: pixel_facing_coord = ({actual_x}, {actual_y})")
                print(f"{'='*60}\n")
            
            click_params['clicked'] = False
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
    
    cv2.destroyAllWindows()
    print("[STATUS] Tool beendet.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[STATUS] Tool durch Benutzer beendet (Ctrl+C)")
    except Exception as e:
        print(f"\n[FEHLER] Unerwarteter Fehler: {e}")
        import traceback
        traceback.print_exc()

