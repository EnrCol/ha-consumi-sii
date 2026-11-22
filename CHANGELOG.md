# Changelog

## 0.3.0b1 — 2026-11-22

Prima versione del fork `EnrCol/ha-consumi-sii`, da `Manu-Nat/portale-consumi-ha` 0.1.2.

**Incompatibile con l'originale:** nuovo dominio `consumi_sii`, nuovi `unique_id` e
nomi delle entità. Va configurata da zero.

- Nome: "Consumi luce e gas (SII)"; entità con `has_entity_name` e traduzioni it/en.
- Un dispositivo per ogni POD/PDR (prima i punti venivano sommati in un solo sensore).
- Nuovi sensori: anno precedente, ultimo mese disponibile; i 12 mensili restano,
  disattivati di default.
- Statistiche esterne mensili per la dashboard Energia, con somma che non torna
  indietro se il portale smette di pubblicare i mesi più vecchi.
- Sessione scaduta riconosciuta: il portale risponde `503 API_INVALID_RESPONSE`, che
  l'originale trattava come errore di rete senza mai chiedere un cookie nuovo.
- I `Set-Cookie` del portale vengono uniti e salvati (prima venivano scartati).
- Casa senza gas: nessun errore se manca l'elenco PDR.
- Diagnostica senza segreti, test unitari, CI con hassfest e validazione HACS.
