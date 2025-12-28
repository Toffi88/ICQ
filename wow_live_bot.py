import cv2
import dxcam
import numpy as np
import os
import pydirectinput
import time
import pygetwindow as gw
from ultralytics import YOLO
import random
import math

# Windows API für Mausstatus-Prüfung
try:
    import win32api
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("[WARNUNG] win32api nicht verfügbar. Benutzer-Interventionserkennung deaktiviert.")

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



class HumanInput:
    def __init__(self):
        # Konfiguration der "Menschlichkeit"
        self.center_x = 0  # Wird später gesetzt
        self.center_y = 0
        
        # Deadzone: Wenn das Ziel innerhalb von X Pixeln ist, nichts tun (verhindert Zittern)
        self.deadzone = 30 
        
        # Geschwindigkeit: Wie aggressiv dreht sich der Bot? (Niedriger = langsamer)
        self.speed_factor = 0.15  # Deutlich langsamer für präzisere Bewegungen
        
        # Vertikale Steuerung: Weniger präzise, nur um Ziel in oberer Hälfte zu halten
        self.vertical_deadzone = 100  # Große Deadzone für vertikale Bewegung
        self.vertical_speed_factor = 0.08  # Langsamer für weniger präzise Bewegung
        self.upper_half_threshold = 0.5  # Ziel sollte in oberen 50% des Bildschirms sein 
        
        # Status der rechten Maustaste
        self.rmb_held = False
        
        # Benutzer-Interventionserkennung
        self.last_mouse_pos = None
        self.last_bot_move_time = 0
        self.user_intervening = False
        self.intervention_start_time = 0  # Zeitpunkt, zu dem die Intervention begann
        self.intervention_timeout = 0.3  # Sekunden, nach denen wir annehmen, dass der Benutzer fertig ist
        
        # DirectInput Konfiguration für schnellere Reaktion
        pydirectinput.PAUSE = 0.001 
        pydirectinput.FAILSAFE = False

    def update_center(self, w, h):
        self.center_x = w // 2
        self.center_y = h // 2
    
    def _get_mouse_state(self):
        """Holt den aktuellen Status der Maus (Position und Tasten) von Windows."""
        if not WIN32_AVAILABLE:
            return None, None
        
        try:
            pos = win32api.GetCursorPos()
            # Prüfe rechte Maustaste: VK_RBUTTON = 0x02
            rmb_pressed = win32api.GetAsyncKeyState(0x02) & 0x8000 != 0
            return pos, rmb_pressed
        except Exception as e:
            return None, None
    
    def check_user_intervention(self):
        """Prüft, ob der Benutzer die Maus benutzt. Gibt True zurück, wenn der Bot pausieren sollte."""
        if not WIN32_AVAILABLE:
            return False
        
        current_pos, rmb_pressed = self._get_mouse_state()
        
        if current_pos is None:
            return False
        
        current_time = time.time()
        
        # Wenn wir gerade eine Bewegung gemacht haben (innerhalb von 150ms), 
        # aktualisiere die erwartete Position und synchronisiere den Status
        if current_time - self.last_bot_move_time < 0.15:  # Innerhalb von 150ms nach Bot-Bewegung
            self.last_mouse_pos = current_pos
            # Synchronisiere den Status der rechten Maustaste
            if rmb_pressed != self.rmb_held:
                self.rmb_held = rmb_pressed
            # Wenn wir gerade eine Bot-Bewegung gemacht haben, ist es keine Intervention
            if self.user_intervening:
                self.user_intervening = False
                self.intervention_start_time = 0
            return False
        
        # Prüfe auf unerwartete Mausbewegung (nur wenn wir NICHT gerade eine Bot-Bewegung gemacht haben)
        if self.last_mouse_pos is not None:
            dx = abs(current_pos[0] - self.last_mouse_pos[0])
            dy = abs(current_pos[1] - self.last_mouse_pos[1])
            
            # Wenn die Maus sich mehr als 10 Pixel bewegt hat (ohne Bot-Bewegung), 
            # hat wahrscheinlich der Benutzer eingegriffen
            if dx > 10 or dy > 10:
                if not self.user_intervening:
                    # Neue Intervention beginnt
                    self.intervention_start_time = current_time
                self.user_intervening = True
                # Synchronisiere den Status der rechten Maustaste
                if rmb_pressed != self.rmb_held:
                    self.rmb_held = rmb_pressed
                # Aktualisiere die Position, damit wir nicht ständig intervenieren
                self.last_mouse_pos = current_pos
                return True
        
        # Prüfe auf manuelle Änderung der rechten Maustaste
        if rmb_pressed != self.rmb_held:
            # Der Benutzer hat die Taste manuell gedrückt oder losgelassen
            if not self.user_intervening:
                self.intervention_start_time = current_time
            self.user_intervening = True
            self.rmb_held = rmb_pressed
            return True
        
        # Wenn der Benutzer eingegriffen hat, aber seit einer Weile nichts mehr passiert ist,
        # nehmen wir an, dass er fertig ist
        if self.user_intervening:
            # Verwende intervention_start_time statt last_bot_move_time
            if self.intervention_start_time > 0:
                time_since_intervention = current_time - self.intervention_start_time
                if time_since_intervention > self.intervention_timeout:
                    # Intervention beendet - Bot kann weitermachen
                    self.user_intervening = False
                    self.intervention_start_time = 0
                    self.last_mouse_pos = current_pos
                    return False
            return True
        
        # Aktualisiere die letzte bekannte Position
        self.last_mouse_pos = current_pos
        return False

    def _hold_rmb(self, hold=True):
        """Verwaltet den Rechtsklick-Status intelligent."""
        if hold and not self.rmb_held:
            pydirectinput.mouseDown(button='right')
            self.rmb_held = True
            time.sleep(random.uniform(0.05, 0.1)) # Kurze Pause wie beim echten Drücken
        elif not hold and self.rmb_held:
            pydirectinput.mouseUp(button='right')
            self.rmb_held = False
            time.sleep(random.uniform(0.05, 0.1))

    def move_mouse_human(self, target_x, target_y=None, scan_region=None):
        """Bewegt die Maus horizontal und vertikal Richtung Ziel mit menschlicher Beschleunigung.
        
        Args:
            target_x: Absolute X-Koordinate des Ziels (präzise Steuerung)
            target_y: Absolute Y-Koordinate des Ziels (optional, weniger präzise - nur obere Hälfte)
            scan_region: Scan-Region als (left, top, right, bottom) Tupel (optional, für obere Grenze-Erkennung)
        """
        # WICHTIG: Prüfe zuerst, ob der Benutzer eingreift
        if self.check_user_intervention():
            # Benutzer benutzt die Maus - pausiere den Bot
            return
        
        if target_x is None:
            # Ziel verloren? Taste NICHT sofort loslassen, sondern kurz halten
            # und dann langsam loslassen, um nicht ruckartig zu stoppen
            # Wir lassen die Taste nur los, wenn wir länger kein Ziel haben
            # (wird durch wiederholte Aufrufe mit None gehandhabt)
            if self.rmb_held:
                # Nur loslassen, wenn wir mehrere Frames kein Ziel haben
                # Für jetzt halten wir die Taste, damit die Kamera nicht ruckartig stoppt
                pass
            return

        offset_x = target_x - self.center_x
        distance = abs(offset_x)

        # 1. Deadzone Check: Sind wir nah genug? Dann chillen.
        if distance < self.deadzone:
            # Im Ziel - Taste kann gehalten bleiben für sanfte Bewegung
            # Oder loslassen für präzises Zielen (kommentiert aus)
            # self._hold_rmb(False) 
            return

        # 2. Taste drücken - WICHTIG: Immer vor der Bewegung
        self._hold_rmb(True)

        # 3. Berechnung der Bewegung (Humanizing Math)
        # Wir nutzen eine Wurzel- oder Log-Funktion, damit weite Distanzen schnell
        # und kurze Distanzen langsam sind.
        # Formel: (Offset * Speed) + Random Noise
        
        # Basis-Geschwindigkeit (Progressiv)
        move_x = int(offset_x * self.speed_factor)
        
        # Begrenzung (Clamping), damit sich der Char nicht im Kreis dreht wie verrückt
        max_step = 20  # Maximale Pixel pro "Tick" - deutlich reduziert
        move_x = max(min(move_x, max_step), -max_step)

        # Wenn wir sehr nah sind, erzwinge kleine Schritte, sonst bleiben wir stecken
        if abs(move_x) < 1:
            move_x = 1 if offset_x > 0 else -1

        # 4. Zufällige Varianz (Jitter)
        # Menschen ziehen die Maus nie perfekt gerade.
        # Wir fügen manchmal etwas mehr oder weniger hinzu.
        jitter = random.randint(-2, 2)
        move_x += jitter

        # 5. Vertikale Steuerung (weniger präzise - nur obere Hälfte)
        move_y = 0
        if target_y is not None:
            screen_mid_y = self.center_y  # Mitte des Bildschirms
            offset_y = target_y - screen_mid_y
            
            # Prüfe zuerst, ob das Ziel sehr hoch im Scan-Bildschirm ist (obere 20% der Scan-Region)
            # Wenn ja, bewege nach unten (positiv), damit die Kamera nach oben schwenkt
            # und das Ziel mehr in die Mitte kommt
            if scan_region is not None:
                left, top, right, bottom = scan_region
                scan_region_height = bottom - top
                
                # Berechne relative Position des Ziels innerhalb der Scan-Region
                # 0.0 = ganz oben, 1.0 = ganz unten
                relative_y_in_region = (target_y - top) / scan_region_height if scan_region_height > 0 else 0.5
                
                # Wenn Ziel im oberen 20% der Scan-Region ist (relative_y < 0.20)
                if relative_y_in_region < 0.20:
                    # Ziel ist sehr hoch - bewege nach oben (negativ), damit Kamera nach oben schwenkt
                    # Berechne Distanz vom oberen Rand (je näher am Rand, desto stärker die Bewegung)
                    distance_from_top = relative_y_in_region * scan_region_height
                    # Umso näher am oberen Rand (kleiner distance_from_top), desto stärker bewegen
                    # Negativ = nach oben (Kamera schwenkt nach oben)
                    move_y = int(-(0.20 - relative_y_in_region) * scan_region_height * self.vertical_speed_factor * 2)
                    
                    # Begrenzung für vertikale Bewegung nach oben (negativ)
                    max_vertical_step = 15
                    move_y = max(min(move_y, -3), -max_vertical_step)  # Immer nach oben (negativ), mindestens 3 Pixel
            
            # Wenn nicht zu weit oben, prüfe ob Ziel in unterer Hälfte
            if move_y == 0:  # Nur wenn wir noch keine Bewegung berechnet haben
                # Nur bewegen, wenn Ziel in unterer Hälfte (positive offset_y bedeutet unten)
                if offset_y > 0:  # Ziel ist unterhalb der Mitte
                    # Berechne Bewegung nach oben (negativ)
                    # Weniger präzise: größere Deadzone, langsamere Bewegung
                    if abs(offset_y) > self.vertical_deadzone:
                        move_y = int(-offset_y * self.vertical_speed_factor)  # Negativ = nach oben
                        
                        # Begrenzung für vertikale Bewegung (weniger aggressiv)
                        max_vertical_step = 15  # Maximal 15 Pixel pro Tick
                        move_y = max(min(move_y, -2), -max_vertical_step)  # Immer nach oben, mindestens 2 Pixel
                    else:
                        # Innerhalb der Deadzone - kleine zufällige Bewegung für Realismus
                        move_y = random.randint(-1, 0)
                else:
                    # Ziel ist bereits in oberer Hälfte - nur kleiner Jitter
                    move_y = random.randint(-1, 1)
        else:
            # Kein target_y - nur kleiner Jitter für Realismus
            move_y = random.randint(-1, 1)

        # 6. Ausführung
        # Die Taste sollte bereits in Schritt 2 gedrückt sein
        # Kurze Pause, damit das Spiel die Bewegung registriert
        time.sleep(random.uniform(0.01, 0.02))
        pydirectinput.moveRel(move_x, move_y, relative=True)
        
        # Aktualisiere die Zeit der letzten Bot-Bewegung für Interventionserkennung
        self.last_bot_move_time = time.time()
        
        # Aktualisiere die erwartete Mausposition
        if WIN32_AVAILABLE:
            try:
                current_pos, _ = self._get_mouse_state()
                if current_pos:
                    self.last_mouse_pos = current_pos
            except:
                pass

        # 7. "Micro-Sleeps" - Das 'Chillen'
        # Je näher wir am Ziel sind, desto vorsichtiger werden wir.
        if distance < 100:
            time.sleep(random.uniform(0.015, 0.030)) # Feinjustierung - länger
        else:
            time.sleep(random.uniform(0.010, 0.020)) # Schnellere Drehung - aber immer noch kontrolliert

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

        # Initialisiere Human Input
        self.human_input = HumanInput()
    
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

    def adjust_region_for_scanning(self, region):
        """Passt die Region an, um obere 5% und untere 15% auszuschließen."""
        if region is None:
            return None
        
        left, top, right, bottom = region
        region_height = bottom - top
        
        # Berechne die auszuschließenden Bereiche
        exclude_top = int(region_height * 0.05)  # Obere 5%
        exclude_bottom = int(region_height * 0.15)  # Untere 15%
        
        # Neue Region: top erhöhen, bottom verringern
        new_top = top + exclude_top
        new_bottom = bottom - exclude_bottom
        
        # Sicherstellen, dass die neue Region gültig ist
        if new_bottom <= new_top:
            return region  # Falls ungültig, Original zurückgeben
        
        return (left, new_top, right, new_bottom)

    def run(self):
        print("[STATUS] ========================================")
        print("[STATUS] Bot gestartet!")
        print("[STATUS] ========================================")
        print(f"[STATUS] Suche nach WoW-Fenster: '{WINDOW_TITLE}'")
        print("[STATUS] Warte 3 Sekunden...")
        time.sleep(3)
        
        frame_count = 0
        print("[STATUS] Starte Hauptschleife...")
        
        # FPS-Berechnung
        fps_start_time = time.time()
        fps_frame_count = 0
        current_fps = 0.0
        
        # Verzögerungsmessung
        latency_start_time = 0.0
        current_latency = 0.0
        
        # WICHTIG: Setze die Mitte für die HumanInput Klasse, sobald wir die Größe kennen
        # Da wir dxcam nutzen, ist self.screen_width/height schon da.
        self.human_input.update_center(self.screen_width, self.screen_height)
        
        # Initialisiere die Mausposition für Interventionserkennung
        if WIN32_AVAILABLE:
            try:
                pos, rmb_pressed = self.human_input._get_mouse_state()
                if pos:
                    self.human_input.last_mouse_pos = pos
                    self.human_input.rmb_held = rmb_pressed
                    print(f"[STATUS] Mausposition initialisiert: {pos}, RMB: {rmb_pressed}")
            except Exception as e:
                print(f"[WARNUNG] Konnte Mausposition nicht initialisieren: {e}")
        
        print("[STATUS] Drücke 'Q' zum Beenden (oder Ctrl+C)")
        
        while True:
            frame_count += 1
            fps_frame_count += 1
            
            # FPS berechnen (alle Sekunde aktualisieren)
            if fps_frame_count >= 30:  # Alle 30 Frames aktualisieren
                elapsed = time.time() - fps_start_time
                if elapsed > 0:
                    current_fps = fps_frame_count / elapsed
                fps_start_time = time.time()
                fps_frame_count = 0
            
            if frame_count % 30 == 0:  # Alle 30 Frames einen Status
                print(f"[STATUS] Läuft... (Frame {frame_count}, FPS: {current_fps:.1f}, Latenz: {current_latency*1000:.1f}ms)")
            
            region = self.get_wow_region()
            if not region:
                if frame_count == 1 or frame_count % 10 == 0:  # Nur gelegentlich melden
                    print("[WARNUNG] WoW-Fenster nicht gefunden. Stelle sicher, dass WoW geöffnet ist!")
                time.sleep(2)
                continue

            # Region für Scanning anpassen (obere 5% und untere 15% ausschließen)
            scan_region = self.adjust_region_for_scanning(region)

            if frame_count == 1:
                print(f"[STATUS] WoW-Fenster gefunden! Region: {region}")
                print(f"[STATUS] Scan-Region (ohne obere 5% und untere 15%): {scan_region}")
                print(f"[STATUS] Region-Validierung: left={region[0]}, top={region[1]}, right={region[2]}, bottom={region[3]}")
                print(f"[STATUS] Bildschirmgrenzen: 0-{self.screen_width} x 0-{self.screen_height}")
                print("[STATUS] Starte Bildaufnahme...")

            # Verzögerungsmessung starten
            latency_start_time = time.time()
            
            try:
                frame = self.camera.grab(region=scan_region)
            except ValueError as e:
                print(f"[FEHLER] Ungültige Region für DXCAM: {e}")
                print(f"[FEHLER] Region war: {scan_region}")
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
            
            # Verzögerungsmessung beenden
            current_latency = time.time() - latency_start_time
            
            # Visualisierung für Detection View
            detection_frame = self.draw_detections(frame, results, offset=(0, 0))
            
            target_x = None  # Reset target
            target_y = None  # Reset target
            
            if len(results[0].boxes) > 0:
                # Nimm das Box mit der höchsten Confidence oder das, das der Mitte am nächsten ist
                # Hier nehmen wir einfach das erste (meistens das sicherste)
                box = results[0].boxes[0].xywh[0].cpu().numpy()
                
                # Box[0] ist center_x relativ zum aufgenommenen Frame
                # Box[1] ist center_y relativ zum aufgenommenen Frame
                # Wir müssen den Offset der Region beachten!
                # Da scan_region = adjust_region_for_scanning(region) ist, 
                # müssen wir die absolute Bildschirmposition berechnen.
                
                local_center_x = float(box[0])
                local_center_y = float(box[1])
                
                # Absolutes X auf dem Monitor = Region Links + Lokales X
                absolute_target_x = scan_region[0] + local_center_x
                # Absolutes Y auf dem Monitor = Region Top + Lokales Y
                absolute_target_y = scan_region[1] + local_center_y
                
                target_x = absolute_target_x
                target_y = absolute_target_y
                
                # Visualisierung
                conf = float(results[0].boxes[0].conf[0].cpu().numpy())
                print(f"[DETECTION] Ziel gefunden bei ({local_center_x:.1f}, {local_center_y:.1f}), Conf: {conf:.2f}")
            else:
                # Optional: TAB drücken wenn nichts gefunden
                pass
            
            # --- HIER KOMMT DIE BEWEGUNG REIN ---
            # Wir übergeben die absolute X- und Y-Koordinate des Ziels. 
            # Die Klasse weiß selbst, wo die Bildschirmmitte ist.
            # X ist präzise, Y ist weniger präzise (nur obere Hälfte).
            # Übergebe auch die gesamte Scan-Region für obere Grenze-Erkennung
            self.human_input.move_mouse_human(target_x, target_y, scan_region)

            # Prüfe Q-Taste zum Beenden (funktioniert auch ohne GUI)
            should_exit = False
            if WIN32_AVAILABLE:
                try:
                    # Prüfe ob Q-Taste gedrückt ist (VK_Q = 0x51)
                    q_pressed = win32api.GetAsyncKeyState(0x51) & 0x8000 != 0
                    if q_pressed:
                        should_exit = True
                except:
                    pass
            
            # Visuelle Kontrolle - Detection View mit Bounding Boxes und Wahrscheinlichkeiten
            if self.show_gui:
                try:
                    # FPS und Latenz auf Frame zeichnen
                    fps_text = f"FPS: {current_fps:.1f}"
                    latency_text = f"Latenz: {current_latency*1000:.1f}ms"
                    
                    # Hintergrund für Text
                    cv2.rectangle(detection_frame, (10, 10), (250, 70), (0, 0, 0), -1)
                    
                    # FPS-Text
                    cv2.putText(detection_frame, fps_text, (15, 35), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    
                    # Latenz-Text
                    cv2.putText(detection_frame, latency_text, (15, 60), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                    
                    # Berechne Skalierung basierend auf Originalgröße
                    h, w = detection_frame.shape[:2]
                    scale = min(DISPLAY_WIDTH / w, DISPLAY_HEIGHT / h)
                    new_w = int(w * scale)
                    new_h = int(h * scale)
                    resized = cv2.resize(detection_frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                    cv2.imshow("Detection View", resized)
                    
                    if cv2.waitKey(1) & 0xFF == ord('q'): 
                        should_exit = True
                except Exception as e:
                    # Falls GUI während der Laufzeit fehlschlägt, deaktiviere sie
                    self.show_gui = False
                    print(f"[WARNUNG] GUI deaktiviert: {e}")
            
            # Beende Schleife wenn Q gedrückt wurde
            if should_exit:
                print("\n[STATUS] Q-Taste gedrückt - Bot wird beendet...")
                break

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