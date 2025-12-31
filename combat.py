"""
================================================================================
Combat Rotation Module - Kampf-Rotationen für WoW Bot
================================================================================

WICHTIGER HINWEIS:
-----------------
Alle Zeitangaben und Bewegungen enthalten zufällige Variationen, um
menschliche Wirkung zu erzielen. Dies macht den Bot weniger erkennbar
und wirkt natürlicher.

FUNKTIONEN:
----------
- BaseRotation: Basis-Klasse für alle Rotationen
- MeleeRotation: Rotation für MELEE_RANGE (Taste 2)
- RangeRotation: Rotation für IN_RANGE (Taste 3)

LOGIK:
-----
- Rotation läuft nur wenn Target in Deadzone (center_deadzone_x)
- Taste wird alle ~1 Sekunde gedrückt (mit Zufall: 0.9-1.1s)
- Rotation pausiert bei OUT_OF_RANGE (dann läuft Charakter)
- Rotation stoppt bei NO_TARGET oder kein YOLO-Detection
- Automatischer Wechsel zwischen Melee und Range Rotation

================================================================================
"""

import time
import random
import pydirectinput


class BaseRotation:
    """Basis-Klasse für alle Kampf-Rotationen."""
    
    def __init__(self, key, center_deadzone_x):
        """
        Args:
            key: Taste die gedrückt werden soll (z.B. '2' oder '3')
            center_deadzone_x: Deadzone für Zentrums-Erkennung (Pixel)
        """
        self.key = key
        self.center_deadzone_x = center_deadzone_x
        self.last_press_time = 0
        self.press_interval_min = 0.9  # Minimale Zeit zwischen Drücken (Sekunden)
        self.press_interval_max = 1.1  # Maximale Zeit zwischen Drücken (Sekunden)
        self.is_active = False  # Ob Rotation aktuell aktiv ist
    
    def should_rotate(self, target_x, center_x, range_state, has_detection):
        """Prüft ob Rotation ausgeführt werden soll.
        
        Args:
            target_x: X-Koordinate des Targets (None wenn kein Target)
            center_x: X-Koordinate der Bildschirmmitte
            range_state: Aktueller Range-State
            has_detection: True wenn YOLO Target erkannt hat
            
        Returns:
            True wenn Rotation ausgeführt werden soll, False sonst
        """
        # Keine Rotation wenn kein Target
        if target_x is None or not has_detection:
            return False
        
        # Keine Rotation bei OUT_OF_RANGE (dann läuft Charakter)
        if range_state == 'OUT_OF_RANGE':
            return False
        
        # Keine Rotation bei NO_TARGET
        if range_state == 'NO_TARGET':
            return False
        
        # Prüfe ob Target in Deadzone (gleiche wie für W-Taste)
        offset_x = abs(target_x - center_x)
        in_deadzone = offset_x <= self.center_deadzone_x
        
        return in_deadzone
    
    def press_key(self):
        """Drückt die Rotation-Taste einmal."""
        try:
            pydirectinput.press(self.key)
            self.last_press_time = time.time()
            # Kurze Pause nach Drücken (mit Zufall für menschliche Wirkung)
            time.sleep(random.uniform(0.05, 0.1))
        except Exception as e:
            print(f"[ROTATION] Fehler beim Drücken der Taste {self.key}: {e}")
    
    def update(self, target_x, center_x, range_state, has_detection):
        """Aktualisiert die Rotation basierend auf aktuellen Bedingungen.
        
        Args:
            target_x: X-Koordinate des Targets
            center_x: X-Koordinate der Bildschirmmitte
            range_state: Aktueller Range-State
            has_detection: True wenn YOLO Target erkannt hat
        """
        should_rotate = self.should_rotate(target_x, center_x, range_state, has_detection)
        
        # Nur Meldung bei Rotation-Wechsel (Start/Stop), keine Debug-Ausgabe mehr
        if should_rotate:
            # Rotation sollte aktiv sein
            if not self.is_active:
                self.is_active = True
                print(f"[ROTATION] Starte {self.__class__.__name__} (Taste {self.key})")
            
            # Prüfe ob Zeit für nächsten Tastendruck
            current_time = time.time()
            time_since_last_press = current_time - self.last_press_time
            
            # Zufälliges Intervall für menschliche Wirkung
            interval = random.uniform(self.press_interval_min, self.press_interval_max)
            
            if time_since_last_press >= interval:
                self.press_key()
        else:
            # Rotation sollte nicht aktiv sein
            if self.is_active:
                self.is_active = False
                print(f"[ROTATION] Stoppe {self.__class__.__name__} (Taste {self.key})")
            self.last_press_time = 0  # Reset Timer


class MeleeRotation(BaseRotation):
    """Rotation für MELEE_RANGE - drückt Taste 2."""
    
    def __init__(self, center_deadzone_x):
        super().__init__('2', center_deadzone_x)
    
    def should_rotate(self, target_x, center_x, range_state, has_detection):
        """Rotation nur bei MELEE_RANGE."""
        # Basis-Prüfung
        if not super().should_rotate(target_x, center_x, range_state, has_detection):
            return False
        
        # Nur bei MELEE_RANGE
        return range_state == 'MELEE_RANGE'


class RangeRotation(BaseRotation):
    """Rotation für IN_RANGE - drückt Taste 3."""
    
    def __init__(self, center_deadzone_x):
        super().__init__('3', center_deadzone_x)
    
    def should_rotate(self, target_x, center_x, range_state, has_detection):
        """Rotation nur bei IN_RANGE."""
        # Basis-Prüfung
        if not super().should_rotate(target_x, center_x, range_state, has_detection):
            return False
        
        # Nur bei IN_RANGE
        return range_state == 'IN_RANGE'

