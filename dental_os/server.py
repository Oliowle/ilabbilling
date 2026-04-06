"""
Dental OS - FastAPI Backend
A dental lab billing system for creating Kostenvoranschläge (cost estimates)
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configuration
DB_PATH = "/sessions/blissful-lucid-allen/dental_os/dental_os.db"
STATIC_DIR = "/sessions/blissful-lucid-allen/dental_os"
HTML_FILE = os.path.join(STATIC_DIR, "index.html")

# Seed Data
POSITIONEN = [
    ("0001", "Eingang/Ausgang Desinfektion", 4.83, "leistung"),
    ("0010", "Modell aus Hartgips", 10.79, "material"),
    ("0011", "Superhartgipsmodell", 15.73, "material"),
    ("0012", "Kontrollmodell", 11.0, "material"),
    ("0014", "Sägemodell", 19.88, "leistung"),
    ("0015", "Stumpf herausnehmbar mit Pins", 18.0, "leistung"),
    ("0016", "Split-Cast Sockel an Modell", 9.38, "leistung"),
    ("0021", "Modell dublieren", 16.5, "leistung"),
    ("0030", "Implantat Modell", 17.0, "material"),
    ("0051", "Stumpf säg. unter Mik., vorb. inkl. Pin", 25.0, "leistung"),
    ("0056", "Stumpf aus feuerfester Masse", 21.35, "leistung"),
    ("0070", "Zahnfleischmaske, abnehmbar", 25.0, "leistung"),
    ("0100", "Modellpaar herstellen u. sockeln", 12.0, "leistung"),
    ("0110", "Dublieren eines Einzelstumpfes", 10.11, "leistung"),
    ("0115", "Unterkiefer-Protrusionsschiene Modell", 15.0, "leistung"),
    ("0120", "Mittelwertartikulator", 12.42, "material"),
    ("0125", "UKPS Artikulator-Montage", 15.0, "leistung"),
    ("0200", "Modellmontage in Mittelwertartikulator", 12.42, "leistung"),
    ("0201", "Montage nach Gesichtsbogen", 15.69, "leistung"),
    ("0202", "Montage eines Gegenkiefermodelles", 10.79, "material"),
    ("0207", "Virtueller Artikulator", 25.84, "leistung"),
    ("0250", "Einstellen u. Auswerten e. Registrates", 23.0, "leistung"),
    ("0301", "Selektives Einschleifen Modellpaar", 4.5, "leistung"),
    ("0401", "Gerüst anpassen / Brückenglied", 22.0, "leistung"),
    ("0500", "Zahnfarbenbestimmung", 19.0, "leistung"),
    ("0501", "Foto - und Modell Funktionsanalyse", 60.0, "leistung"),
    ("0600", "Wax-up diagnostisch, je Zahn", 20.0, "leistung"),
    ("0611", "Mock-up Schiene", 106.74, "leistung"),
    ("0752", "Individueller Löffel für Imp.", 29.66, "leistung"),
    ("0804", "Formteil für provisorische Versorgung", 34.0, "leistung"),
    ("0805", "Langzeitprovisorium Kst./ CAD-CAM", 93.26, "leistung"),
    ("0850", "Adjustierte Aufbissschiene", 269.0, "leistung"),
    ("0851", "Aufbiss", 25.0, "leistung"),
    ("0854", "Sportschutzschiene", 85.0, "leistung"),
    ("0857", "Miniplastschiene", 79.0, "leistung"),
    ("0858", "Jig-Aufbau", 40.0, "leistung"),
    ("1000", "Aufwand bei Suprakonstruktion", 110.0, "leistung"),
    ("1003", "UKPS Gerüst-Herstellung", 120.0, "leistung"),
    ("1010", "Klebeverbindung Titan / Lisi / Zirkon", 84.0, "leistung"),
    ("1011", "Modellimplantat repositionieren", 11.8, "leistung"),
    ("1016", "Individuelles Titanabutment", 55.0, "leistung"),
    ("1017", "Individuelles E.Max-Abutment", 60.0, "leistung"),
    ("3000", "Krone/Brückenglied gefräst aus Zirkon", 110.0, "leistung"),
    ("3002", "Zirkonkr./ Br.-Glied vollanatomisch", 160.0, "leistung"),
    ("3003", "Zirkongerüst auf Implantat", 162.92, "leistung"),
    ("4010", "Aufbissbehelf mit adjustierter Oberfläche (BEL)", 0, "leistung"),
    ("5001", "Krone/Kappe/Schale Lithium disilicate", 123.0, "leistung"),
    ("5002", "Krone aus Presskeramik", 160.0, "leistung"),
    ("5003", "Teilkrone/Onlay Presskeramik", 197.0, "leistung"),
    ("5010", "UKPS Kunststoff-Verarbeitung", 45.0, "leistung"),
    ("5100", "UKPS Schiene Oberteil", 95.0, "leistung"),
    ("5110", "UKPS Schiene Unterteil", 95.0, "leistung"),
    ("5200", "Inlay aus Presskeramik, e.max", 113.0, "leistung"),
    ("5302", "Keramische Schulter", 18.0, "leistung"),
    ("5500", "Mehrflächige Verblendung Keramik", 125.0, "leistung"),
    ("5502", "Wurzelpontic aus Keramik", 45.0, "leistung"),
    ("5504", "Indiv. charakt. Keramik", 35.0, "leistung"),
    ("5505", "Krone e.max auf Implantat", 195.0, "leistung"),
    ("5509", "Individuelle Oberflächenstruktur", 18.0, "leistung"),
    ("5601", "Frontzahn. n. gnathologischen Kriterien", 56.0, "leistung"),
    ("5602", "Kaufläche n. gnathologischen Kriterien", 27.0, "leistung"),
    ("5603", "Arbeiten unter Stereomikroskop, je Zahn", 35.0, "leistung"),
    ("5604", "Aufpassen auf Zweitmodell, je Krone", 10.5, "leistung"),
    ("5606", "Individualität / Maltechnik", 40.0, "leistung"),
    ("5800", "Galvanokäppchen", 65.0, "leistung"),
    ("7100", "Aufbiss einschleifen (BEL)", 0, "leistung"),
    ("8000", "Versand, je Versandgang", 23.0, "material"),
    ("9022", "Digitale Artikulation", 18.0, "leistung"),
    ("9024", "Modell Implantat 3d Print", 33.71, "material"),
    ("9025", "Modell 3d Print", 23.0, "material"),
    ("9027", "Digitalen Stumpf designen/ drucken", 20.22, "leistung"),
    ("9030", "Kontrollmodell 3d Print", 19.0, "material"),
    ("9032", "Digitale Axiographie-Integration", 37.0, "leistung"),
    ("9100", "Kiefergelenkanalyse", 85.0, "leistung"),
    ("9330", "Versandkosten (BEL)", 0, "leistung"),
    ("9335", "UKPS Versandkosten", 15.0, "material"),
    ("E001", "e-max Presspellet, je Teil", 25.0, "material"),
    ("E005", "Amber Mill", 30.0, "material"),
    ("E060", "Einbettmasse, Pressmaterial", 15.0, "material"),
    ("I200", "Camlog Abformpfosten offene Abformung", 60.0, "material"),
    ("I201", "Modellanalog", 30.0, "material"),
    ("I221", "Modellanalog Titanbasis", 35.0, "material"),
    ("I614", "Klebebasis Titan", 87.0, "material"),
    ("I802", "3D Scan-Body", 85.0, "material"),
    ("S405", "PMMA Blank", 39.0, "material"),
    ("Z100", "Zirkonrohling, je Einheit", 48.0, "material"),
    ("020", "Sonderkunststoff", 15.0, "material"),
]

KUERZEL = [
    ("ZK", "Vollanatomische Zirkonkrone", "Vollanatomische Zirkonkrone, gefräst und individuell charakterisiert"),
    ("ZKV", "Zirkonkrone mit Verblendung", "Zirkonkrone mit mehrflächiger Keramikverblendung"),
    ("ZBR", "Zirkon-Brücke", "Brücke aus Zirkon, vollanatomisch"),
    ("SCH", "Aufbissschiene", "Adjustierte Aufbissschiene mit Artikulator-Montage"),
    ("SCHK", "Kassenschiene", "Aufbissschiene für Kassenpatienten (BEL-Positionen)"),
    ("SCHS", "Schnarcherschiene Privat", "Anti-Schnarch-Schiene (UKPS) Privatpatient"),
    ("SCHSK", "Schnarcherschiene Kasse", "Anti-Schnarch-Schiene (UKPS) Kassenpatient"),
    ("SKM", "Suprakonstruktion", "Zirkonkrone auf Implantat-Suprakonstruktion"),
    ("PK", "Presskeramik-Krone", "Teilkrone oder Onlay aus Presskeramik"),
    ("EMX", "E.Max Krone", "Krone aus Lithiumdisilikat (e.max)"),
    ("EMXI", "E.Max Implantat", "E.Max Krone auf Implantat mit Klebebasis"),
    ("VEN", "Veneer", "Keramikschale (Veneer) aus Lithiumdisilikat"),
    ("MOD", "Modellherstellung", "Nur Modellherstellung und Artikulation"),
    ("MINI", "Miniplastschiene", "Einfache Tiefzieh-Miniplastschiene"),
    ("MOCK", "Mock-Up", "Mock-Up Schiene für Ästhetik-Probe"),
    ("JIGS", "Jig", "Jig-Schiene für Bisslage-Registrierung"),
    ("SMIL", "Smile Design", "Digitales Smile Design mit Flowable Injection"),
    ("WAX", "Wax-Up", "Diagnostisches Wax-Up"),
    ("GB", "Gesichtsbogen", "Nur Gesichtsbogen-Abrechnung"),
    ("MKON", "Münchner Konzept", "Münchner Konzept Schiene"),
    ("INL", "Inlay", "Inlay aus Presskeramik"),
    ("LZP", "Langzeitprovisorium", "Langzeitprovisorium aus Kunststoff/CAD-CAM"),
]

KUERZEL_POS = [
    # ZK - Vollanatomische Zirkonkrone
    ("ZK", "0010", 1, 1, "fix", None),
    ("ZK", "0051", 1, 1, "pro_zahn", None),
    ("ZK", "0200", 1, 1, "fix", "kein_gb_privat"),
    ("ZK", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("ZK", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("ZK", "0120", 1, 1, "fix", None),
    ("ZK", "3002", 1, 1, "pro_zahn", None),
    ("ZK", "5602", 1, 1, "pro_zahn", None),
    ("ZK", "Z100", 1, 1, "pro_zahn", None),
    ("ZK", "9022", 1, 1, "fix", None),
    ("ZK", "9025", 1, 2, "fix", None),
    ("ZK", "9027", 1, 1, "pro_zahn", None),
    ("ZK", "9030", 0, 1, "fix", None),
    ("ZK", "8000", 1, 1, "fix", "privat"),
    ("ZK", "9330", 1, 1, "fix", "kasse"),
    ("ZK", "0301", 0, 1, "fix", None),
    ("ZK", "0001", 0, 1, "fix", None),
    ("ZK", "9100", 0, 1, "fix", None),
    # ZKV - Zirkonkrone mit Verblendung
    ("ZKV", "0010", 1, 1, "fix", None),
    ("ZKV", "0051", 1, 1, "pro_zahn", None),
    ("ZKV", "0200", 1, 1, "fix", "kein_gb_privat"),
    ("ZKV", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("ZKV", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("ZKV", "0120", 1, 1, "fix", None),
    ("ZKV", "3000", 1, 1, "pro_zahn", None),
    ("ZKV", "5500", 1, 1, "pro_zahn", None),
    ("ZKV", "5601", 1, 1, "pro_zahn", None),
    ("ZKV", "5602", 1, 1, "pro_zahn", None),
    ("ZKV", "5509", 1, 1, "pro_zahn", None),
    ("ZKV", "E060", 1, 1, "pro_zahn", None),
    ("ZKV", "E001", 1, 1, "pro_zahn", None),
    ("ZKV", "Z100", 1, 1, "pro_zahn", None),
    ("ZKV", "9022", 1, 1, "fix", None),
    ("ZKV", "9025", 1, 2, "fix", None),
    ("ZKV", "9027", 1, 1, "pro_zahn", None),
    ("ZKV", "9030", 0, 1, "fix", None),
    ("ZKV", "5504", 0, 1, "pro_zahn", None),
    ("ZKV", "5603", 0, 1, "pro_zahn", None),
    ("ZKV", "5604", 0, 1, "pro_zahn", None),
    ("ZKV", "8000", 1, 1, "fix", "privat"),
    ("ZKV", "9330", 1, 1, "fix", "kasse"),
    ("ZKV", "9100", 0, 1, "fix", None),
    # ZBR - Brücke
    ("ZBR", "0010", 1, 1, "fix", None),
    ("ZBR", "0051", 1, 1, "pro_zahn", None),
    ("ZBR", "0200", 1, 1, "fix", "kein_gb_privat"),
    ("ZBR", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("ZBR", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("ZBR", "0120", 1, 1, "fix", None),
    ("ZBR", "3002", 1, 1, "pro_zahn", None),
    ("ZBR", "5602", 1, 1, "pro_zahn", None),
    ("ZBR", "Z100", 1, 1, "pro_zahn", None),
    ("ZBR", "0401", 1, 1, "pro_glied", None),
    ("ZBR", "9022", 1, 1, "fix", None),
    ("ZBR", "9025", 1, 2, "fix", None),
    ("ZBR", "9027", 1, 1, "pro_zahn", None),
    ("ZBR", "8000", 1, 1, "fix", "privat"),
    ("ZBR", "9330", 1, 1, "fix", "kasse"),
    ("ZBR", "9100", 0, 1, "fix", None),
    # SCH - Aufbissschiene (Privat)
    ("SCH", "0001", 1, 1, "fix", None),
    ("SCH", "0850", 1, 1, "fix", None),
    ("SCH", "0851", 1, 1, "fix", "privat"),
    ("SCH", "4010", 1, 1, "fix", "kasse"),
    ("SCH", "0250", 1, 1, "fix", None),
    ("SCH", "0200", 1, 1, "fix", "kein_gesichtsbogen"),
    ("SCH", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("SCH", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("SCH", "0120", 1, 1, "fix", None),
    ("SCH", "9022", 1, 1, "fix", None),
    ("SCH", "9025", 1, 2, "fix", None),
    ("SCH", "8000", 1, 1, "fix", "privat"),
    ("SCH", "9330", 1, 1, "fix", "kasse"),
    ("SCH", "0021", 0, 1, "fix", None),
    ("SCH", "0010", 0, 1, "fix", None),
    ("SCH", "9032", 0, 1, "fix", "privat"),
    ("SCH", "S405", 0, 1, "fix", "privat"),
    # SCHK - Kassenschiene
    ("SCHK", "0021", 1, 1, "fix", None),
    ("SCHK", "0120", 1, 1, "fix", None),
    ("SCHK", "4010", 1, 1, "fix", None),
    ("SCHK", "7100", 1, 1, "fix", None),
    ("SCHK", "9330", 1, 1, "fix", None),
    ("SCHK", "0001", 0, 1, "fix", None),
    ("SCHK", "0010", 0, 1, "fix", None),
    ("SCHK", "0250", 0, 1, "fix", None),
    # SCHS - Schnarcherschiene Privat
    ("SCHS", "0125", 1, 1, "fix", None),
    ("SCHS", "1003", 1, 1, "fix", None),
    ("SCHS", "5010", 1, 1, "fix", None),
    ("SCHS", "5100", 1, 1, "fix", None),
    ("SCHS", "5110", 1, 1, "fix", None),
    ("SCHS", "5200", 1, 1, "fix", None),
    ("SCHS", "9335", 1, 1, "fix", None),
    # SCHSK - Schnarcherschiene Kasse
    ("SCHSK", "0001", 1, 1, "fix", None),
    ("SCHSK", "0115", 1, 1, "fix", None),
    ("SCHSK", "5010", 1, 1, "fix", None),
    ("SCHSK", "5100", 1, 1, "fix", None),
    ("SCHSK", "5110", 1, 1, "fix", None),
    ("SCHSK", "5200", 1, 1, "fix", None),
    ("SCHSK", "7100", 1, 1, "fix", None),
    ("SCHSK", "9022", 1, 1, "fix", None),
    ("SCHSK", "9330", 1, 1, "fix", None),
    # SKM - Suprakonstruktion
    ("SKM", "0010", 1, 1, "fix", None),
    ("SKM", "0030", 1, 1, "pro_zahn", None),
    ("SKM", "0200", 1, 1, "fix", "kein_gb_privat"),
    ("SKM", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("SKM", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("SKM", "0120", 1, 1, "fix", None),
    ("SKM", "1000", 1, 1, "pro_zahn", None),
    ("SKM", "1010", 1, 1, "pro_zahn", None),
    ("SKM", "1011", 1, 1, "pro_zahn", None),
    ("SKM", "3003", 1, 1, "pro_zahn", None),
    ("SKM", "I201", 1, 1, "pro_zahn", None),
    ("SKM", "I614", 1, 1, "pro_zahn", None),
    ("SKM", "9022", 1, 1, "fix", None),
    ("SKM", "9024", 1, 1, "fix", None),
    ("SKM", "9025", 1, 2, "fix", None),
    ("SKM", "3002", 0, 1, "pro_zahn", None),
    ("SKM", "0016", 0, 1, "fix", None),
    ("SKM", "0600", 0, 1, "pro_zahn", None),
    ("SKM", "8000", 1, 1, "fix", "privat"),
    ("SKM", "9330", 1, 1, "fix", "kasse"),
    ("SKM", "9100", 0, 1, "fix", None),
    # PK - Presskeramik
    ("PK", "0010", 1, 1, "fix", None),
    ("PK", "0051", 1, 1, "pro_zahn", None),
    ("PK", "0200", 1, 1, "fix", "kein_gb_privat"),
    ("PK", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("PK", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("PK", "0120", 1, 1, "fix", None),
    ("PK", "5003", 1, 1, "pro_zahn", None),
    ("PK", "E001", 1, 1, "pro_zahn", None),
    ("PK", "E060", 1, 1, "pro_zahn", None),
    ("PK", "5602", 1, 1, "pro_zahn", None),
    ("PK", "0600", 0, 1, "pro_zahn", None),
    ("PK", "9022", 0, 1, "fix", None),
    ("PK", "9025", 0, 2, "fix", None),
    ("PK", "9027", 0, 1, "pro_zahn", None),
    ("PK", "8000", 1, 1, "fix", "privat"),
    ("PK", "9330", 1, 1, "fix", "kasse"),
    # EMX - E.Max Krone
    ("EMX", "0010", 1, 1, "fix", None),
    ("EMX", "0051", 1, 1, "pro_zahn", None),
    ("EMX", "0200", 1, 1, "fix", "kein_gb_privat"),
    ("EMX", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("EMX", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("EMX", "0120", 1, 1, "fix", None),
    ("EMX", "5001", 1, 1, "pro_zahn", None),
    ("EMX", "E001", 1, 1, "pro_zahn", None),
    ("EMX", "5601", 0, 1, "pro_zahn", None),
    ("EMX", "5602", 1, 1, "pro_zahn", None),
    ("EMX", "9022", 1, 1, "fix", None),
    ("EMX", "9025", 1, 2, "fix", None),
    ("EMX", "9027", 1, 1, "pro_zahn", None),
    ("EMX", "8000", 1, 1, "fix", "privat"),
    ("EMX", "9330", 1, 1, "fix", "kasse"),
    # VEN - Veneer
    ("VEN", "0010", 1, 1, "fix", None),
    ("VEN", "0051", 1, 1, "pro_zahn", None),
    ("VEN", "0200", 1, 1, "fix", "kein_gb_privat"),
    ("VEN", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("VEN", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("VEN", "0120", 1, 1, "fix", None),
    ("VEN", "5001", 1, 1, "pro_zahn", None),
    ("VEN", "E001", 1, 1, "pro_zahn", None),
    ("VEN", "E060", 1, 1, "pro_zahn", None),
    ("VEN", "5601", 0, 1, "pro_zahn", None),
    ("VEN", "5602", 1, 1, "pro_zahn", None),
    ("VEN", "9022", 0, 1, "fix", None),
    ("VEN", "9025", 0, 2, "fix", None),
    ("VEN", "9027", 0, 1, "pro_zahn", None),
    ("VEN", "8000", 1, 1, "fix", "privat"),
    ("VEN", "9330", 1, 1, "fix", "kasse"),
    # INL - Inlay
    ("INL", "0010", 1, 1, "fix", None),
    ("INL", "0051", 1, 1, "pro_zahn", None),
    ("INL", "0200", 1, 1, "fix", "kein_gb_privat"),
    ("INL", "0201", 1, 1, "fix", "gesichtsbogen"),
    ("INL", "0202", 1, 1, "fix", "gesichtsbogen"),
    ("INL", "0120", 1, 1, "fix", None),
    ("INL", "5200", 1, 1, "pro_zahn", None),
    ("INL", "E001", 1, 1, "pro_zahn", None),
    ("INL", "E060", 1, 1, "pro_zahn", None),
    ("INL", "5602", 1, 1, "pro_zahn", None),
    ("INL", "9022", 1, 1, "fix", None),
    ("INL", "9025", 1, 2, "fix", None),
    ("INL", "9027", 1, 1, "pro_zahn", None),
    ("INL", "8000", 1, 1, "fix", "privat"),
    ("INL", "9330", 1, 1, "fix", "kasse"),
    # LZP - Langzeitprovisorium
    ("LZP", "0010", 1, 1, "fix", None),
    ("LZP", "0120", 1, 1, "fix", None),
    ("LZP", "0805", 1, 1, "pro_zahn", None),
    ("LZP", "5602", 1, 1, "pro_zahn", None),
    ("LZP", "9022", 0, 1, "fix", None),
    ("LZP", "9025", 0, 2, "fix", None),
    ("LZP", "8000", 1, 1, "fix", "privat"),
    ("LZP", "9330", 1, 1, "fix", "kasse"),
    # MOCK - Mock-Up
    ("MOCK", "0001", 1, 1, "fix", None),
    ("MOCK", "0600", 1, 1, "pro_zahn", None),
    ("MOCK", "0611", 1, 1, "fix", None),
    ("MOCK", "0501", 0, 1, "fix", None),
    ("MOCK", "9022", 0, 1, "fix", None),
    ("MOCK", "8000", 1, 1, "fix", "privat"),
    ("MOCK", "9330", 1, 1, "fix", "kasse"),
    # WAX - Wax-Up
    ("WAX", "0001", 1, 1, "fix", None),
    ("WAX", "0600", 1, 1, "pro_zahn", None),
    ("WAX", "9025", 1, 1, "fix", None),
    ("WAX", "0501", 0, 1, "fix", None),
    ("WAX", "0611", 0, 1, "fix", None),
    ("WAX", "9022", 0, 1, "fix", None),
    ("WAX", "8000", 1, 1, "fix", "privat"),
    ("WAX", "9330", 1, 1, "fix", "kasse"),
    ("WAX", "9100", 0, 1, "fix", None),
    # GB - Gesichtsbogen
    ("GB", "0201", 1, 1, "fix", None),
    ("GB", "0202", 1, 1, "fix", None),
    ("GB", "9025", 1, 2, "fix", None),
    ("GB", "8000", 1, 1, "fix", "privat"),
    ("GB", "9330", 1, 1, "fix", "kasse"),
    # SMIL - Smile Design
    ("SMIL", "0001", 1, 1, "fix", None),
    ("SMIL", "0600", 1, 1, "pro_zahn", None),
    ("SMIL", "0804", 1, 1, "fix", None),
    ("SMIL", "0611", 0, 1, "fix", None),
    ("SMIL", "0501", 0, 1, "fix", None),
    ("SMIL", "9022", 0, 1, "fix", None),
    ("SMIL", "8000", 1, 1, "fix", "privat"),
    ("SMIL", "9330", 1, 1, "fix", "kasse"),
    # MKON - Münchner Konzept
    ("MKON", "0001", 1, 1, "fix", None),
    ("MKON", "0850", 1, 1, "fix", None),
    ("MKON", "020", 1, 1, "fix", None),
    ("MKON", "0250", 1, 1, "fix", None),
    ("MKON", "9022", 0, 1, "fix", None),
    ("MKON", "9025", 0, 2, "fix", None),
    ("MKON", "8000", 1, 1, "fix", "privat"),
    ("MKON", "9330", 1, 1, "fix", "kasse"),
    ("MKON", "9100", 0, 1, "fix", None),
    # MINI - Miniplastschiene
    ("MINI", "0857", 1, 1, "fix", None),
    ("MINI", "0010", 1, 1, "fix", None),
    ("MINI", "0120", 1, 1, "fix", None),
    ("MINI", "8000", 1, 1, "fix", "privat"),
    ("MINI", "9330", 1, 1, "fix", "kasse"),
    # JIGS - Jig
    ("JIGS", "0858", 1, 1, "fix", None),
    ("JIGS", "0010", 1, 1, "fix", None),
    ("JIGS", "0120", 1, 1, "fix", None),
    ("JIGS", "8000", 1, 1, "fix", "privat"),
    ("JIGS", "9330", 1, 1, "fix", "kasse"),
]

PRAXEN = [
    ("Paul Seemann", "SEE"),
    ("Dr. Gabriele Schmidt", "GSC"),
    ("Dr. Lex", "LEX"),
    ("MVZ Phönixsee", "PHX"),
    ("Röder u. Kollegen", "ROE"),
    ("Dr. Neuffer", "NEU"),
    ("Dr. Wojahn", "WOJ"),
    ("Dr. Krauß", "KRA"),
    ("Das Hugo", "HUG"),
    ("Helm Dent", "HEL"),
    ("Zahnärzte am Königsplatz", "KOE"),
    ("Clinic Drohomyretska", "DRO"),
    ("Smile Atelier", "SMI"),
    ("Dr. Kersting", "KER"),
    ("Omar Gazaev", "GAZ"),
    ("Martmöller u. Kollegen", "MAR"),
    ("Dauner", "DAU"),
    ("Heuß", "HEU"),
    ("Papajewski", "PAP"),
    ("Pühler", "PUE"),
    ("Zahnheilkunde am Markt", "ZAH"),
    ("Schulz-Clauß-Lorenz", "SCL"),
]


# Database Context Manager
@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# Database Initialization
def init_db():
    if os.path.exists(DB_PATH):
        return

    with get_db() as conn:
        cursor = conn.cursor()

        # Create tables
        cursor.execute("""
            CREATE TABLE positionen (
                id INTEGER PRIMARY KEY,
                nummer TEXT UNIQUE NOT NULL,
                bezeichnung TEXT NOT NULL,
                einzelpreis REAL NOT NULL DEFAULT 0,
                kategorie TEXT NOT NULL CHECK(kategorie IN ('leistung','material')),
                mwst_satz REAL DEFAULT 7.0,
                aktiv BOOLEAN DEFAULT 1
            )
        """)

        cursor.execute("""
            CREATE TABLE kuerzel (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                bezeichnung TEXT NOT NULL,
                beschreibung TEXT,
                aktiv BOOLEAN DEFAULT 1
            )
        """)

        cursor.execute("""
            CREATE TABLE kuerzel_positionen (
                id INTEGER PRIMARY KEY,
                kuerzel_id INTEGER NOT NULL REFERENCES kuerzel(id),
                position_id INTEGER NOT NULL REFERENCES positionen(id),
                ist_pflicht BOOLEAN DEFAULT 1,
                standard_menge REAL DEFAULT 1.0,
                mengen_formel TEXT DEFAULT 'fix',
                bedingung TEXT,
                sortierung INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE praxen (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                ist_kasse_default BOOLEAN DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE kva (
                id INTEGER PRIMARY KEY,
                praxis_id INTEGER REFERENCES praxen(id),
                patient_name TEXT,
                ist_kasse BOOLEAN DEFAULT 0,
                hat_gesichtsbogen BOOLEAN DEFAULT 0,
                arbeitsart TEXT,
                erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'entwurf'
            )
        """)

        cursor.execute("""
            CREATE TABLE kva_positionen (
                id INTEGER PRIMARY KEY,
                kva_id INTEGER NOT NULL REFERENCES kva(id),
                position_nummer TEXT NOT NULL,
                position_bezeichnung TEXT NOT NULL,
                menge REAL DEFAULT 1.0,
                einzelpreis REAL DEFAULT 0,
                kategorie TEXT DEFAULT 'leistung',
                ist_korrigiert BOOLEAN DEFAULT 0,
                sortierung INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE korrekturen (
                id INTEGER PRIMARY KEY,
                kuerzel_code TEXT NOT NULL,
                position_nummer TEXT NOT NULL,
                aktion TEXT NOT NULL CHECK(aktion IN ('hinzugefuegt','entfernt','menge_geaendert')),
                neue_menge REAL,
                ist_kasse BOOLEAN,
                hat_gesichtsbogen BOOLEAN,
                praxis_code TEXT,
                erstellt_am DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed positionen
        for nummer, bezeichnung, einzelpreis, kategorie in POSITIONEN:
            cursor.execute(
                "INSERT INTO positionen (nummer, bezeichnung, einzelpreis, kategorie) VALUES (?, ?, ?, ?)",
                (nummer, bezeichnung, einzelpreis, kategorie),
            )

        # Seed kuerzel
        for code, bezeichnung, beschreibung in KUERZEL:
            cursor.execute(
                "INSERT INTO kuerzel (code, bezeichnung, beschreibung) VALUES (?, ?, ?)",
                (code, bezeichnung, beschreibung),
            )

        # Seed kuerzel_positionen
        for kuerzel_code, pos_nummer, ist_pflicht, menge, mengen_formel, bedingung in KUERZEL_POS:
            cursor.execute(
                "SELECT id FROM kuerzel WHERE code = ?",
                (kuerzel_code,),
            )
            kuerzel_id = cursor.fetchone()[0]

            cursor.execute(
                "SELECT id FROM positionen WHERE nummer = ?",
                (pos_nummer,),
            )
            pos_row = cursor.fetchone()
            if pos_row:
                position_id = pos_row[0]
                cursor.execute(
                    "INSERT INTO kuerzel_positionen (kuerzel_id, position_id, ist_pflicht, standard_menge, mengen_formel, bedingung) VALUES (?, ?, ?, ?, ?, ?)",
                    (kuerzel_id, position_id, ist_pflicht, menge, mengen_formel, bedingung),
                )

        # Seed praxen
        for name, code in PRAXEN:
            cursor.execute(
                "INSERT INTO praxen (name, code) VALUES (?, ?)",
                (name, code),
            )

        conn.commit()


# Pydantic Models
class PosicionItem(BaseModel):
    position_nummer: str
    position_bezeichnung: str
    menge: float
    einzelpreis: float
    kategorie: str


class KVACreate(BaseModel):
    praxis_id: Optional[int] = None
    patient_name: Optional[str] = None
    ist_kasse: bool = False
    hat_gesichtsbogen: bool = False
    arbeitsart: Optional[str] = None
    positionen: List[PosicionItem] = []


class KVAUpdate(BaseModel):
    patient_name: Optional[str] = None
    status: Optional[str] = None


class ResolveRequest(BaseModel):
    kuerzel: str
    zaehne: int = 1
    kasse: bool = False
    gesichtsbogen: bool = False


class KorrektureRequest(BaseModel):
    kva_id: Optional[int] = None
    kuerzel_code: str
    position_nummer: str
    aktion: str
    neue_menge: Optional[float] = None
    ist_kasse: bool = False
    hat_gesichtsbogen: bool = False
    praxis_code: Optional[str] = None


# Lifespan event handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    yield
    # Shutdown (if needed)


# FastAPI Application
app = FastAPI(title="Dental OS API", version="1.0.0", lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routes


@app.get("/")
async def root():
    if os.path.exists(HTML_FILE):
        return FileResponse(HTML_FILE)
    return {"message": "Dental OS API"}


@app.get("/api/praxen")
def list_praxen():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, code FROM praxen ORDER BY name")
        rows = cursor.fetchall()
        return [{"id": r[0], "name": r[1], "code": r[2]} for r in rows]


@app.get("/api/kuerzel")
def list_kuerzel():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT code, bezeichnung, beschreibung FROM kuerzel WHERE aktiv = 1 ORDER BY code")
        rows = cursor.fetchall()
        return [{"code": r[0], "bezeichnung": r[1], "beschreibung": r[2]} for r in rows]


@app.get("/api/positionen")
def list_positionen():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT nummer, bezeichnung, einzelpreis, kategorie FROM positionen WHERE aktiv = 1 ORDER BY nummer"
        )
        rows = cursor.fetchall()
        return [
            {
                "nummer": r[0],
                "bezeichnung": r[1],
                "einzelpreis": r[2],
                "kategorie": r[3],
            }
            for r in rows
        ]


@app.post("/api/resolve")
def resolve_kuerzel(req: ResolveRequest):
    with get_db() as conn:
        cursor = conn.cursor()

        # Handle special case: SCH + kasse -> SCHK, SCHS + kasse -> SCHSK
        kuerzel_code = req.kuerzel
        if req.kasse:
            if req.kuerzel == "SCH":
                kuerzel_code = "SCHK"
            elif req.kuerzel == "SCHS":
                kuerzel_code = "SCHSK"

        # Get kuerzel
        cursor.execute("SELECT id FROM kuerzel WHERE code = ?", (kuerzel_code,))
        kuerzel_row = cursor.fetchone()
        if not kuerzel_row:
            raise HTTPException(status_code=404, detail="Kuerzel not found")

        kuerzel_id = kuerzel_row[0]

        # Get kuerzel_positionen with ist_pflicht=1
        cursor.execute(
            """
            SELECT kp.id, p.nummer, p.bezeichnung, p.einzelpreis, p.kategorie,
                   kp.standard_menge, kp.mengen_formel, kp.bedingung
            FROM kuerzel_positionen kp
            JOIN positionen p ON kp.position_id = p.id
            WHERE kp.kuerzel_id = ? AND kp.ist_pflicht = 1
            ORDER BY p.nummer
            """,
            (kuerzel_id,),
        )
        rows = cursor.fetchall()

        result = []
        for row in rows:
            bedingung = row[7]

            # Filter by bedingung
            if bedingung == "gesichtsbogen" and not req.gesichtsbogen:
                continue
            if bedingung == "kein_gesichtsbogen" and req.gesichtsbogen:
                continue
            if bedingung == "privat" and req.kasse:
                continue
            if bedingung == "kasse" and not req.kasse:
                continue
            if bedingung == "kein_gb_privat" and (req.gesichtsbogen or req.kasse):
                continue

            # Calculate menge
            menge = row[5]  # standard_menge
            mengen_formel = row[6]
            if mengen_formel == "pro_zahn":
                menge = req.zaehne * menge
            elif mengen_formel == "pro_glied":
                menge = req.zaehne * menge

            result.append(
                {
                    "position_nummer": row[1],
                    "position_bezeichnung": row[2],
                    "einzelpreis": row[3],
                    "kategorie": row[4],
                    "menge": menge,
                }
            )

        return result


@app.post("/api/kva")
def create_kva(req: KVACreate):
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO kva (praxis_id, patient_name, ist_kasse, hat_gesichtsbogen, arbeitsart, status)
            VALUES (?, ?, ?, ?, ?, 'entwurf')
            """,
            (
                req.praxis_id,
                req.patient_name,
                req.ist_kasse,
                req.hat_gesichtsbogen,
                req.arbeitsart,
            ),
        )
        kva_id = cursor.lastrowid

        # Insert positionen
        for idx, pos in enumerate(req.positionen):
            cursor.execute(
                """
                INSERT INTO kva_positionen
                (kva_id, position_nummer, position_bezeichnung, menge, einzelpreis, kategorie, sortierung)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kva_id,
                    pos.position_nummer,
                    pos.position_bezeichnung,
                    pos.menge,
                    pos.einzelpreis,
                    pos.kategorie,
                    idx,
                ),
            )

        conn.commit()
        return {"id": kva_id, "status": "created"}


@app.get("/api/kva")
def list_kva(limit: int = Query(100, ge=1, le=1000)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT k.id, k.patient_name, k.ist_kasse, k.hat_gesichtsbogen,
                   k.arbeitsart, k.erstellt_am, k.status, p.name
            FROM kva k
            LEFT JOIN praxen p ON k.praxis_id = p.id
            ORDER BY k.erstellt_am DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "patient_name": r[1],
                "ist_kasse": bool(r[2]),
                "hat_gesichtsbogen": bool(r[3]),
                "arbeitsart": r[4],
                "erstellt_am": r[5],
                "status": r[6],
                "praxis_name": r[7],
            }
            for r in rows
        ]


@app.get("/api/kva/{kva_id}")
def get_kva(kva_id: int):
    with get_db() as conn:
        cursor = conn.cursor()

        # Get KVA header
        cursor.execute(
            """
            SELECT k.id, k.patient_name, k.ist_kasse, k.hat_gesichtsbogen,
                   k.arbeitsart, k.erstellt_am, k.status, p.name, k.praxis_id
            FROM kva k
            LEFT JOIN praxen p ON k.praxis_id = p.id
            WHERE k.id = ?
            """,
            (kva_id,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="KVA not found")

        # Get KVA positionen
        cursor.execute(
            """
            SELECT position_nummer, position_bezeichnung, menge, einzelpreis, kategorie, ist_korrigiert
            FROM kva_positionen
            WHERE kva_id = ?
            ORDER BY sortierung
            """,
            (kva_id,),
        )
        pos_rows = cursor.fetchall()

        return {
            "id": row[0],
            "patient_name": row[1],
            "ist_kasse": bool(row[2]),
            "hat_gesichtsbogen": bool(row[3]),
            "arbeitsart": row[4],
            "erstellt_am": row[5],
            "status": row[6],
            "praxis_name": row[7],
            "praxis_id": row[8],
            "positionen": [
                {
                    "position_nummer": pr[0],
                    "position_bezeichnung": pr[1],
                    "menge": pr[2],
                    "einzelpreis": pr[3],
                    "kategorie": pr[4],
                    "ist_korrigiert": bool(pr[5]),
                }
                for pr in pos_rows
            ],
        }


@app.post("/api/korrektur")
def save_korrektur(req: KorrektureRequest):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO korrekturen
            (kuerzel_code, position_nummer, aktion, neue_menge, ist_kasse, hat_gesichtsbogen, praxis_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.kuerzel_code,
                req.position_nummer,
                req.aktion,
                req.neue_menge,
                req.ist_kasse,
                req.hat_gesichtsbogen,
                req.praxis_code,
            ),
        )
        conn.commit()
        return {"status": "saved", "id": cursor.lastrowid}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
