# Changelog

## 0.4.0b2 — 2026-11-22

- Il portale risponde `result: ""` quando non ci sono dati (es. nessuna fornitura gas): il preferito
  si fermava con "JSON Parse error". Ora vale come "nessun dato"; gli errori indicano il servizio.

## 0.4.0b1 — 2026-11-22

- **Collegamento dal browser (consigliato):** un preferito eseguito sulla pagina autenticata del
  portale legge forniture e consumi e li invia ad Home Assistant. Niente cookie da copiare, nessuna
  credenziale salvata, nessuna sessione da rinnovare; per aggiornare basta riusarlo dal portale.
  Chiave di invio per installazione (in HA solo l'hash), dati nel frammento dell'URL, consegna
  same-origin, blocco dopo tentativi errati.
- Modalità cookie diventata «avanzata»: richiesta ogni 10 minuti per tenere viva la sessione;
  alla scadenza la riautenticazione propone anche il preferito.
- Riconfigura: nuovo preferito (cambio chiave o indirizzo) o passaggio di modalità.
- Test del preferito in Node con un finto portale, decodificati poi dal codice Python.

## 0.3.0b1 — 2026-11-22

- Nuovo logo e icona (fulmine e fiamma), generati da `tools/draw_logo.py`.

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
