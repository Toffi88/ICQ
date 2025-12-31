"""
================================================================================
KONTEXT FÜR KI-ASSISTENTEN
================================================================================

Zweck dieses Kontext-Blocks:
----------------------------
Dieser Block dient dazu, neuen Chat-Fenstern wichtige Informationen über den Bot
zu übermitteln, damit die KI den Code besser verstehen und weiterentwickeln kann.
Es ist KEINE Versionssammlung, sondern eine Zusammenfassung der Kernfunktionalität.

================================================================================
BEKANNTE PROBLEME / STATUS
================================================================================

WAYPOINT-NAVIGATION:
-------------------
- ✅ Charakter-Ausrichtung funktioniert: Der Bot dreht sich korrekt in Richtung
  des nächsten Waypoints
- ❌ Bewegung zum Ziel funktioniert NICHT: Nach der korrekten Ausrichtung
  bewegt sich der Charakter nicht zum Waypoint, obwohl die W-Taste gedrückt wird
- Problem: Die W-Taste wird zwar gedrückt, aber der Charakter läuft nicht
  in die richtige Richtung oder bewegt sich nicht ausreichend

================================================================================
KERN-FUNKTIONALITÄT
================================================================================

1. TARGET-ERKENNUNG:
   - YOLO-Modell: White Skull Detection (runs/detect/Google_Skull1/weights/best.pt)
   - WeakAura: Liest Range-Status aus Pixel-Farbe (Rot/Grün/Blau/Schwarz)
   - Range-States: OUT_OF_RANGE (Rot), MELEE_RANGE (Grün), IN_RANGE (Blau), NO_TARGET (Schwarz)

2. BEWEGUNGS-LOGIK:
   - W-Taste: Läuft wenn OUT_OF_RANGE, stoppt bei MELEE_RANGE/IN_RANGE
   - Kamera: Präzise horizontal (X), weniger präzise vertikal (Y)
   - Deadzone: center_deadzone_x=120px (Target muss in diesem Bereich sein)

3. TARGET-SUCHE (State-Machine, nicht-blockierend):
   - NO_TARGET → Tab drücken → wenn weiterhin NO_TARGET → ~30° Drehung → Tab
   - Farbwechsel Schwarz→Farbe → F1 drücken (setzt Mark)
   - YOLO findet 5x kein Mark → Drehung
   - WICHTIG: Keine blockierenden Sleeps! State-Machine über mehrere Frames

4. KAMPF-ROTATIONEN (combat.py):
   - MeleeRotation: Taste 2 bei MELEE_RANGE (nur wenn Target in Deadzone)
   - RangeRotation: Taste 3 bei IN_RANGE (nur wenn Target in Deadzone)
   - Automatischer Wechsel zwischen Rotationen
   - Timing: 0.9-1.1 Sekunden (zufällig für menschliche Wirkung)

5. WICHTIGE PRINZIPIEN:
   - Alle Bewegungen/Zeiten enthalten Zufall für menschliche Wirkung
   - Keine blockierenden Sleeps während Target-Suche (FPS-Erhalt)
   - State-Machine für nicht-blockierende Operationen
   - Benutzer-Intervention: Bot pausiert wenn Maus bewegt wird

================================================================================
WICHTIGE KONFIGURATIONEN
================================================================================

- WeakAura-Position: weakuara_offset_x=0, weakuara_offset_y=590 (relativ zur Mitte)
- Speed: speed_factor=0.10 (normal), target_search_speed_factor=0.15 (50% schneller)
- Deadzones: deadzone=30px, center_deadzone_x=120px, vertical_deadzone=100px
- Tab-Delay: 0.1 Sekunden
- Rotation: 15-20 Schritte für nahtlose Bewegung

================================================================================
"""

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

# Windows API für Mausstatus-Prüfung und Fenster-Management
try:
    import win32api
    import win32gui
    import win32con
    WIN32_AVAILABLE = True
except ImportError:
    WIN32_AVAILABLE = False
    print("[WARNUNG] win32api nicht verfügbar. Benutzer-Interventionserkennung deaktiviert.")

