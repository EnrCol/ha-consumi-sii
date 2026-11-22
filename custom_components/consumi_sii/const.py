"""Costanti dell'integrazione Consumi luce e gas (SII)."""

DOMAIN = "consumi_sii"
NAME = "Consumi luce e gas (SII)"

BASE_URL = "https://www.consumienergia.it/portaleConsumi/legacyapi/rs/it/"

API_FORNITURE_ELETTRICHE = "fornitureElettricheService.json"
API_FORNITURE_GAS = "fornitureGasService.json"
API_CONSUMI_ELETTRICI = "consumiElettricoService.json"
API_CONSUMI_GAS = "consumiGasService.json"

CONF_COOKIE_HEADER = "cookie_header"
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"

DEFAULT_SCAN_INTERVAL_HOURS = 168  # una settimana
MIN_SCAN_INTERVAL_HOURS = 24
MAX_SCAN_INTERVAL_HOURS = 720
