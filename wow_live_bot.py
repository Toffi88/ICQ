import cv2
import dxcam
import numpy as np
import os
import pydirectinput
import time
import pygetwindow as gw
from ultralytics import YOLO

# --- KONFIGURATION ---
WINDOW_TITLE = "World of Warcraft"
SEARCH_IMGSZ = 1280  # Hohe Auflösung für weite Entfernungen
CONF_THRESHOLD = 0.45
DISPLAY_WIDTH = 1280  # Breite des Anzeigefensters
DISPLAY_HEIGHT = 720  # Höhe des Anzeigefensters

# Pfade zu deinen Modellen
print("[STATUS] Initialisiere Modell-Pfade...")
script_dir = os.path.dirname(os.path.abspath(__file__))
print(f"[STATUS] Script-Verzeichnis: {script_dir}")

print("[STATUS] Lade Modell: White Skull...")
model_white_skull = YOLO(os.path.join(script_dir, r"runs\detect\Google_Skull1\weights\best.pt"))
print("[STATUS] White Skull Modell geladen!")

class WoWBot:
    def __init__(self):
        print("[STATUS] Initialisiere WoWBot...")
        print("[STATUS] Erstelle DXCAM-Kamera...")
        self.camera = dxcam.create(output_color="BGR")
        print("[STATUS] Kamera erstellt!")
        
        # Hole Bildschirmauflösung von der Kamera
        self.screen_width = self.camera.width
        self.screen_height = self.camera.height
        print(f"[STATUS] Bildschirmauflösung: {self.screen_width}x{self.screen_height}")
        
        self.active_model = model_white_skull # Standardmodell
        print("[STATUS] Aktives Modell: White Skull")
        print("[STATUS] Prüfe GUI-Unterstützung...")
        self.show_gui = self._check_gui_support()
        if self.show_gui:
            print("[STATUS] GUI-Unterstützung: Aktiviert")
        else:
            print("[STATUS] GUI-Unterstützung: Deaktiviert")
        print("[STATUS] WoWBot initialisiert!")
    
    def _check_gui_support(self):
        """Prüft ob OpenCV GUI-Funktionen verfügbar sind."""
        try:
            # Teste ob cv2.imshow() funktioniert
            test_img = np.zeros((100, 100, 3), dtype=np.uint8)
            cv2.imshow("test", test_img)
            cv2.destroyAllWindows()
            return True
        except Exception as e:
            print(f"[WARNUNG] OpenCV GUI nicht verfügbar: {e}")
            print("[WARNUNG] Detection View wird nicht angezeigt.")
            return False

    def validate_region(self, region):
        """Validiert und korrigiert die Region, damit sie innerhalb des Bildschirms liegt."""
        if region is None:
            return None
        
        left, top, right, bottom = region
        
        # Stelle sicher, dass die Koordinaten innerhalb des Bildschirms liegen
        left = max(0, min(left, self.screen_width - 1))
        top = max(0, min(top, self.screen_height - 1))
        right = max(left + 1, min(right, self.screen_width))
        bottom = max(top + 1, min(bottom, self.screen_height))
        
        # Stelle sicher, dass right > left und bottom > top
        if right <= left or bottom <= top:
            return None
        
        return (left, top, right, bottom)

    def get_wow_region(self):
        try:
            windows = gw.getWindowsWithTitle(WINDOW_TITLE)
            if len(windows) == 0:
                return None
            win = windows[0]
            region = (win.left, win.top, win.left + win.width, win.top + win.height)
            
            # Validiere die Region
            validated_region = self.validate_region(region)
            if validated_region != region:
                print(f"[WARNUNG] Region korrigiert: {region} -> {validated_region}")
            
            return validated_region
        except Exception as e:
            print(f"[FEHLER] Fehler beim Abrufen des WoW-Fensters: {e}")
            return None

    def draw_detections(self, frame, results, offset=(0, 0)):
        """Zeichnet Detektionen mit Bounding Boxes und Wahrscheinlichkeiten auf dem Frame."""
        display_frame = frame.copy()
        
        if len(results[0].boxes) > 0:
            boxes = results[0].boxes
            for i, box in enumerate(boxes):
                # Bounding Box Koordinaten (xyxy Format)
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                x1, y1, x2, y2 = int(x1 + offset[0]), int(y1 + offset[1]), int(x2 + offset[0]), int(y2 + offset[1])
                
                # Konfidenzwert
                conf = float(box.conf[0].cpu().numpy())
                conf_percent = conf * 100
                
                # Klasse (falls vorhanden)
                cls = int(box.cls[0].cpu().numpy()) if box.cls is not None else 0
                
                # Farbe basierend auf Konfidenz (grün = hoch, rot = niedrig)
                color_intensity = int(conf * 255)
                color = (0, color_intensity, 255 - color_intensity)
                
                # Bounding Box zeichnen
                cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                
                # Text mit Wahrscheinlichkeit
                label = f"Conf: {conf_percent:.1f}%"
                label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                
                # Hintergrund für Text
                cv2.rectangle(display_frame, 
                            (x1, y1 - label_size[1] - 10), 
                            (x1 + label_size[0] + 5, y1), 
                            color, -1)
                
                # Text zeichnen
                cv2.putText(display_frame, label, (x1 + 2, y1 - 5), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                # Zentrum markieren
                center_x = int((x1 + x2) / 2)
                center_y = int((y1 + y2) / 2)
                cv2.circle(display_frame, (center_x, center_y), 5, color, -1)
        
        return display_frame

    def run(self):
        print("[STATUS] ========================================")
        print("[STATUS] Bot gestartet!")
        print("[STATUS] ========================================")
        print(f"[STATUS] Suche nach WoW-Fenster: '{WINDOW_TITLE}'")
        print("[STATUS] Warte 3 Sekunden...")
        time.sleep(3)
        
        frame_count = 0
        print("[STATUS] Starte Hauptschleife...")
        
        while True:
            frame_count += 1
            if frame_count % 30 == 0:  # Alle 30 Frames einen Status
                print(f"[STATUS] Läuft... (Frame {frame_count})")
            
            region = self.get_wow_region()
            if not region:
                if frame_count == 1 or frame_count % 10 == 0:  # Nur gelegentlich melden
                    print("[WARNUNG] WoW-Fenster nicht gefunden. Stelle sicher, dass WoW geöffnet ist!")
                time.sleep(2)
                continue

            if frame_count == 1:
                print(f"[STATUS] WoW-Fenster gefunden! Region: {region}")
                print(f"[STATUS] Region-Validierung: left={region[0]}, top={region[1]}, right={region[2]}, bottom={region[3]}")
                print(f"[STATUS] Bildschirmgrenzen: 0-{self.screen_width} x 0-{self.screen_height}")
                print("[STATUS] Starte Bildaufnahme...")

            try:
                frame = self.camera.grab(region=region)
            except ValueError as e:
                print(f"[FEHLER] Ungültige Region für DXCAM: {e}")
                print(f"[FEHLER] Region war: {region}")
                print(f"[FEHLER] Bildschirmauflösung: {self.screen_width}x{self.screen_height}")
                time.sleep(2)
                continue
            if frame is None:
                if frame_count == 1 or frame_count % 10 == 0:
                    print("[WARNUNG] Konnte kein Frame erfassen!")
                continue

            if frame_count == 1:
                h, w = frame.shape[:2]
                print(f"[STATUS] Frame erfasst! Größe: {w}x{h}")

            # Suche nach Ziel im gesamten Bild
            results = self.active_model.predict(frame, imgsz=SEARCH_IMGSZ, conf=CONF_THRESHOLD, verbose=False)
            
            # Visualisierung für Detection View
            detection_frame = self.draw_detections(frame, results, offset=(0, 0))
            
            if len(results[0].boxes) > 0:
                # Nimm das erste gefundene Mark (xywh Format: center_x, center_y, width, height)
                box = results[0].boxes[0].xywh[0].cpu().numpy()
                center_x = float(box[0])
                center_y = float(box[1])
                conf = float(results[0].boxes[0].conf[0].cpu().numpy())
                print(f"[DETECTION] Ziel gefunden bei ({center_x:.1f}, {center_y:.1f}), Conf: {conf:.2f}")
            else:
                # Optional: TAB drücken wenn nichts gefunden
                pass

            # Visuelle Kontrolle - Detection View mit Bounding Boxes und Wahrscheinlichkeiten
            if self.show_gui:
                try:
                    if detection_frame is not None:
                        # Berechne Skalierung basierend auf Originalgröße
                        h, w = detection_frame.shape[:2]
                        scale = min(DISPLAY_WIDTH / w, DISPLAY_HEIGHT / h)
                        new_w = int(w * scale)
                        new_h = int(h * scale)
                        resized = cv2.resize(detection_frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                        cv2.imshow("Detection View", resized)
                    else:
                        h, w = frame.shape[:2]
                        scale = min(DISPLAY_WIDTH / w, DISPLAY_HEIGHT / h)
                        new_w = int(w * scale)
                        new_h = int(h * scale)
                        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                        cv2.imshow("Detection View", resized)
                    
                    if cv2.waitKey(1) & 0xFF == ord('q'): 
                        break
                except:
                    # Falls GUI während der Laufzeit fehlschlägt, deaktiviere sie
                    self.show_gui = False
                    print("GUI deaktiviert.")

        if self.show_gui:
            try:
                cv2.destroyAllWindows()
            except:
                pass




if __name__ == "__main__":
    print("[STATUS] ========================================")
    print("[STATUS] Starte WoW Bot Script...")
    print("[STATUS] ========================================")
    try:
        bot = WoWBot()
        bot.run()
    except KeyboardInterrupt:
        print("\n[STATUS] Bot durch Benutzer gestoppt (Ctrl+C)")
    except Exception as e:
        print(f"\n[FEHLER] Unerwarteter Fehler: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("[STATUS] Bot beendet.")