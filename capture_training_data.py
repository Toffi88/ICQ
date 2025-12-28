import dxcam
import cv2
import time
import os
import pygetwindow as gw
from datetime import datetime

# EINSTELLUNGEN
SAVE_FOLDER = "wow_training_data"
INTERVAL = 2  # Alle 3 Sekunden ein Bild
WINDOW_TITLE = "World of Warcraft" # Muss exakt so heißen wie das Fenster

if not os.path.exists(SAVE_FOLDER):
    os.makedirs(SAVE_FOLDER)

def validate_and_clip_region(region, screen_width, screen_height):
    """Validiert und begrenzt die Region auf die Bildschirmgrenzen."""
    left, top, right, bottom = region
    
    # Begrenze auf Bildschirmgrenzen
    left = max(0, min(left, screen_width - 1))
    top = max(0, min(top, screen_height - 1))
    right = max(left + 1, min(right, screen_width))
    bottom = max(top + 1, min(bottom, screen_height))
    
    return (left, top, right, bottom)

def capture_training_data():
    print(f"Suche nach Fenster: {WINDOW_TITLE}...")
    
    # DXCAM Kamera initialisieren
    camera = dxcam.create(output_color="BGR")
    
    # Bildschirmauflösung ermitteln
    screen_width = camera.width
    screen_height = camera.height
    print(f"Bildschirmauflösung: {screen_width}x{screen_height}")
    
    while True:
        try:
            # WoW Fenster finden
            window = gw.getWindowsWithTitle(WINDOW_TITLE)[0]
            
            if window:
                # Fenster-Region für Screenshot bestimmen
                left = window.left
                top = window.top
                right = window.left + window.width
                bottom = window.top + window.height
                
                # Region validieren und auf Bildschirmgrenzen begrenzen
                region = validate_and_clip_region(
                    (left, top, right, bottom),
                    screen_width,
                    screen_height
                )
                
                # Prüfe ob Fenster sichtbar ist (nicht minimiert)
                if window.width > 0 and window.height > 0:
                    frame = None
                    
                    # Versuche zuerst direkte Region-Aufnahme
                    try:
                        # Prüfe ob Region innerhalb der Bildschirmgrenzen liegt
                        if (left >= 0 and top >= 0 and 
                            right <= screen_width and bottom <= screen_height and
                            left < right and top < bottom):
                            frame = camera.grab(region=region)
                    except Exception as e:
                        print(f"Region-Aufnahme fehlgeschlagen: {e}")
                    
                    # Fallback: Nimm gesamten Bildschirm auf und schneide Fenster aus
                    if frame is None:
                        try:
                            print("Versuche Fallback: Gesamter Bildschirm...")
                            full_screen = camera.grab()
                            if full_screen is not None:
                                # Berechne relative Position im Screenshot
                                # dxcam gibt den primären Monitor zurück
                                rel_left = max(0, left)
                                rel_top = max(0, top)
                                rel_right = min(full_screen.shape[1], right)
                                rel_bottom = min(full_screen.shape[0], bottom)
                                
                                # Nur ausschneiden wenn Fenster auf primärem Monitor
                                if (rel_left < rel_right and rel_top < rel_bottom and
                                    rel_right <= full_screen.shape[1] and rel_bottom <= full_screen.shape[0]):
                                    frame = full_screen[rel_top:rel_bottom, rel_left:rel_right]
                                    print(f"Ausgeschnitten: {rel_left}, {rel_top}, {rel_right}, {rel_bottom}")
                                else:
                                    print("Fenster liegt außerhalb des primären Monitors.")
                        except Exception as e:
                            print(f"Fallback fehlgeschlagen: {e}")
                    
                    if frame is not None:
                        # Zeitstempel für Dateinamen
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                        filename = os.path.join(SAVE_FOLDER, f"shot_{timestamp}.png")
                        
                        # Bild speichern
                        cv2.imwrite(filename, frame)
                        
                        print(f"Gespeichert: {filename}")
                    else:
                        print("Screenshot fehlgeschlagen. Versuche erneut...")
                else:
                    print("Fenster ist minimiert oder hat keine Größe.")
                    
            time.sleep(INTERVAL)
            
        except IndexError:
            print("WoW Fenster nicht gefunden. Bitte starten...")
            time.sleep(10)
        except KeyboardInterrupt:
            print("Aufnahme gestoppt.")
            break
        except Exception as e:
            print(f"Fehler: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    capture_training_data()

