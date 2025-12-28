"""
Hilfsskript zum Ermitteln der Bildschirm-Informationen
Führt dieses Skript aus, um die korrekten Werte für PREVIEW_WINDOW_X und PREVIEW_WINDOW_Y zu finden
"""

import pygetwindow as gw
import win32api
import win32con

print("="*60)
print("Bildschirm-Informationen")
print("="*60)

# Primäre Bildschirmauflösung
primary_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
primary_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
print(f"\nPrimärer Bildschirm:")
print(f"  Breite: {primary_width}px")
print(f"  Höhe: {primary_height}px")

# Virtuelle Bildschirmgröße (alle Bildschirme zusammen)
virtual_width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
virtual_height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
virtual_left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
virtual_top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)

print(f"\nVirtueller Desktop (alle Bildschirme):")
print(f"  Position: ({virtual_left}, {virtual_top})")
print(f"  Größe: {virtual_width}x{virtual_height}px")

# WoW-Fenster Position
try:
    wow_win = gw.getWindowsWithTitle('World of Warcraft')[0]
    print(f"\nWoW-Fenster:")
    print(f"  Position: ({wow_win.left}, {wow_win.top})")
    print(f"  Größe: {wow_win.width}x{wow_win.height}px")
    
    # Auf welchem Bildschirm ist WoW?
    if wow_win.left < primary_width and wow_win.left >= 0:
        print(f"  -> WoW ist auf dem PRIMAREN Bildschirm")
        print(f"  -> 2. Bildschirm beginnt bei x={virtual_left}")
        if virtual_left < 0:
            print(f"\nEmpfohlene PREVIEW_WINDOW_X: {virtual_left + 50} (2. Bildschirm ist LINKS)")
        else:
            print(f"\nEmpfohlene PREVIEW_WINDOW_X: {primary_width + 50} (2. Bildschirm ist RECHTS)")
    else:
        print(f"  -> WoW ist auf dem 2. Bildschirm")
        print(f"  -> 2. Bildschirm beginnt bei x={virtual_left}")
        print(f"\nEmpfohlene PREVIEW_WINDOW_X: 50 (auf primarem Bildschirm)")
        
except IndexError:
    print("\n⚠ WoW-Fenster nicht gefunden!")

print("\n" + "="*60)
print("Empfehlung für wow_live_bot.py:")
print("="*60)
print("Falls das Fenster nicht sichtbar ist, setze in wow_live_bot.py:")
print(f"  PREVIEW_WINDOW_X = {primary_width + 50 if wow_win.left < primary_width else 50}")
print(f"  PREVIEW_WINDOW_Y = 50")
print("="*60)

