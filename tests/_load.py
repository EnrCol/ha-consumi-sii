"""Carica i moduli puri dell'integrazione senza eseguire __init__ (che usa HA)."""
import importlib
import sys
import types
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "consumi_sii"


def load(name: str):
    if "consumi_sii" not in sys.modules:
        pkg = types.ModuleType("consumi_sii")
        pkg.__path__ = [str(PKG_DIR)]
        sys.modules["consumi_sii"] = pkg
    return importlib.import_module(f"consumi_sii.{name}")
