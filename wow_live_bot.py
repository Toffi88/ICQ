"""
================================================================================
WoW Bot - Automatisierter Target-Tracking und Bewegungs-Bot
================================================================================

HAUPTFUNKTIONEN:
---------------
1. Target-Erkennung:
   - YOLO-basierte Objekterkennung (White Skull Modell)
   - WeakAura-basierte Range-Erkennung (Farbcodierung: Rot/Grün/Blau/Schwarz)
   - Automatische Target-Suche mit Tab-Taste und Kameradrehung

2. Kamera-Steuerung:
   - Präzise horizontale Mausbewegung zum Target (X-Achse)
   - Weniger präzise vertikale Steuerung (Y-Achse) - hält Target in oberer Hälfte
   - Verhindert, dass Target oben aus dem Bildschirm rutscht

3. Bewegungssteuerung:
   - W-Taste: Läuft nach vorne wenn Target OUT_OF_RANGE (Rot)
   - Stoppt wenn Target in MELEE_RANGE (Grün) oder IN_RANGE (Blau)
   - Range-Status wird aus WeakAura-Farbe gelesen

4. Target-Suche-Logik (State-Machine, nicht-blockierend):
   - Schwarz in WeakAura = kein Target → Tab drücken
   - Nach Tab weiterhin Schwarz → ~30° Drehung → erneut Tab
   - Farbwechsel von Schwarz → F1 drücken (setzt Mark auf Target)
   - Wenn YOLO 5x kein Mark findet trotz Target → Drehung
   - Nahtlose Rotation über mehrere Frames (15-20 Schritte)
   - Minimale Wartezeiten für schnelle, flüssige Bewegung

5. Kampf-Rotationen (combat.py):
   - MeleeRotation: Taste 2 für MELEE_RANGE (Grün)
   - RangeRotation: Taste 3 für IN_RANGE (Blau)
   - Automatischer Wechsel zwischen Rotationen basierend auf Range-State
   - Rotation nur wenn Target in Deadzone (wie W-Taste)
   - Zufällige Timing-Variationen (0.9-1.1 Sekunden) für menschliche Wirkung

6. Benutzer-Interventionserkennung:
   - Erkennt wenn Benutzer Maus benutzt → pausiert Bot automatisch
   - Synchronisiert Status der rechten Maustaste

WICHTIGE KONZEPTE:
-----------------
- Deadzone: Bereich um Bildschirmmitte, in dem keine Bewegung nötig ist
- Range-States: OUT_OF_RANGE (Rot), MELEE_RANGE (Grün), IN_RANGE (Blau), NO_TARGET (Schwarz)
- Target-Search-Mode vs. Tracking-Mode: Zwei Betriebsmodi
- Smoothe Bewegungen: Reduzierte Geschwindigkeit (speed_factor=0.10, max_step=15)
- State-Machine: Nicht-blockierende Target-Suche über mehrere Frames
- Frame-basierte Rotation: Nahtlose Drehung ohne Sleep-Blockierungen
- Zufällige Variationen: Alle Bewegungen und Zeitangaben enthalten Zufall für menschliche Wirkung

KONFIGURATION:
-------------
- WeakAura-Position: weakuara_offset_x, weakuara_offset_y (relativ zur Bildschirmmitte)
- Bewegungsgeschwindigkeit: speed_factor=0.10, target_search_speed_factor=0.15 (50% schneller)
- Deadzones: deadzone (horizontal), vertical_deadzone, center_deadzone_x=120
- Range-Schwellenwerte: In get_range_state_from_color() definiert
- Tab-Delay: 0.1 Sekunden (reduziert für schnellere Suche)
- Rotation-Schritte: 15-20 für nahtlose Bewegung

PERFORMANCE-OPTIMIERUNGEN:
--------------------------
- Keine blockierenden Sleeps während Target-Suche (0 FPS-Einbruch)
- State-Machine verteilt Wartezeiten über mehrere Frames
- Minimale Wartezeiten (0.05s) für nahtlose Bewegung
- Lineare Interpolation für flüssigere Rotation

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

# Windows API für Mausstatus-Prüfung
try:
    import win32api
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
        if use_smoothing:
            # Verwende erhöhte Geschwindigkeit während Target-Suche (50% schneller)
            current_speed_factor = self.target_search_speed_factor if self.target_search_mode else self.speed_factor
            move_x = int(move_x * current_speed_factor)
            max_step = 15  # Reduziert für smoothere Bewegung
            move_x = max(min(move_x, max_step), -max_step)
            
            # Wenn wir sehr nah sind, erzwinge kleine Schritte
            if abs(move_x) < 1 and move_x != 0:
                move_x = 1 if move_x > 0 else -1
            
            # Jitter für menschliche Wirkung
            jitter = random.randint(-2, 2)
            move_x += jitter
        
        # Führe Bewegung aus
        pydirectinput.moveRel(move_x, move_y, relative=True)
        
        # Keine Pause während Target-Suche für kontinuierliche Bewegung
        if not self.target_search_mode:
            time.sleep(random.uniform(0.020, 0.030))  # Normale Pause nur außerhalb der Suche
    
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
    
    def _hold_w_key(self, hold=True):
        """Verwaltet den W-Taste-Status (Vorwärtsbewegung)."""
        print(f"[_hold_w_key] Aufgerufen mit hold={hold}, aktueller Status w_key_held={self.w_key_held}")
        if hold and not self.w_key_held:
            print("[_hold_w_key] *** DRÜCKE W-TASTE ***")
            try:
                pydirectinput.keyDown('w')
                self.w_key_held = True
                print(f"[_hold_w_key] W-Taste sollte jetzt gedrückt sein, w_key_held={self.w_key_held}")
                # Längere Pause, damit das Spiel die Taste registriert
                time.sleep(random.uniform(0.05, 0.1))
            except Exception as e:
                print(f"[_hold_w_key] FEHLER beim Drücken der W-Taste: {e}")
        elif not hold and self.w_key_held:
            print("[_hold_w_key] *** LASSE W-TASTE LOS ***")
            try:
                pydirectinput.keyUp('w')
                self.w_key_held = False
                print(f"[_hold_w_key] W-Taste sollte jetzt losgelassen sein, w_key_held={self.w_key_held}")
                time.sleep(random.uniform(0.02, 0.05))
            except Exception as e:
                print(f"[_hold_w_key] FEHLER beim Loslassen der W-Taste: {e}")
        else:
            print(f"[_hold_w_key] Keine Änderung nötig (hold={hold}, w_key_held={self.w_key_held})")
    
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
            
            # Debug-Ausgabe (häufiger für besseres Debugging)
            if not hasattr(self, '_range_debug_counter'):
                self._range_debug_counter = 0
            self._range_debug_counter += 1
            
            if self._range_debug_counter % 5 == 0:  # Alle 5 Frames (häufiger)
                print(f"[RANGE] Position ({x}, {y}), Farbe BGR=({pixel_color[0]}, {pixel_color[1]}, {pixel_color[2]}), State={range_state}")
            
            return range_state
        except Exception as e:
            print(f"[RANGE] Fehler beim Lesen der Range: {e}")
            import traceback
            traceback.print_exc()
            return 'UNKNOWN'
    
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
        # Kurze Pause, damit das Spiel die Bewegung registriert
        time.sleep(random.uniform(0.01, 0.02))
        pydirectinput.moveRel(move_x, move_y, relative=True)
        
        # Zusätzliche Pause nach Bewegung für smoothere Bewegung
        time.sleep(random.uniform(0.015, 0.025))
        
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

        # 7. "Micro-Sleeps" - Das 'Chillen' (erhöht für smoothere Bewegung)
        # Je näher wir am Ziel sind, desto vorsichtiger werden wir.
        if distance < 100:
            time.sleep(random.uniform(0.020, 0.035)) # Feinjustierung - länger (von 0.015-0.030)
        else:
            time.sleep(random.uniform(0.020, 0.030)) # Schnellere Drehung - aber immer noch kontrolliert (von 0.010-0.020)

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
            
            # Prüfe ob YOLO ein Target erkannt hat
            has_detection = len(results[0].boxes) > 0
            
            # --- TARGET-SUCHE-LOGIK ---
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
                    # Kein Ziel gefunden - W-Taste loslassen
                    target_x = None
                    target_y = None
                    self.human_input._hold_w_key(False)
                
                # --- HIER KOMMT DIE BEWEGUNG REIN ---
                # Wir übergeben die absolute X- und Y-Koordinate des Ziels. 
                # Die Klasse weiß selbst, wo die Bildschirmmitte ist.
                # X ist präzise, Y ist weniger präzise (nur obere Hälfte).
                # Übergebe auch die gesamte Scan-Region für obere Grenze-Erkennung
                self.human_input.move_mouse_human(target_x, target_y, scan_region)
                
                # --- RANGE-ERKENNUNG & VORWÄRTSBEWEGUNG (W-Taste) ---
                # Range-State wurde bereits oben für Visualisierung gelesen
                # Verarbeite Range-State-Änderung (verhindert Key-Spamming)
                # Nur wenn nicht NO_TARGET (dann ist es bereits in handle_target_search behandelt)
                if range_state != 'NO_TARGET':
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
                # W-Taste sollte nicht gedrückt sein
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