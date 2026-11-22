# Changelog

## 0.4.0b8 — 2026-11-22

- Pagina permanente **Aggiorna i consumi**, aperta dal link «Apri» del dispositivo: pulsante per il
  portale e preferito sempre disponibile, senza rifare la configurazione.
- Avviso in **Riparazioni** quando gli ultimi dati hanno più di 35 giorni, con il link alla pagina;
  sparisce al prossimo invio.
- Il preferito già salvato resta valido.

## 0.4.0b7 — 2026-11-22

- I sensori mensili mostrano l'anno nel nome: «Dicembre 2025», «Novembre 2026». Il nome segue i
  dati e cambia da solo quando arriva il mese dell'anno nuovo.

## 0.4.0b6 — 2026-11-22

- Un solo dispositivo per POD/PDR: «Ultimo aggiornamento» passa sul dispositivo del punto e il
  dispositivo di servizio «Consumi luce e gas (SII)» viene rimosso in automatico.
- Nomi più brevi: «Anno corrente», «Anno precedente», «Ultimo mese», «Gennaio» … «Dicembre»,
  con una traduzione per mese invece di un nome con segnaposto. (Un sensore che mostra solo il nome
  del dispositivo ha l'opzione «Usa il nome del dispositivo» attiva nelle sue impostazioni.)
- Tutti i sensori sono attivi di default; i mensili disattivati dalle versioni precedenti si
  riattivano (quelli spenti a mano restano spenti).
- Ogni sensore mensile mostra l'ultimo valore disponibile per quel mese (es. dicembre dell'anno
  scorso finché non c'è quello di quest'anno), con l'anno nell'attributo `anno`.
  Gli entity_id già esistenti non cambiano.

## 0.4.0b5 — 2026-11-22

- La ricezione leggeva solo la parte del corpo già arrivata: con invii di decine di KB i dati
  risultavano troncati e HA rispondeva "Richiesta non valida". Ora legge il corpo fino alla fine.
- Gli invii scartati sono descritti nel log; la pagina di ricezione decodifica il frammento.

## 0.4.0b3 — 2026-11-22

- Il preferito invia solo i campi delle misure mensili. Prima inviava le risposte intere, comprese
  le curve orarie e quartorarie, e su utenze con tanti dati HA le scartava con "Richiesta non valida".
- Un invio troppo grande ha ora un messaggio suo; gli invii scartati finiscono nel log di HA.

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
