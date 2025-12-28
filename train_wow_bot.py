"""
WoW Bot Training mit YOLO8 und Roboflow
Lädt Trainingsdaten von Roboflow und trainiert ein YOLO8-Modell
"""

from ultralytics import YOLO
from roboflow import Roboflow
import torch

# EINSTELLUNGEN
# TODO: Hier deinen Roboflow API-Key eintragen
ROBOFLOW_API_KEY = "bWCQrHFXnnZsy0GLxM8c"
WORKSPACE = "icq"  # Aus data.yaml
PROJECT = "red_cross"  # Aus data.yaml
VERSION = 1  # Aus data.yaml

# GPU-Erkennung (unterstützt NVIDIA CUDA und AMD DirectML)
def detect_device():
    """Erkennt verfügbare GPU (CUDA oder DirectML) oder verwendet CPU"""
    # 1. Prüfe CUDA (NVIDIA)
    if torch.cuda.is_available():
        device = 0  # Erste GPU verwenden
        print(f"✓ NVIDIA GPU erkannt: {torch.cuda.get_device_name(0)}")
        print(f"✓ CUDA Version: {torch.version.cuda}")
        return device
    
    # 2. Prüfe DirectML (AMD/Intel auf Windows)
    # HINWEIS: Ultralytics YOLO unterstützt DirectML nicht direkt.
    # PyTorch mit DirectML kann aber intern genutzt werden, wenn installiert.
    try:
        import torch_directml
        if torch_directml.is_available():
            print(f"✓ AMD/Intel GPU erkannt (DirectML)")
            print(f"⚠ HINWEIS: Ultralytics YOLO nutzt DirectML möglicherweise nicht direkt.")
            print(f"⚠ Training läuft auf CPU (mit DirectML-Beschleunigung falls möglich)")
            print(f"💡 Für bessere Performance: Nutze Linux mit ROCm oder trainiere auf CPU")
            # Ultralytics erwartet "cpu" oder CUDA-Device-Nummer
            # DirectML wird von PyTorch intern genutzt, wenn verfügbar
            device = "cpu"
            return device
    except ImportError:
        pass
    
    # 3. Fallback auf CPU
    device = "cpu"
    print("⚠ Keine GPU gefunden - Training läuft auf CPU (sehr langsam!)")
    print("💡 Tipp: Für AMD-GPUs installiere 'torch-directml' (siehe README_AMD.md)")
    return device

DEVICE = detect_device()

# 1. DATEN LADEN (Hier kommt dein Roboflow-Code rein)
rf = Roboflow(api_key=ROBOFLOW_API_KEY)
project = rf.workspace(WORKSPACE).project(PROJECT)
version = project.version(VERSION)
dataset = version.download("yolov8")

# 2. MODELL LADEN
# Wir nehmen 'yolov8n.pt' (Nano-Version) für maximale FPS
model = YOLO("yolov8n.pt") 

# 3. TRAINING STARTEN
if __name__ == '__main__':
    print("=" * 60)
    print("🚀 WoW Bot Training mit YOLO8")
    print("=" * 60)
    print(f"📦 Datensatz geladen von: {dataset.location}")
    print(f"📊 Training startet...\n")
    
    results = model.train(
        data=f"{dataset.location}/data.yaml", 
        epochs=200,       # Wie oft er den Datensatz durchgeht
        imgsz=640,       # Bildgröße (bei Out-of-Memory auf 416 oder 320 reduzieren)
        batch=4,         # Batch-Größe reduzieren (Standard: 16) - reduziert GPU-Speicher
                        # Falls immer noch Out-of-Memory: auf 2 oder 1 reduzieren
        plots=True,      # Erstellt schöne Diagramme vom Fortschritt
        device=DEVICE,   # Automatisch GPU oder CPU
        amp=True,        # Mixed Precision Training (spart Speicher)
        workers=4        # Anzahl der Worker-Threads für Datenladen
    )
    
    print("\n" + "=" * 60)
    print("✅ Training abgeschlossen!")
    print("=" * 60)
    print(f"📁 Dein Modell liegt unter 'runs/detect/train/weights/best.pt'")
    print(f"📁 Das letzte Modell liegt unter 'runs/detect/train/weights/last.pt'")
