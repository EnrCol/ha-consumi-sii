<p align="center">
  <img src="images/logo.png" alt="Consumi luce e gas (SII)" width="140">
</p>

<h1 align="center">Consumi luce e gas (SII)</h1>

Integrazione **non ufficiale** per Home Assistant che legge i consumi mensili di
**luce e gas** dal [Portale Consumi](https://www.consumienergia.it/portaleConsumi/)
del SII (Sistema Informativo Integrato, Acquirente Unico): le misure ufficiali che
i distributori trasmettono al registro nazionale, anche per i periodi di fornitori
precedenti.

> Fork di [Manu-Nat/portale-consumi-ha](https://github.com/Manu-Nat/portale-consumi-ha)
> (MIT). Dominio, nomi ed entità sono cambiati: **non è un aggiornamento in place**
> dell'integrazione originale. Vedi [CHANGELOG](CHANGELOG.md).

## Cosa fa

- Trova i **POD** (luce) e i **PDR** (gas) con un contratto attivo e crea un
  **dispositivo per ciascun punto**.
- Per ogni punto, tutti attivi: **Anno corrente**, **Anno precedente**, **Ultimo mese**,
  un sensore per mese (**Gennaio** … **Dicembre**, con l'ultimo anno disponibile per
  quel mese nell'attributo `anno`) e il diagnostico **Ultimo aggiornamento**.
- Importa tutta la storia mensile come **statistiche esterne** (`consumi_sii:luce_<pod>`,
  `consumi_sii:gas_<pdr>`), selezionabili nella **dashboard Energia** come consumo
  dalla rete o come gas.
- Unisce le misure di contratti e gestori diversi sullo stesso punto, preferendo la
  lettura più recente e, a parità di data, la rettifica.
- **Collegamento dal browser:** entri nel portale con SPID/CIE e un preferito invia i consumi ad Home Assistant. Nessun cookie, nessuna credenziale salvata, nulla che scada.
- Modalità avanzata con cookie: sessione tenuta viva ogni 10 minuti, riautenticazione quando scade.
- Diagnostica scaricabile senza cookie né codici completi.

L'integrazione esegue solo richieste di lettura (GET).

## Installazione

Marketplace/HACS → repository personalizzato `https://github.com/EnrCol/ha-consumi-sii`,
categoria **Integrazione**; installa e riavvia Home Assistant. In alternativa copia
`custom_components/consumi_sii` nella cartella `custom_components`.

## Configurazione (2 minuti, una volta sola)

1. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Consumi luce e gas (SII)**
   → **Collega dal browser (consigliato)**.
2. Si apre una pagina con il pulsante **Invia consumi a Home Assistant**: trascinalo nella
   barra dei preferiti. Sul telefono usa **Copia codice del preferito** e segui le istruzioni.
3. Premi **Apri il Portale Consumi** ed entra con **SPID o CIE**, come sempre.
4. Quando vedi le tue forniture, clicca il preferito. Legge i consumi, torna su Home Assistant
   e la configurazione si completa da sola.

**Per aggiornare i dati** entra nel portale e clicca di nuovo il preferito: niente da fare in
Home Assistant. Il portale pubblica i consumi una volta al mese, quindi basta un clic al mese.

Niente strumenti sviluppatore, niente cookie da copiare, nessuna credenziale salvata: non c'è
nulla che scada.

### Come funziona

Il cookie di sessione del portale (`JSESSIONID`) è `HttpOnly`: un preferito non può leggerlo,
quindi non si può trasferire come il token di [ha-contarina](https://github.com/EnrCol/ha-contarina).
Il preferito però gira dentro la pagina del portale, dove il browser allega da sé la sessione:
legge i quattro servizi JSON (forniture e consumi) e invia **i dati** ad Home Assistant.

- I dati viaggiano nel frammento dell'URL (la parte dopo `#`, mai inviata in rete) verso una
  pagina di Home Assistant, che li consegna con una richiesta dalla stessa origine.
- Il preferito contiene l'indirizzo di Home Assistant e una **chiave di invio** casuale; Home
  Assistant ne conserva solo l'hash. La chiave permette soltanto di sostituire i consumi di
  questa integrazione: non legge nulla. Non condividere il preferito; per cambiare chiave (o se
  cambia l'indirizzo di Home Assistant) usa **Riconfigura**.
- Il telefono deve poter raggiungere l'indirizzo di Home Assistant usato nel preferito.

### Modalità avanzata: cookie

Chi vuole aggiornamenti automatici può scegliere **Incolla il cookie (avanzato)**: dopo
l'accesso al portale, strumenti sviluppatore (**F12**) → **Rete** → una richiesta
`*Service.json` → **Intestazioni richiesta** → valore di **`Cookie`**. Come il rinnovo del token
in ha-contarina, Home Assistant fa una richiesta leggera **ogni 10 minuti** per tenere viva la
sessione e salva i cookie rinnovati dal portale. Se la sessione scade, il portale risponde
`503 API_INVALID_RESPONSE`: se la home pubblica è raggiungibile, Home Assistant chiede un nuovo
collegamento (anche passando al preferito); altrimenti lo tratta come disservizio.

> ⚠️ Non inserire mai credenziali SPID o CIE. Il cookie vale come una password.

## Dashboard Energia

Le statistiche contengono una riga per mese, posta alla mezzanotte del primo giorno.
Nelle viste **mese** e **anno** i totali sono corretti; nella vista giorno il consumo del
mese appare tutto il giorno 1. I dati del portale arrivano con settimane o mesi di ritardo.

Il gas è pubblicato in **Smc** e mostrato come m³ (differenza di pochi punti percentuali).

## Limiti

- Progetto non ufficiale, non affiliato al SII, ad Acquirente Unico o ai fornitori.
- Le API usate non sono documentate e possono cambiare senza preavviso.
- Una sola configurazione per istanza (nessuna gestione delle deleghe).

Licenza [MIT](LICENSE).