# Importiere Combat-Rotationen
from combat import MeleeRotation, RangeRotation

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
        self.speed_factor = 0.10  # Reduziert für smoothere Bewegungen (von 0.15)
        self.target_search_speed_factor = 0.15  # 50% schneller während Target-Suche (0.10 * 1.5)
        self.rotation_speed_factor = 0.50  # Höherer Speed-Factor für Rotation (5x schneller als normal)
        
        # Vertikale Steuerung: Weniger präzise, nur um Ziel in oberer Hälfte zu halten
        self.vertical_deadzone = 100  # Große Deadzone für vertikale Bewegung
        self.vertical_speed_factor = 0.08  # Langsamer für weniger präzise Bewegung
        self.upper_half_threshold = 0.5  # Ziel sollte in oberen 50% des Bildschirms sein 
        
        # Zentrums-Deadzone: Wie nah muss das Ziel horizontal an der Mitte sein, um nach vorne zu laufen?
        # WICHTIG: Nur X-Achse wird geprüft! Y-Achse ist nur für Kamera-Einstellung, nicht für Bewegung.
        # Größerer Bereich, damit der Charakter früher anfängt zu laufen (nicht nur herumstehen)
        self.center_deadzone_x = 120  # Pixel-Toleranz horizontal (größer, damit Charakter läuft)
        
        # WeakAura Position (Offset von der Bildschirmmitte nach oben)
        # TODO: Diese Werte anpassen basierend auf der tatsächlichen Position der WeakAura
        self.weakuara_offset_x = 0  # Horizontal (0 = genau in der Mitte)
        self.weakuara_offset_y = 590  # Vertikal (positiv = nach unten von der Mitte, 400 Pixel tiefer als -100)
        
        # Range-State-Management
        self.current_range_state = None  # OUT_OF_RANGE, MELEE_RANGE, IN_RANGE, UNKNOWN
        self.previous_range_state = None  # Für State-Change-Erkennung
        
        # Target-Suche-State-Management
        self.target_search_mode = True  # True = Suche Target, False = Tracking-Modus
        self.last_tab_press_time = 0  # Zeitpunkt des letzten Tab-Drucks
        self.tab_press_delay = 0.1  # Mindestabstand zwischen Tab-Drücken (reduziert für schnellere Suche)
        self.rotation_count = 0  # Anzahl der 90°-Drehungen bei Target-Suche
        self.max_rotations = 4  # Maximale Anzahl 90°-Drehungen (360°)
        self.rotation_direction = 1  # 1 = rechts, -1 = links
        self.last_range_state_for_f1 = None  # Letzter Range-State für F1-Erkennung
        self.last_f1_press_time = 0  # Zeitpunkt des letzten F1-Drucks
        self.f1_cooldown = 1.5  # Mindestabstand nach F1, bevor weitere Aktionen (Sekunden)
        
        # YOLO-Detection-Zähler: Zählt wie oft hintereinander kein Mark gefunden wurde trotz Target
        self.no_yolo_detection_count = 0  # Zähler für fehlende YOLO-Detection
        
        # State-Machine für nicht-blockierende Target-Suche
        self.search_state = "idle"  # "idle", "waiting_after_tab", "check_rotation", "rotating", "waiting_after_rotation"
        self.search_state_time = 0  # Zeitpunkt des letzten State-Wechsels
        self.rotation_step = 0  # Aktueller Schritt der Drehung (0 = nicht aktiv)
        self.rotation_total_steps = 0  # Gesamtzahl der Schritte für aktuelle Drehung
        self.rotation_virtual_target_x = 0  # Ziel-X für aktuelle Drehung
        self.rotation_virtual_target_y = 0  # Ziel-Y für aktuelle Drehung
        
        # Combat-Rotationen (werden in update_center initialisiert)
        self.melee_rotation = None
        self.range_rotation = None
        self.max_no_yolo_detections = 5  # Nach 5 Mal ohne Detection → Drehung
        
        # Status der rechten Maustaste
        self.rmb_held = False
        
        # Status der W-Taste (Vorwärtsbewegung)
        self.w_key_held = False
        
        # Benutzer-Interventionserkennung
        self.last_mouse_pos = None
        self.last_bot_move_time = 0
        self.user_intervening = False
        self.intervention_start_time = 0  # Zeitpunkt, zu dem die Intervention begann
        self.intervention_timeout = 0.3  # Sekunden, nach denen wir annehmen, dass der Benutzer fertig ist
        
        # DirectInput Konfiguration für schnellere Reaktion
        pydirectinput.PAUSE = 0.001 
        pydirectinput.FAILSAFE = False
        
        # Pixel-Koordinaten für Positionsdaten (relativ zum WoW-Fenster)
        # WICHTIG: Diese müssen mit den Positionen in find_pixel_position.py übereinstimmen!
        self.pixel_x_coord = (60, 350)  # (x, y) für X-Koordinate (Lila)
        self.pixel_y_coord = (60, 460)  # (x, y) für Y-Koordinate (Rot)
        self.pixel_facing_coord = (60, 590)  # (x, y) für Blickrichtung (Beige)
        
        # Aktuelle Position und Blickrichtung
        self.current_x = 0.0
        self.current_y = 0.0
        self.current_facing = 0.0  # In Grad (0-360)
        
        # Waypoint-Liste
        self.waypoints = []  # Liste von (x, y) Tupeln (normalisiert 0.0-1.0)
        self.current_waypoint_index = 0
        self.waypoint_reached_threshold = 0.0  # Keine Toleranz - Waypoint muss exakt erreicht werden
        
        # Tastatur-Rotation für große Winkel (A/D Tasten)
        self.a_key_held = False  # A-Taste (gegen Uhrzeigersinn / links)
        self.d_key_held = False  # D-Taste (mit Uhrzeigersinn / rechts)

    def update_center(self, w, h):
        self.center_x = w // 2
        self.center_y = h // 2
        
        # Initialisiere Combat-Rotationen mit center_deadzone_x (nur einmal)
        if self.melee_rotation is None:
            self.melee_rotation = MeleeRotation(self.center_deadzone_x)
            self.range_rotation = RangeRotation(self.center_deadzone_x)
            print(f"[STATUS] Combat-Rotationen initialisiert (Deadzone: {self.center_deadzone_x}px)")
    
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
            # Keine Pause während Target-Suche für kontinuierliche Bewegung
            if not self.target_search_mode:
                time.sleep(random.uniform(0.05, 0.1))  # Pause nur außerhalb der Suche
        elif not hold and self.rmb_held:
            pydirectinput.mouseUp(button='right')
            self.rmb_held = False
            # Keine Pause während Target-Suche für kontinuierliche Bewegung
            if not self.target_search_mode:
                time.sleep(random.uniform(0.05, 0.1))  # Pause nur außerhalb der Suche
    
    def press_tab_key(self):
        """Drückt die Tab-Taste einmal für Target-Suche."""
        current_time = time.time()
        if current_time - self.last_tab_press_time < self.tab_press_delay:
            return  # Zu schnell, überspringe
        
        try:
            print("[TARGET-SUCHE] Drücke Tab-Taste...")
            pydirectinput.press('tab')
            self.last_tab_press_time = current_time
            # Keine Pause während Target-Suche für kontinuierliche Bewegung
            if not self.target_search_mode:
                time.sleep(random.uniform(0.1, 0.2))  # Pause nur außerhalb der Suche
        except Exception as e:
            print(f"[TARGET-SUCHE] Fehler beim Drücken der Tab-Taste: {e}")
    
    def press_f1_key(self):
        """Drückt die F1-Taste einmal, um das Mark auf das Target zu setzen."""
        try:
            current_time = time.time()
            # Prüfe ob F1 kürzlich gedrückt wurde (verhindert mehrfaches Drücken)
            if current_time - self.last_f1_press_time < 0.5:
                return  # Zu schnell, überspringe
            
            print("[TARGET-SUCHE] *** DRÜCKE F1-TASTE (Setze Mark auf Target) ***")
            pydirectinput.press('f1')
            self.last_f1_press_time = current_time
            
            # Längere Pause nach F1, damit Mark-Erkennung Zeit hat
            print("[TARGET-SUCHE] Warte auf Mark-Erkennung...")
            time.sleep(random.uniform(1.0, 1.5))  # 1-1.5 Sekunden Pause
        except Exception as e:
            print(f"[TARGET-SUCHE] Fehler beim Drücken der F1-Taste: {e}")
    
    def _execute_mouse_movement(self, move_x, move_y, use_smoothing=True):
        """Basis-Funktion für alle Mausbewegungen - vereinheitlicht die Logik.
        
        Args:
            move_x: Gewünschte horizontale Bewegung in Pixeln
            move_y: Gewünschte vertikale Bewegung in Pixeln
            use_smoothing: Wenn True, wende speed_factor und max_step an
        """
        # WICHTIG: Rechte Maustaste am ANFANG drücken
        # Merke, ob RMB bereits vorher gedrückt war
        rmb_was_held_before = self.rmb_held
        
        # Stelle sicher, dass RMB gedrückt ist
        if not self.rmb_held:
            self._hold_rmb(True)
            # Keine Pause - würde zu hackenden Bewegungen führen
        
        if use_smoothing:
            # Verwende erhöhte Geschwindigkeit während Target-Suche (50% schneller)
            current_speed_factor = self.target_search_speed_factor if self.target_search_mode else self.speed_factor
            move_x = int(move_x * current_speed_factor)
            max_step = 15  # Reduziert für smoothere Bewegung
            move_x = max(min(move_x, max_step), -max_step)
            
            # Wenn wir sehr nah sind, erzwinge kleine Schritte
            if abs(move_x) < 1 and move_x != 0:
                move_x = 1 if move_x > 0 else -1
            
            # Jitter für menschliche Wirkung (reduziert für smoothere Bewegung)
            jitter = random.randint(-1, 1)  # Reduziert von -2,2 auf -1,1
            move_x += jitter
        
        # Führe Bewegung aus
        pydirectinput.moveRel(move_x, move_y, relative=True)
        
        # Keine Pause - würde Frame-Rate reduzieren
        # Die Bewegung wird sofort ausgeführt, Sleep ist nicht nötig
        
        # WICHTIG: Rechte Maustaste am ENDE loslassen
        # Nur loslassen, wenn wir sie in dieser Funktion gedrückt haben
        # (nicht loslassen, wenn sie bereits vorher gedrückt war)
        if self.rmb_held and not rmb_was_held_before:
            self._hold_rmb(False)
            # Keine Pause - würde Frame-Rate reduzieren
    
    def _start_rotation(self):
        """Startet eine Rotation (initialisiert State-Variablen für Frame-basierte Drehung)."""
        try:
            print(f"[TARGET-SUCHE] Starte Drehung um ~30° (rechts)...")
            
            # Berechne virtuelle Target-Position außerhalb des Bildschirms für Drehung
            rotation_distance = int(self.center_x * random.uniform(0.10, 0.15))
            
            # Virtuelle Target-Positionen
            self.rotation_virtual_target_x = self.center_x + rotation_distance
            self.rotation_virtual_target_y = self.center_y + random.randint(-50, 50)
            
            # Anzahl der Schritte für nahtlose Bewegung (mehr Schritte = flüssiger)
            self.rotation_total_steps = random.randint(15, 20)  # Erhöht für nahtlosere Rotation
            self.rotation_step = 0
            
            # Drücke rechte Maustaste für Kameradrehung
            if not self.rmb_held:
                self._hold_rmb(True)
                
        except Exception as e:
            print(f"[TARGET-SUCHE] Fehler beim Starten der Drehung: {e}")
            import traceback
            traceback.print_exc()
            self.rotation_step = 0
            self.search_state = "idle"
    
    def _execute_rotation_step(self):
        """Führt einen Schritt der Rotation aus (wird pro Frame aufgerufen)."""
        try:
            if self.rotation_step >= self.rotation_total_steps:
                return
            
            # Berechne Fortschritt (0.0 bis 1.0)
            progress = self.rotation_step / self.rotation_total_steps
            
            # Lineare Interpolation für nahtlosere Bewegung (statt quadratischer Easing)
            # Dies macht die Bewegung gleichmäßiger und flüssiger
            current_target_x = self.center_x + (self.rotation_virtual_target_x - self.center_x) * progress
            current_target_y = self.center_y + (self.rotation_virtual_target_y - self.center_y) * progress
            
            # Berechne Offset
            offset_x = current_target_x - self.center_x
            
            # Führe Bewegung aus
            move_y = random.randint(-1, 1)  # Leichte vertikale Variation
            self._execute_mouse_movement(offset_x, move_y, use_smoothing=True)
            
            # Nächster Schritt
            self.rotation_step += 1
            
        except Exception as e:
            print(f"[TARGET-SUCHE] Fehler bei Rotations-Schritt: {e}")
            self.rotation_step = 0
            self.search_state = "idle"
    
    def rotate_90_degrees(self, scan_region=None):
        """Veraltete Funktion - wird durch _start_rotation() und _execute_rotation_step() ersetzt.
        Behalten für Kompatibilität, aber sollte nicht mehr verwendet werden.
        """
        # Starte Rotation (wird dann über mehrere Frames ausgeführt)
        self._start_rotation()
        self.search_state = "rotating"
    
    def light_camera_rotation(self):
        """Führt eine leichte Kameradrehung aus, um Target zu finden."""
        try:
            print("[TARGET-SUCHE] Leichte Kameradrehung...")
            
            # Halte rechte Maustaste
            if not self.rmb_held:
                self._hold_rmb(True)
            
            # Leichte Bewegung (kleiner als 90°) - nutze gemeinsame Basis-Funktion
            move_x = random.randint(-100, 100)  # Zufällige Richtung
            move_y = random.randint(-10, 10)
            
            # Nutze die gemeinsame Basis-Funktion für smoothere Bewegung
            self._execute_mouse_movement(move_x, move_y, use_smoothing=True)
            
            # Lasse rechte Maustaste los
            if self.rmb_held:
                self._hold_rmb(False)
            
            # Keine Pause während Target-Suche für kontinuierliche Bewegung
            if not self.target_search_mode:
                time.sleep(random.uniform(0.1, 0.2))  # Pause nur außerhalb der Suche
            
        except Exception as e:
            print(f"[TARGET-SUCHE] Fehler bei leichter Kameradrehung: {e}")
    
    def handle_target_search(self, range_state, has_detection):
        """Verwaltet die Target-Suche-Logik mit State-Machine (nicht-blockierend).
        
        Args:
            range_state: Aktueller Range-State (kann 'NO_TARGET' sein)
            has_detection: True wenn YOLO ein Target erkannt hat
        """
        # Prüfe ob Status von NO_TARGET zu einem anderen Status wechselt
        # Wenn ja, drücke F1-Taste (setzt Mark auf Target)
        if (self.last_range_state_for_f1 == 'NO_TARGET' and 
            range_state != 'NO_TARGET' and 
            range_state is not None):
            print(f"[TARGET-SUCHE] Status-Wechsel von NO_TARGET zu {range_state} - Drücke F1!")
            self.press_f1_key()
        
        # Aktualisiere letzten State für F1-Erkennung
        if range_state is not None:
            self.last_range_state_for_f1 = range_state
        
        # Prüfe ob kein Target (Schwarz im Range-Bereich)
        no_target = (range_state == 'NO_TARGET')
        current_time = time.time()
        
        if self.target_search_mode:
            # Target-Suche-Modus aktiv - State-Machine
            if no_target:
                # Kein Target gefunden - State-Machine für nicht-blockierende Suche
                
                # Prüfe ob F1 kürzlich gedrückt wurde - dann keine weitere Aktion
                if current_time - self.last_f1_press_time < self.f1_cooldown:
                    # F1 wurde kürzlich gedrückt - warte auf Mark-Erkennung
                    self.search_state = "idle"
                    return
                
                # State-Machine-Logik
                if self.search_state == "idle":
                    # Prüfe ob Tab gedrückt werden kann
                    if current_time - self.last_tab_press_time >= self.tab_press_delay:
                        self.press_tab_key()
                        self.search_state = "waiting_after_tab"
                        self.search_state_time = current_time
                
                elif self.search_state == "waiting_after_tab":
                    # Minimale Wartezeit nach Tab-Druck (nahtlose Bewegung)
                    if current_time - self.search_state_time >= 0.05:
                        # Prüfe ob F1 kürzlich gedrückt wurde
                        if current_time - self.last_f1_press_time < self.f1_cooldown:
                            self.search_state = "idle"
                            return
                        
                        # Prüfe ob Rotation nötig
                        if self.rotation_count < self.max_rotations:
                            # Starte Rotation direkt (keine zusätzliche Wartezeit)
                            self._start_rotation()
                            self.search_state = "rotating"
                        else:
                            # Maximale Drehungen erreicht, reset
                            print("[TARGET-SUCHE] Maximale Drehungen erreicht, reset...")
                            self.rotation_count = 0
                            self.search_state = "idle"
                
                elif self.search_state == "rotating":
                    # Führe einen Schritt der Rotation aus (wird über mehrere Frames verteilt)
                    if self.rotation_step >= self.rotation_total_steps:
                        # Rotation abgeschlossen
                        if self.rmb_held:
                            self._hold_rmb(False)
                        self.rotation_count += 1
                        self.rotation_step = 0
                        self.search_state = "waiting_after_rotation"
                        self.search_state_time = current_time
                        print("[TARGET-SUCHE] Drehung abgeschlossen, warte auf Mark-Erkennung...")
                    else:
                        # Führe einen Schritt aus
                        self._execute_rotation_step()
                
                elif self.search_state == "waiting_after_rotation":
                    # Minimale Wartezeit nach Drehung (nahtlose Bewegung)
                    wait_time = 0.05  # Sehr kurz für nahtlose Rotation
                    if current_time - self.search_state_time >= wait_time:
                        # Nach Drehung erneut Tab drücken
                        self.press_tab_key()
                        self.search_state = "waiting_after_tab"
                        self.search_state_time = current_time
            else:
                # Target gefunden! (kein Schwarz mehr)
                print("[TARGET-SUCHE] Target gefunden! Wechsle zu Tracking-Modus.")
                self.target_search_mode = False
                self.rotation_count = 0  # Reset für nächste Suche
                self.search_state = "idle"  # Reset State-Machine
                self.rotation_step = 0  # Reset Rotation
                
                # Prüfe ob Target direkt sichtbar (YOLO hat es erkannt)
                if not has_detection:
                    # Target nicht direkt sichtbar, leichte Kameradrehung
                    print("[TARGET-SUCHE] Target nicht direkt sichtbar, führe leichte Kameradrehung aus...")
                    self.light_camera_rotation()
        else:
            # Tracking-Modus aktiv
            # Prüfe zuerst ob Rotation läuft (auch im Tracking-Modus möglich)
            if self.search_state == "rotating":
                # Führe einen Schritt der Rotation aus
                if self.rotation_step >= self.rotation_total_steps:
                    # Rotation abgeschlossen
                    if self.rmb_held:
                        self._hold_rmb(False)
                    self.rotation_step = 0
                    self.search_state = "idle"
                    self.no_yolo_detection_count = 0  # Reset nach Drehung
                    print("[TARGET-SUCHE] Drehung abgeschlossen (Tracking-Modus)")
                else:
                    # Führe einen Schritt aus
                    self._execute_rotation_step()
                return  # Rotation hat Priorität
            
            if no_target:
                # Target verloren, zurück zur Suche
                print("[TARGET-SUCHE] Target verloren! Wechsle zurück zu Target-Suche.")
                self.target_search_mode = True
                self.rotation_count = 0
                self.no_yolo_detection_count = 0  # Reset Zähler
                self.search_state = "idle"  # Reset State-Machine
                self.rotation_step = 0  # Reset Rotation
                # Stoppe W-Taste falls gedrückt
                if self.w_key_held:
                    self._hold_w_key(False)
            else:
                # Target vorhanden (nicht NO_TARGET)
                # Prüfe ob YOLO das Mark findet
                if has_detection:
                    # YOLO hat Mark gefunden - Reset Zähler
                    if self.no_yolo_detection_count > 0:
                        print(f"[TARGET-SUCHE] YOLO hat Mark wieder gefunden (nach {self.no_yolo_detection_count} Frames ohne Detection)")
                    self.no_yolo_detection_count = 0
                else:
                    # Target vorhanden, aber YOLO findet kein Mark
                    self.no_yolo_detection_count += 1
                    
                    if self.no_yolo_detection_count >= self.max_no_yolo_detections:
                        # 5 Mal hintereinander kein Mark gefunden → Drehung
                        print(f"[TARGET-SUCHE] {self.max_no_yolo_detections} Mal hintereinander kein Mark von YOLO gefunden - Drehe um ~30°")
                        self._start_rotation()
                        self.search_state = "rotating"
                        self.no_yolo_detection_count = 0  # Reset nach Drehung
    
    def _focus_wow_window_simple(self):
        """Einfache Funktion zum Fokussieren des WoW-Fensters (für HumanInput-Klasse)."""
        if not WIN32_AVAILABLE:
            return False
        
        try:
            wow_titles = ['World of Warcraft', 'WoW', 'World of Warcraft Classic']
            for title in wow_titles:
                hwnd = win32gui.FindWindow(None, title)
                if hwnd:
                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetActiveWindow(hwnd)
                    return True
        except:
            pass
        return False
    
    def _hold_a_key(self, hold=True):
        """Verwaltet den A-Tasten-Status (Drehung gegen Uhrzeigersinn / links)."""
        # Stelle sicher, dass WoW-Fenster fokussiert ist vor Tastatureingabe
        # Nur beim ersten Drücken fokussieren (nicht jedes Frame)
        if hold and not self.a_key_held:
            self._focus_wow_window_simple()
            # Keine Pause - Fokus wird schnell genug gesetzt
            
            # WICHTIG: Rechte Maustaste LOSLASSEN während Tastatur-Rotation!
            # Wenn RMB gedrückt ist, ändert sich die Funktion von A/D (dreht Kamera statt Charakter)
            if self.rmb_held:
                self._hold_rmb(False)
        
        if hold and not self.a_key_held:
            pydirectinput.keyDown('a')
            self.a_key_held = True
        elif not hold and self.a_key_held:
            pydirectinput.keyUp('a')
            self.a_key_held = False
    
    def _hold_d_key(self, hold=True):
        """Verwaltet den D-Tasten-Status (Drehung mit Uhrzeigersinn / rechts)."""
        # Stelle sicher, dass WoW-Fenster fokussiert ist vor Tastatureingabe
        # Nur beim ersten Drücken fokussieren (nicht jedes Frame)
        if hold and not self.d_key_held:
            self._focus_wow_window_simple()
            # Keine Pause - Fokus wird schnell genug gesetzt
            
            # WICHTIG: Rechte Maustaste LOSLASSEN während Tastatur-Rotation!
            # Wenn RMB gedrückt ist, ändert sich die Funktion von A/D (dreht Kamera statt Charakter)
            if self.rmb_held:
                self._hold_rmb(False)
        
        if hold and not self.d_key_held:
            pydirectinput.keyDown('d')
            self.d_key_held = True
        elif not hold and self.d_key_held:
            pydirectinput.keyUp('d')
            self.d_key_held = False
    
    def _hold_w_key(self, hold=True):
        """Verwaltet den W-Taste-Status (Vorwärtsbewegung)."""
        # Stelle sicher, dass WoW-Fenster fokussiert ist vor Tastatureingabe
        # Nur beim ersten Drücken fokussieren (nicht jedes Frame)
        if hold and not self.w_key_held:
            self._focus_wow_window_simple()
            # Keine Pause - Fokus wird schnell genug gesetzt
        
        if hold and not self.w_key_held:
            try:
                pydirectinput.keyDown('w')
                self.w_key_held = True
                print(f"[W-TASTE] W-Taste GEDRÜCKT (w_key_held={self.w_key_held})")
                # Keine Pause - Taste wird sofort registriert, Sleep würde Frame-Rate reduzieren
            except Exception as e:
                print(f"[_hold_w_key] FEHLER beim Drücken der W-Taste: {e}")
        elif not hold and self.w_key_held:
            try:
                pydirectinput.keyUp('w')
                self.w_key_held = False
                print(f"[W-TASTE] W-Taste LOSGELASSEN (w_key_held={self.w_key_held})")
                # Keine Pause - Taste wird sofort registriert, Sleep würde Frame-Rate reduzieren
            except Exception as e:
                print(f"[_hold_w_key] FEHLER beim Loslassen der W-Taste: {e}")
        # Wenn hold=True und w_key_held=True, wird nichts gemacht (Taste bleibt gedrückt)
    
    def get_range_state_from_color(self, pixel_color):
        """Interpretiert die Farbe eines Pixels und gibt den Range-Zustand zurück.
        
        Args:
            pixel_color: BGR-Farbe als (B, G, R) Tupel oder numpy array
            
        Returns:
            'OUT_OF_RANGE', 'MELEE_RANGE', 'IN_RANGE', 'NO_TARGET', oder 'UNKNOWN'
        """
        if pixel_color is None or len(pixel_color) < 3:
            return 'UNKNOWN'
        
        # BGR Format (OpenCV Standard)
        b, g, r = int(pixel_color[0]), int(pixel_color[1]), int(pixel_color[2])
        
        # Toleranz-Schwellenwerte für Farberkennung (wegen Kompressionsartefakten)
        # Lockere Schwellenwerte für bessere Erkennung
        
        # Rot: OUT_OF_RANGE (R dominant, G und B niedrig)
        if r > 150 and g < 100 and b < 100:
            return 'OUT_OF_RANGE'
        
        # Grün: MELEE_RANGE (G dominant, R und B niedrig)
        # Erweiterte Bedingung: G muss deutlich höher sein als R und B
        if g > 150 and r < 100 and b < 100:
            return 'MELEE_RANGE'
        # Alternative: Wenn G deutlich höher ist als R und B (auch wenn G < 150)
        if g > 120 and g > r + 30 and g > b + 30 and r < 120 and b < 120:
            return 'MELEE_RANGE'
        
        # Blau: IN_RANGE (B dominant, R und G niedrig)
        if b > 150 and r < 100 and g < 100:
            return 'IN_RANGE'
        
        # Schwarz: Alle Werte niedrig (kein Target)
        if r < 50 and g < 50 and b < 50:
            return 'NO_TARGET'  # Schwarz = kein Target
        
        # Schwarz oder andere Farben
        return 'UNKNOWN'
    
    def _get_direction_name(self, angle_deg):
        """Konvertiert einen Winkel in Grad zu einer Himmelsrichtung.
        
        Args:
            angle_deg: Winkel in Grad (0-360)
            
        Returns:
            Himmelsrichtung als String (Norden, Osten, Süden, Westen, etc.)
        """
        # Normalisiere auf 0-360
        angle_deg = angle_deg % 360.0
        
        # Bestimme Himmelsrichtung
        if angle_deg >= 337.5 or angle_deg < 22.5:
            return "Norden"
        elif 22.5 <= angle_deg < 67.5:
            return "Nord-Osten"
        elif 67.5 <= angle_deg < 112.5:
            return "Osten"
        elif 112.5 <= angle_deg < 157.5:
            return "Süd-Osten"
        elif 157.5 <= angle_deg < 202.5:
            return "Süden"
        elif 202.5 <= angle_deg < 247.5:
            return "Süd-Westen"
        elif 247.5 <= angle_deg < 292.5:
            return "Westen"
        elif 292.5 <= angle_deg < 337.5:
            return "Nord-Westen"
        else:
            return "Unbekannt"
    
    def read_range_from_frame(self, frame):
        """Liest die Range-Information aus dem Frame an der WeakAura-Position.
        
        Args:
            frame: OpenCV Frame (BGR Format) - sollte der aufgenommene Frame sein (scan_region)
            
        Returns:
            Range-Zustand: 'OUT_OF_RANGE', 'MELEE_RANGE', 'IN_RANGE', oder 'UNKNOWN'
        """
        if frame is None:
            return 'UNKNOWN'
        
        try:
            h, w = frame.shape[:2]
            
            # Berechne WeakAura-Position relativ zur Frame-Mitte
            frame_center_x = w // 2
            frame_center_y = h // 2
            x = int(frame_center_x + self.weakuara_offset_x)
            y = int(frame_center_y + self.weakuara_offset_y)
            
            # Prüfe ob Position innerhalb des Frames liegt
            if x < 0 or x >= w or y < 0 or y >= h:
                if not hasattr(self, '_range_warning_shown'):
                    print(f"[RANGE] WeakAura-Position ({x}, {y}) außerhalb des Frames ({w}x{h})")
                    print(f"[RANGE] Frame-Mitte wäre ({w//2}, {h//2}), Offset ist ({self.weakuara_offset_x}, {self.weakuara_offset_y})")
                    self._range_warning_shown = True
                return 'UNKNOWN'
            
            # Lese Pixel-Farbe an dieser Position
            pixel_color = frame[y, x]  # OpenCV verwendet (y, x) nicht (x, y)!
            
            # Interpretiere Farbe
            range_state = self.get_range_state_from_color(pixel_color)
            
            # Keine Debug-Ausgabe mehr - nur bei State-Änderung in handle_range_state_change
            return range_state
        except Exception as e:
            print(f"[RANGE] Fehler beim Lesen der Range: {e}")
            import traceback
            traceback.print_exc()
            return 'UNKNOWN'
    
    def decode_24bit_pixel(self, pixel_bgr, normalize=True):
        """Dekodiert einen 24-Bit-Pixel-Wert aus BGR-Farbwerten.
        
        Args:
            pixel_bgr: BGR-Farbe als (B, G, R) Tupel oder numpy array
            normalize: Wenn True, normalisiert auf 0.0-1.0, sonst gibt Ro-Wert zurück
            
        Returns:
            Normalisierter Wert zwischen 0.0 und 1.0, oder Ro-Wert (0-16777215)
        
        WICHTIG: WeakAura-Code zeigt:
        - r = math.floor(raw / 65536) / 255  (obere 16 Bits, aber als 0-1 normalisiert)
        - g = math.floor(bit.band(raw, 0xFF00) / 256) / 255  (Bits 8-15)
        - b = bit.band(raw, 0xFF) / 255  (Bits 0-7)
        
        Das bedeutet: R enthält die oberen 16 Bits, nicht 8 Bits!
        """
        if pixel_bgr is None or len(pixel_bgr) < 3:
            return None
        
        # BGR Format (OpenCV Standard)
        b, g, r = int(pixel_bgr[0]), int(pixel_bgr[1]), int(pixel_bgr[2])
        
        # WeakAura-Code analysieren:
        # raw = math.floor((facing / (math.pi * 2)) * 16777215)  [24-Bit-Wert]
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
    
    def decode_facing_pixel(self, pixel_bgr):
        """Dekodiert einen Blickrichtung-Pixel und konvertiert zu Grad.
        
        Args:
            pixel_bgr: BGR-Farbe als (B, G, R) Tupel oder numpy array
            
        Returns:
            Blickrichtung in Grad (0.0 bis 360.0)
        """
        normalized = self.decode_24bit_pixel(pixel_bgr)
        if normalized is None:
            return None
        
        # WeakAura: GetPlayerFacing() gibt 0 bis 2π zurück
        # Normalisiert auf 0.0-1.0, dann * 360° für Grad
        facing_degrees = normalized * 360.0
        
        # FEHLERHAFTE KORREKTUR ENTFERNT:
        # Die vorherige Logik hat Winkel zwischen 45-135 und 225-315 um 180 Grad gedreht.
        # Das hat dazu geführt, dass der Bot seine eigene Position falsch interpretiert
        # und ständig hin und her springt (Oszillation).
        
        # Wir vertrauen dem rohen Wert der WeakAura.
        # Sollte der Bot später verkehrt herum laufen, muss die Logik bei 
        # "angle_diff" oder die Tastenbelegung (A/D) angepasst werden, 
        # aber NICHT die Sensor-Daten manipuliert werden.
        
        return facing_degrees
    
    def read_position_from_frame(self, frame):
        """Liest die aktuelle Position (X, Y, Facing) aus dem Frame.
        
        Args:
            frame: OpenCV Frame (BGR Format)
            
        Returns:
            (x, y, facing) Tupel oder None bei Fehler
        """
        if frame is None:
            return None
        
        try:
            h, w = frame.shape[:2]
            
            # Prüfe ob Positionen innerhalb des Frames liegen
            if (self.pixel_x_coord[0] < 0 or self.pixel_x_coord[0] >= w or 
                self.pixel_x_coord[1] < 0 or self.pixel_x_coord[1] >= h):
                return None
            if (self.pixel_y_coord[0] < 0 or self.pixel_y_coord[0] >= w or 
                self.pixel_y_coord[1] < 0 or self.pixel_y_coord[1] >= h):
                return None
            if (self.pixel_facing_coord[0] < 0 or self.pixel_facing_coord[0] >= w or 
                self.pixel_facing_coord[1] < 0 or self.pixel_facing_coord[1] >= h):
                return None
            
            # Lese Pixel an den konfigurierten Positionen
            # Beachte: OpenCV verwendet (y, x) nicht (x, y)!
            x_pixel = frame[self.pixel_x_coord[1], self.pixel_x_coord[0]]
            y_pixel = frame[self.pixel_y_coord[1], self.pixel_y_coord[0]]
            facing_pixel = frame[self.pixel_facing_coord[1], self.pixel_facing_coord[0]]
            
            # Dekodiere Werte
            # Für Koordinaten: normalisieren, da WeakAuras normalisierte Werte (0.0-1.0) ausgeben
            # Für Facing: normalisieren, da es ein Winkel ist
            x_value_raw = self.decode_24bit_pixel(x_pixel, normalize=True)
            y_value_raw = self.decode_24bit_pixel(y_pixel, normalize=True)
            
            # Für Facing: Dekodiere zuerst den normalisierten Wert (vor Korrektur)
            facing_normalized = self.decode_24bit_pixel(facing_pixel, normalize=True)
            facing_raw_degrees = facing_normalized * 360.0 if facing_normalized is not None else None
            facing_value = self.decode_facing_pixel(facing_pixel)
            
            if x_value_raw is not None and y_value_raw is not None and facing_value is not None:
                # Debug-Ausgabe: Zeige rohe WeakAura-Werte (alle 30 Frames)
                if not hasattr(self, '_weakuara_debug_counter'):
                    self._weakuara_debug_counter = 0
                self._weakuara_debug_counter += 1
                if self._weakuara_debug_counter % 30 == 0:
                    b_facing, g_facing, r_facing = int(facing_pixel[0]), int(facing_pixel[1]), int(facing_pixel[2])
                    print(f"[WEAKAURA-RAW] Facing-Pixel BGR=({b_facing}, {g_facing}, {r_facing}), "
                          f"Normalisiert={facing_normalized:.6f}, "
                          f"Roher Winkel={facing_raw_degrees:.1f}°, "
                          f"Korrigierter Winkel={facing_value:.1f}°")
                
                # Dekodierte Werte direkt zuweisen (keine Vertauschung mehr)
                # Die WeakAura für X-Koordinate gibt X aus, Y-Koordinate gibt Y aus
                self.current_x = x_value_raw
                self.current_y = y_value_raw
                self.current_facing = facing_value
                return (self.current_x, self.current_y, facing_value)
            
            return None
        except Exception as e:
            print(f"[POSITION] Fehler beim Lesen der Position: {e}")
            return None
    
    def drive_to_waypoint(self, target_x, target_y):
        """Navigiert den Charakter zu einem Ziel-Waypoint.
        
        Args:
            target_x: Ziel-X-Koordinate (normalisiert 0.0-1.0)
            target_y: Ziel-Y-Koordinate (normalisiert 0.0-1.0)
            
        Returns:
            True wenn Waypoint erreicht, False sonst
            
        BEKANNTES PROBLEM:
        ------------------
        Die Charakter-Ausrichtung funktioniert korrekt (Drehung zum Waypoint),
        aber die Bewegung zum Ziel funktioniert nicht. Die W-Taste wird gedrückt,
        aber der Charakter bewegt sich nicht ausreichend oder in die richtige
        Richtung zum Waypoint.
        """
        # Prüfe zuerst ob Benutzer eingreift - dann pausiere Navigation
        if self.check_user_intervention():
            # Benutzer greift ein - stoppe Bewegung
            if self.w_key_held:
                self._hold_w_key(False)
            if self.rmb_held:
                self._hold_rmb(False)
            return False
        
        # Berechne Distanz zum Ziel (beide Werte sind normalisiert 0.0-1.0)
        dx = target_x - self.current_x
        dy = target_y - self.current_y
        distance = math.sqrt(dx * dx + dy * dy)
        
        # Prüfe ob Waypoint erreicht
        # Waypoint gilt als erreicht, wenn X und Y jeweils innerhalb von ±1 (WoW-Koordinaten) sind
        # Da Koordinaten normalisiert sind (0.0-1.0), entspricht ±1 in WoW-Koordinaten ±0.01 in normalisierten Koordinaten
        waypoint_threshold = 0.01  # ±1 in WoW-Koordinaten = ±0.01 in normalisierten Koordinaten
        
        if abs(dx) <= waypoint_threshold and abs(dy) <= waypoint_threshold:
            # Waypoint erreicht! Stoppe Bewegung
            if self.w_key_held:
                self._hold_w_key(False)
            if self.rmb_held:
                self._hold_rmb(False)
            if self.a_key_held:
                self._hold_a_key(False)
            if self.d_key_held:
                self._hold_d_key(False)
            print(f"[NAVIGATION] Waypoint erreicht! Pos: ({int(self.current_x * 100)}, {int(self.current_y * 100)}), Ziel: ({int(target_x * 100)}, {int(target_y * 100)})")
            return True
        
        # Berechne Zielwinkel (Target Angle) in Radian
        # KORREKTUR: WoW nutzt ein CCW System (0=N, 90=W).
        # Wir müssen dx und dy negieren, um die korrekten Komponenten für atan2 zu haben.
        # -dx = West-Komponente (Positiv wenn wir nach Westen müssen)
        # -dy = Nord-Komponente (Positiv wenn wir nach Norden müssen)
        # atan2(-dx, -dy) gibt: Norden=0° (dx=0, dy<0 → atan2(0, 1) = 0°),
        #                         Westen=90° (dx<0, dy=0 → atan2(1, 0) = 90°),
        #                         Süden=180° (dx=0, dy>0 → atan2(0, -1) = 180°),
        #                         Osten=270° (dx>0, dy=0 → atan2(-1, 0) = -90° → 270°)
        target_angle_rad = math.atan2(-dx, -dy)  # -dx und -dy für korrekte WoW-Koordinaten
        target_angle_deg = math.degrees(target_angle_rad)
        
        # Normalisiere auf 0-360 Grad
        if target_angle_deg < 0:
            target_angle_deg += 360.0
        
        # ---------------------------------------------------------
        # STABILISIERTE WINKEL-BERECHNUNG (ANTI-PENDEL)
        # ---------------------------------------------------------
        
        # 1. Berechne einfache Differenz
        angle_diff_raw = self.current_facing - target_angle_deg
        
        # 2. Standard-Normalisierung auf [-180, +180]
        # (Negativ = Links drehen, Positiv = Rechts drehen)
        angle_diff = (angle_diff_raw + 180.0) % 360.0 - 180.0
        
        # 3. ANTI-PENDEL-KORREKTUR (WICHTIG!)
        # Wenn das Ziel im Rücken ist (> 150° Differenz), springt der "kürzeste Weg"
        # ständig zwischen Links und Rechts hin und her.
        # Lösung: Wir erzwingen bei großen Winkeln IMMER eine Rechtsdrehung (positiv).
        if abs(angle_diff) > 150.0:
            angle_diff = abs(angle_diff)  # Erzwinge positiv -> Drehung nach Rechts (D-Taste)
        
        # Debug-Ausgabe (jedes Frame)
        print(f"[NAVIGATION] Pos: ({self.current_x * 100:.2f}, {self.current_y * 100:.2f}), "
              f"Ziel: ({target_x * 100:.2f}, {target_y * 100:.2f}), "
              f"Distanz: {distance * 100:.2f}, "
              f"Facing: {self.current_facing:.1f}°, "
              f"Zielwinkel: {target_angle_deg:.1f}°, "
              f"Roh-Differenz: {angle_diff_raw:.1f}°, "
              f"Normalisierte Differenz: {angle_diff:.1f}°")
        
        # ============================================================
        # ROTATIONS-LOGIK
        # ============================================================
        # angle_diff negativ → Ziel ist links → A-Taste (links drehen)
        # angle_diff positiv → Ziel ist rechts → D-Taste (rechts drehen)
        # abs(angle_diff) <= 10° → Dead Zone erreicht, laufen
        # ============================================================
        
        abs_angle_diff = abs(angle_diff)
        
        if abs_angle_diff > 45.0:  # Phase 1: Grobe Ausrichtung mit Tastatur
            # Stoppe alle anderen Tasten
            if self.w_key_held:
                self._hold_w_key(False)
            if self.rmb_held:
                self._hold_rmb(False)
            
            if angle_diff < 0:
                # Negativ → Ziel ist links → A-Taste (links drehen)
                if self.d_key_held:
                    self._hold_d_key(False)
                if not self.a_key_held:
                    self._hold_a_key(True)
            else:
                # Positiv → Ziel ist rechts → D-Taste (rechts drehen)
                if self.a_key_held:
                    self._hold_a_key(False)
                if not self.d_key_held:
                    self._hold_d_key(True)
            
            return False
        
        elif abs_angle_diff > 10.0:  # Phase 2: Feine Ausrichtung mit Maus (10-45°)
            # Stoppe Tastatur-Rotation
            if self.a_key_held:
                self._hold_a_key(False)
            if self.d_key_held:
                self._hold_d_key(False)
            if self.w_key_held:
                self._hold_w_key(False)
            
            # WICHTIG: Rechte Maustaste am Anfang drücken und GEDRÜCKT HALTEN
            # Die RMB muss während der gesamten Rotation gedrückt bleiben
            if not self.rmb_held:
                self._hold_rmb(True)
                # Kurze Pause, damit RMB wirklich registriert wird
                time.sleep(0.01)
            
            # Berechne Mausbewegung basierend auf Richtung
            if angle_diff < 0:
                # Negativ → Ziel ist links → Maus nach links (negativ) für Linksdrehung
                move_x = -int(abs_angle_diff * 0.75)
            else:
                # Positiv → Ziel ist rechts → Maus nach rechts (positiv) für Rechtsdrehung
                move_x = int(abs_angle_diff * 0.75)
            
            # Begrenze auf kleine, sanfte Bewegungen
            move_x = max(min(move_x, 12), -12)
            
            # Kleine vertikale Variation für Realismus
            move_y = random.randint(-1, 1)
            
            # WICHTIG: Stelle sicher, dass RMB noch gedrückt ist vor der Bewegung
            # (könnte von anderen Modulen losgelassen worden sein)
            if not self.rmb_held:
                self._hold_rmb(True)
                time.sleep(0.01)
            
            # Führe Mausbewegung aus (NUR wenn RMB gedrückt ist)
            if self.rmb_held:
                pydirectinput.moveRel(move_x, move_y, relative=True)
            else:
                # Fallback: Drücke RMB erneut und bewege dann
                self._hold_rmb(True)
                time.sleep(0.01)
                pydirectinput.moveRel(move_x, move_y, relative=True)
            
            # WICHTIG: Rechte Maustaste NICHT loslassen - bleibt gedrückt für kontinuierliche Rotation
            # (wird erst losgelassen wenn abs_angle_diff <= 10° in der else-Klausel)
            
            return False
        
        else:
            # Dead Zone erreicht (abs(angle_diff) <= 10°) - laufe nach vorne
            # Stoppe alle Rotationen
            if self.a_key_held:
                self._hold_a_key(False)
            if self.d_key_held:
                self._hold_d_key(False)
            if self.rmb_held:
                self._hold_rmb(False)
            
            # W-Taste einmal drücken und dann gedrückt lassen
            if not self.w_key_held:
                print(f"[DRIVE_TO_WAYPOINT] W-Taste wird GEDRÜCKT (angle_diff={angle_diff:.1f}°)")
                self._hold_w_key(True)
            
            return False  # Noch nicht am Ziel
    
    def handle_range_state_change(self, new_range_state):
        """Verwaltet die W-Taste basierend auf Range-State.
        
        Args:
            new_range_state: Neuer Range-Zustand
        """
        # Prüfe ob State sich geändert hat
        state_changed = new_range_state != self.current_range_state
        
        if state_changed:
            self.previous_range_state = self.current_range_state
            self.current_range_state = new_range_state
            print(f"[RANGE] State-Änderung: {self.previous_range_state} -> {self.current_range_state}")
        
        # Entscheide basierend auf aktuellem State (auch wenn er gleich bleibt)
        if new_range_state == 'OUT_OF_RANGE':
            # Ziel ist zu weit weg - laufe nach vorne (W-Taste gedrückt halten)
            if not self.w_key_held:
                if state_changed:
                    print("[RANGE] OUT_OF_RANGE - Starte Vorwärtsbewegung (W-Taste)")
                else:
                    print("[RANGE] OUT_OF_RANGE - Halte Vorwärtsbewegung (W-Taste)")
                self._hold_w_key(True)
            # Wenn W-Taste bereits gedrückt ist, nichts tun (bleibt gedrückt)
        elif new_range_state in ('MELEE_RANGE', 'IN_RANGE'):
            # Ziel ist in Reichweite - stoppe Bewegung
            if self.w_key_held:
                print(f"[RANGE] {new_range_state} - Stoppe Vorwärtsbewegung (W-Taste loslassen)")
                self._hold_w_key(False)
        elif new_range_state in ('UNKNOWN', 'NO_TARGET'):
            # Unbekannter Zustand oder kein Target - behalte aktuellen Status bei (keine Änderung)
            # NO_TARGET wird in handle_target_search behandelt, hier nur Status beibehalten
            if state_changed:
                print(f"[RANGE] {new_range_state} - Behalte aktuellen Status (W-Taste: {self.w_key_held})")
    
    def check_target_in_center(self, target_x, target_y):
        """Prüft, ob das Ziel horizontal nahe genug an der Bildschirmmitte ist.
        
        WICHTIG: Nur X-Achse wird geprüft! Y-Achse ist nur für Kamera-Einstellung.
        
        Returns:
            True wenn Ziel horizontal innerhalb der Zentrums-Deadzone ist, False sonst
        """
        if target_x is None:
            print(f"[DEBUG CENTER] Kein Ziel (target_x={target_x})")
            return False
        
        # Berechne horizontalen Abstand zur Mitte (NUR X-Achse!)
        offset_x = abs(target_x - self.center_x)
        
        # Prüfe ob innerhalb der horizontalen Deadzone
        in_center = offset_x <= self.center_deadzone_x
        
        # Debug-Ausgabe (immer, damit wir sehen was passiert)
        if not hasattr(self, '_debug_counter'):
            self._debug_counter = 0
        self._debug_counter += 1
        
        # Jeden Frame ausgeben (kann später reduziert werden)
        print(f"[DEBUG CENTER] Frame {self._debug_counter}: Ziel X={target_x:.1f}, Mitte X={self.center_x}")
        print(f"[DEBUG CENTER] Horizontaler Offset: {offset_x:.1f}/{self.center_deadzone_x}, In Center: {in_center}")
        
        return in_center

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
        
        # WICHTIG: Wenn wir zu einem Waypoint navigieren, NICHT die Maus bewegen!
        # Die Waypoint-Navigation verwendet ihre eigene Maus-Steuerung
        # Diese Funktion ist nur für Combat/Target-Tracking gedacht
        # Prüfe ob wir gerade zu einem Waypoint navigieren (indirekt über w_key_held während Navigation)
        # Aber besser: Diese Funktion sollte nur aufgerufen werden, wenn nicht navigating_to_waypoint
        # Das wird bereits in der Main-Loop geprüft, aber als zusätzliche Sicherheit:
        # Wenn RMB für Waypoint-Navigation gedrückt ist, nicht stören
        if self.rmb_held and not self.target_search_mode:
            # RMB ist gedrückt, aber wir sind nicht im Target-Search-Modus
            # Das könnte Waypoint-Navigation sein - nicht stören
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
        # Verwende erhöhte Geschwindigkeit während Target-Suche (50% schneller)
        current_speed_factor = self.target_search_speed_factor if self.target_search_mode else self.speed_factor
        move_x = int(offset_x * current_speed_factor)
        
        # Begrenzung (Clamping), damit sich der Char nicht im Kreis dreht wie verrückt
        max_step = 15  # Maximale Pixel pro "Tick" - reduziert für smoothere Bewegung (von 20)
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
        # Keine Pause - würde zu hackenden Bewegungen führen
        pydirectinput.moveRel(move_x, move_y, relative=True)
        
        # Keine Pause - würde zu hackenden Bewegungen führen
        
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

        # Keine Micro-Sleeps - würden zu hackenden Bewegungen führen

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
        
        # Lade Waypoints aus Datei
        self.load_waypoints_from_file("waypoints.txt")
    
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
    
    def _bring_window_to_front(self, window_name):
        """Bringt ein OpenCV-Fenster in den Vordergrund.
        
        WICHTIG: Diese Funktion sollte nur selten aufgerufen werden, da sie den Fokus
        vom WoW-Fenster abzieht und Tastatureingaben verhindert!
        
        Args:
            window_name: Name des OpenCV-Fensters
        """
        if not WIN32_AVAILABLE:
            return
        
        try:
            # Finde das Fenster-Handle
            hwnd = win32gui.FindWindow(None, window_name)
            if hwnd:
                # Stelle sicher, dass das Fenster nicht minimiert ist
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    # Nur wenn minimiert: Fenster wiederherstellen, aber NICHT in den Vordergrund bringen
                    # (um WoW-Fokus zu behalten)
                    # ENTFERNT: SetForegroundWindow und BringWindowToTop ziehen Fokus vom WoW-Fenster ab
                    # win32gui.SetForegroundWindow(hwnd)
                    # win32gui.BringWindowToTop(hwnd)
        except Exception as e:
            # Fehler beim Bringen des Fensters in den Vordergrund - nicht kritisch
            pass
    
    def _focus_wow_window(self):
        """Fokussiert das WoW-Fenster, damit Tastatureingaben ankommen."""
        if not WIN32_AVAILABLE:
            return False
        
        try:
            # Suche nach WoW-Fenster mit verschiedenen möglichen Titeln
            wow_titles = ['World of Warcraft', 'WoW', 'World of Warcraft Classic']
            
            for title in wow_titles:
                hwnd = win32gui.FindWindow(None, title)
                if hwnd:
                    # Stelle sicher, dass das Fenster nicht minimiert ist
                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    
                    # Bringt das Fenster in den Vordergrund
                    win32gui.SetForegroundWindow(hwnd)
                    win32gui.BringWindowToTop(hwnd)
                    
                    # Zusätzlich: Setze den Fokus explizit
                    win32gui.SetActiveWindow(hwnd)
                    
                    return True
            
            return False
        except Exception as e:
            # Fehler beim Fokussieren - nicht kritisch, aber loggen
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

    def draw_weakuara_position(self, frame, range_state=None, pixel_color=None):
        """Zeichnet die WeakAura-Position im Frame mit einem Kreis und Informationen.
        
        Args:
            frame: OpenCV Frame (BGR Format)
            range_state: Optional, der erkannte Range-State
            pixel_color: Optional, die erkannte Pixel-Farbe (BGR)
        """
        if frame is None:
            return frame
        
        try:
            h, w = frame.shape[:2]
            # Berechne WeakAura-Position relativ zur Frame-Mitte
            frame_center_x = w // 2
            frame_center_y = h // 2
            x = int(frame_center_x + self.human_input.weakuara_offset_x)
            y = int(frame_center_y + self.human_input.weakuara_offset_y)
            
            # Prüfe ob Position innerhalb des Frames liegt
            if x < 0 or x >= w or y < 0 or y >= h:
                return frame  # Position außerhalb, nichts zeichnen
            
            # Farbe basierend auf Range-State
            if range_state == 'OUT_OF_RANGE':
                circle_color = (0, 0, 255)  # Rot (BGR)
                state_text = "OUT_OF_RANGE"
            elif range_state == 'MELEE_RANGE':
                circle_color = (0, 255, 0)  # Grün (BGR)
                state_text = "MELEE_RANGE"
            elif range_state == 'IN_RANGE':
                circle_color = (255, 0, 0)  # Blau (BGR)
                state_text = "IN_RANGE"
            else:
                circle_color = (128, 128, 128)  # Grau (BGR)
                state_text = "UNKNOWN"
            
            # Zeichne einen großen Kreis um die Position
            cv2.circle(frame, (x, y), 15, circle_color, 3)  # Äußerer Kreis
            cv2.circle(frame, (x, y), 5, circle_color, -1)  # Innerer gefüllter Kreis
            
            # Zeichne ein kleines Kreuz in der Mitte für präzise Position
            cv2.line(frame, (x - 10, y), (x + 10, y), circle_color, 2)
            cv2.line(frame, (x, y - 10), (x, y + 10), circle_color, 2)
            
            # Text mit Range-State und Position
            info_text = f"Range: {state_text}"
            if pixel_color is not None:
                b, g, r = int(pixel_color[0]), int(pixel_color[1]), int(pixel_color[2])
                info_text += f" | BGR:({b},{g},{r})"
            info_text += f" | Pos:({x},{y})"
            
            # Hintergrund für Text
            text_size, _ = cv2.getTextSize(info_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            text_x = x - text_size[0] // 2
            text_y = y - 30  # Über dem Kreis
            
            # Stelle sicher, dass Text nicht außerhalb des Frames ist
            if text_y < 20:
                text_y = y + 30  # Unter dem Kreis
            
            # Schwarzer Hintergrund für bessere Lesbarkeit
            cv2.rectangle(frame, 
                        (text_x - 5, text_y - text_size[1] - 5), 
                        (text_x + text_size[0] + 5, text_y + 5), 
                        (0, 0, 0), -1)
            
            # Text zeichnen
            cv2.putText(frame, info_text, (text_x, text_y), 
                      cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
        except Exception as e:
            print(f"[RANGE] Fehler beim Zeichnen der WeakAura-Position: {e}")
        
        return frame

    def draw_position_pixels(self, frame):
        """Zeichnet kleine Kreise an den Pixel-Positionen für X, Y, Facing.
        
        Args:
            frame: OpenCV Frame (BGR Format)
        """
        if frame is None:
            return frame
        
        try:
            h, w = frame.shape[:2]
            
            # Zeichne Kreis für X-Koordinate (Lila)
            x_pos = self.human_input.pixel_x_coord
            if 0 <= x_pos[0] < w and 0 <= x_pos[1] < h:
                cv2.circle(frame, (x_pos[0], x_pos[1]), 5, (255, 0, 255), 2)  # Lila (BGR)
                cv2.putText(frame, "X", (x_pos[0] + 8, x_pos[1] + 5), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1)
            
            # Zeichne Kreis für Y-Koordinate (Rot)
            y_pos = self.human_input.pixel_y_coord
            if 0 <= y_pos[0] < w and 0 <= y_pos[1] < h:
                cv2.circle(frame, (y_pos[0], y_pos[1]), 5, (0, 0, 255), 2)  # Rot (BGR)
                cv2.putText(frame, "Y", (y_pos[0] + 8, y_pos[1] + 5), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
            
            # Zeichne Kreis für Facing (Beige/Gelb)
            facing_pos = self.human_input.pixel_facing_coord
            if 0 <= facing_pos[0] < w and 0 <= facing_pos[1] < h:
                cv2.circle(frame, (facing_pos[0], facing_pos[1]), 5, (0, 200, 255), 2)  # Beige/Gelb (BGR)
                cv2.putText(frame, "F", (facing_pos[0] + 8, facing_pos[1] + 5), 
                          cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 255), 1)
            
        except Exception as e:
            print(f"[POSITION] Fehler beim Zeichnen der Pixel-Positionen: {e}")
        
        return frame

    def load_waypoints_from_file(self, filepath="waypoints.txt"):
        """Lädt Waypoints aus einer Textdatei.
        
        Format: Eine Zeile pro Waypoint, Format: "x,y" oder "x, y"
        Leere Zeilen und Zeilen mit # werden ignoriert.
        
        Args:
            filepath: Pfad zur Waypoint-Datei
        """
        waypoints = []
        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filepath)
        
        try:
            if not os.path.exists(full_path):
                print(f"[WAYPOINTS] Datei nicht gefunden: {full_path}")
                print(f"[WAYPOINTS] Erstelle Standard-Waypoint-Datei mit Test-Koordinaten...")
                # Erstelle Standard-Datei mit Test-Koordinaten
                # Koordinaten müssen normalisiert sein (0.0-1.0)
                # Beispiel: 50,86 in WoW-Koordinaten = 0.50, 0.86 (angenommen max 100)
                with open(full_path, 'w') as f:
                    f.write("# Waypoint-Datei für WoW Bot\n")
                    f.write("# Format: x,y (eine Zeile pro Waypoint, normalisiert 0.0-1.0)\n")
                    f.write("# Zeilen mit # werden ignoriert\n")
                    f.write("# Beispiel: 50,86 in WoW = 0.50,0.86 (wenn max Koordinate = 100)\n")
                    f.write("0.50,0.86\n")
                    f.write("0.44,0.81\n")
                print(f"[WAYPOINTS] Standard-Datei erstellt: {full_path}")
            
            with open(full_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    # Ignoriere leere Zeilen und Kommentare
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse Koordinaten
                    try:
                        parts = line.split(',')
                        if len(parts) == 2:
                            x = float(parts[0].strip())
                            y = float(parts[1].strip())
                            
                            # Konvertiere WoW-Koordinaten zu normalisierten Werten, falls nötig
                            # Wenn Werte > 1.0, dann sind es WoW-Koordinaten (angenommen max = 100)
                            # Konvertiere: WoW-Koordinate / 100.0 = normalisierter Wert
                            if x > 1.0 or y > 1.0:
                                # Werte sind WoW-Koordinaten, normalisiere sie
                                max_coord = 100.0  # Annahme: max WoW-Koordinate = 100
                                x = x / max_coord
                                y = y / max_coord
                                print(f"[WAYPOINTS] Konvertiert WoW-Koordinaten zu normalisierten Werten")
                            
                            waypoints.append((x, y))
                            print(f"[WAYPOINTS] Waypoint {len(waypoints)} geladen: ({x:.3f}, {y:.3f})")
                        else:
                            print(f"[WAYPOINTS] Warnung: Ungültiges Format in Zeile {line_num}: {line}")
                    except ValueError as e:
                        print(f"[WAYPOINTS] Fehler beim Parsen von Zeile {line_num}: {line} - {e}")
            
            if waypoints:
                self.human_input.waypoints = waypoints
                self.human_input.current_waypoint_index = 0
                print(f"[WAYPOINTS] {len(waypoints)} Waypoints erfolgreich geladen!")
            else:
                print(f"[WAYPOINTS] Keine gültigen Waypoints in Datei gefunden!")
                
        except Exception as e:
            print(f"[WAYPOINTS] Fehler beim Laden der Waypoint-Datei: {e}")
            import traceback
            traceback.print_exc()
    
    def save_waypoints_to_file(self, filepath="waypoints.txt"):
        """Speichert Waypoints in eine Textdatei.
        
        Args:
            filepath: Pfad zur Waypoint-Datei
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filepath)
        
        try:
            with open(full_path, 'w') as f:
                f.write("# Waypoint-Datei für WoW Bot\n")
                f.write("# Format: x,y (eine Zeile pro Waypoint)\n")
                f.write("# Zeilen mit # werden ignoriert\n")
                for x, y in self.human_input.waypoints:
                    f.write(f"{x},{y}\n")
            print(f"[WAYPOINTS] {len(self.human_input.waypoints)} Waypoints gespeichert: {full_path}")
        except Exception as e:
            print(f"[WAYPOINTS] Fehler beim Speichern der Waypoint-Datei: {e}")

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
        
        # 3-Sekunden-Pause nach dem Start, damit Bot-Fenster sich öffnen kann und alle Systeme hochfahren
        print("[STATUS] Warte 3 Sekunden für System-Initialisierung...")
        time.sleep(3)
        print("[STATUS] System bereit - Bot beginnt mit Verarbeitung...")
        
        # Zähler für regelmäßiges Fokussieren des WoW-Fensters
        focus_check_counter = 0
        
        while True:
            frame_count += 1
            fps_frame_count += 1
            focus_check_counter += 1
            
            # Fokussiere WoW-Fenster regelmäßig (alle 60 Frames = ca. alle 6 Sekunden bei 10 FPS)
            if focus_check_counter >= 60:
                self._focus_wow_window()
                focus_check_counter = 0
            
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
            
            # Lese Range-Status für Visualisierung (vorher, damit wir die Farbe haben)
            range_state = self.human_input.read_range_from_frame(frame)
            pixel_color = None
            try:
                h, w = frame.shape[:2]
                # Berechne WeakAura-Position relativ zur Frame-Mitte
                frame_center_x = w // 2
                frame_center_y = h // 2
                x = int(frame_center_x + self.human_input.weakuara_offset_x)
                y = int(frame_center_y + self.human_input.weakuara_offset_y)
                if 0 <= x < w and 0 <= y < h:
                    pixel_color = frame[y, x]
            except:
                pass
            
            # Zeichne WeakAura-Position im Detection Frame
            detection_frame = self.draw_weakuara_position(detection_frame, range_state, pixel_color)
            
            # Zeichne Position-Pixel im Detection Frame
            detection_frame = self.draw_position_pixels(detection_frame)
            
            # Lese aktuelle Position aus Frame
            position_data = self.human_input.read_position_from_frame(frame)
            if position_data:
                x, y, facing = position_data
                # Debug-Ausgabe alle 30 Frames
                # Werte als ganze Zahlen anzeigen (multipliziere mit 100 für WoW-Koordinaten)
                if frame_count % 30 == 0:
                    print(f"[POSITION] X={int(x * 100)}, Y={int(y * 100)}, Facing={facing:.1f}°")
            
            # Prüfe ob YOLO ein Target erkannt hat
            has_detection = len(results[0].boxes) > 0
            
            # --- MODUS-TRACKING für Wechsel-Meldungen ---
            if not hasattr(self, '_last_bot_mode'):
                self._last_bot_mode = None
            
            # --- WAYPOINT-NAVIGATION ---
            # Nur wenn kein YOLO-Target vorhanden ist, navigiere zu Waypoints
            navigating_to_waypoint = False
            if not has_detection and len(self.human_input.waypoints) > 0:
                # Prüfe ob wir noch einen aktiven Waypoint haben
                if self.human_input.current_waypoint_index < len(self.human_input.waypoints):
                    target_waypoint = self.human_input.waypoints[self.human_input.current_waypoint_index]
                    target_x, target_y = target_waypoint
                    
                    # Navigiere zum Waypoint
                    waypoint_reached = self.human_input.drive_to_waypoint(target_x, target_y)
                    
                    if waypoint_reached:
                        print(f"[NAVIGATION] Waypoint {self.human_input.current_waypoint_index + 1} erreicht!")
                        self.human_input.current_waypoint_index += 1
                        
                        # Wenn alle Waypoints erreicht, starte von vorne
                        if self.human_input.current_waypoint_index >= len(self.human_input.waypoints):
                            print("[NAVIGATION] Alle Waypoints erreicht! Starte von vorne.")
                            self.human_input.current_waypoint_index = 0
                    
                    navigating_to_waypoint = True
                else:
                    # Keine Waypoints mehr, reset
                    self.human_input.current_waypoint_index = 0
            
            # Bestimme aktuellen Bot-Modus
            current_bot_mode = None
            if navigating_to_waypoint:
                current_bot_mode = "WAYPOINT_NAVIGATION"
            elif self.human_input.target_search_mode:
                current_bot_mode = "TARGET_SEARCH"
            elif has_detection:
                current_bot_mode = "COMBAT"
            else:
                current_bot_mode = "IDLE"
            
            # Meldung bei Modus-Wechsel
            if self._last_bot_mode is not None and self._last_bot_mode != current_bot_mode:
                print(f"[MODUS] Wechsel: {self._last_bot_mode} -> {current_bot_mode}")
            self._last_bot_mode = current_bot_mode
            
            # --- TARGET-SUCHE-LOGIK ---
            # Nur ausführen wenn nicht zu Waypoint navigiert wird
            if not navigating_to_waypoint:
                # Prüfe ob Target vorhanden (basierend auf Range-Farbe)
                self.human_input.handle_target_search(range_state, has_detection)
            
            # Nur im Tracking-Modus die normale Logik ausführen
            if not self.human_input.target_search_mode:
                # Tracking-Modus: Normale Logik
                target_x = None  # Reset target
                target_y = None  # Reset target
                
                if has_detection:
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
                    # Kein Ziel gefunden
                    # WICHTIG: W-Taste NICHT loslassen, wenn wir zu einem Waypoint navigieren!
                    # Die Waypoint-Navigation verwaltet die W-Taste selbst
                    target_x = None
                    target_y = None
                    # W-Taste wird nur losgelassen, wenn wir NICHT zu einem Waypoint navigieren
                    if not navigating_to_waypoint:
                        if self.human_input.w_key_held:
                            self.human_input._hold_w_key(False)
                
                # --- HIER KOMMT DIE BEWEGUNG REIN ---
                # WICHTIG: move_mouse_human NICHT aufrufen während Waypoint-Navigation!
                # Die Waypoint-Navigation verwendet nur W-Taste, keine Mausbewegungen
                # move_mouse_human würde die Bewegung stören (kleine Mausbewegungen führen zu Zucken)
                if not navigating_to_waypoint:
                    # Nur im Combat-Modus (mit YOLO-Target) Mausbewegungen verwenden
                    # Wir übergeben die absolute X- und Y-Koordinate des Ziels. 
                    # Die Klasse weiß selbst, wo die Bildschirmmitte ist.
                    # X ist präzise, Y ist weniger präzise (nur obere Hälfte).
                    # Übergebe auch die gesamte Scan-Region für obere Grenze-Erkennung
                    self.human_input.move_mouse_human(target_x, target_y, scan_region)
                
                # --- RANGE-ERKENNUNG & VORWÄRTSBEWEGUNG (W-Taste) ---
                # Range-State wurde bereits oben für Visualisierung gelesen
                # Verarbeite Range-State-Änderung (verhindert Key-Spamming)
                # WICHTIG: Nur wenn nicht NO_TARGET UND nicht während Waypoint-Navigation
                # Die Waypoint-Navigation verwaltet die W-Taste selbst
                if range_state != 'NO_TARGET' and not navigating_to_waypoint:
                    self.human_input.handle_range_state_change(range_state)
                
                # --- KAMPF-ROTATIONEN ---
                # Aktualisiere Melee- und Range-Rotationen basierend auf Range-State
                if self.human_input.melee_rotation is not None and self.human_input.range_rotation is not None:
                    self.human_input.melee_rotation.update(
                        target_x, 
                        self.human_input.center_x, 
                        range_state, 
                        has_detection
                    )
                    self.human_input.range_rotation.update(
                        target_x, 
                        self.human_input.center_x, 
                        range_state, 
                        has_detection
                    )
            else:
                # Target-Suche-Modus: Keine normale Tracking-Logik
                # WICHTIG: W-Taste NICHT loslassen, wenn wir zu einem Waypoint navigieren!
                # Die Waypoint-Navigation verwaltet die W-Taste selbst
                if not navigating_to_waypoint:
                    if self.human_input.w_key_held:
                        self.human_input._hold_w_key(False)

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
                    
                    # WICHTIG: Bringt das Bot-Fenster NICHT in den Vordergrund, da dies den Fokus
                    # vom WoW-Fenster abzieht und Tastatureingaben verhindert!
                    # Nur beim ersten Frame: kleine Verzögerung, damit Fenster Zeit hat zu erstellen
                    if frame_count == 1:
                        time.sleep(0.1)  # Kurze Verzögerung für Fenster-Erstellung
                        # Beim ersten Frame einmalig das Fenster in den Vordergrund bringen
                        # (danach nicht mehr, um WoW-Fokus zu behalten)
                        self._bring_window_to_front("Detection View")
                    # ENTFERNT: Regelmäßiges Bringen des Bot-Fensters in den Vordergrund
                    # Dies verhindert, dass das WoW-Fenster den Fokus verliert
                    # elif frame_count % 60 == 0:
                    #     self._bring_window_to_front("Detection View")
                    
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

        # Stelle sicher, dass alle Tasten losgelassen werden
        if self.human_input.rmb_held:
            self.human_input._hold_rmb(False)
        if self.human_input.w_key_held:
            self.human_input._hold_w_key(False)
        
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