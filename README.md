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
- Per ogni punto: **consumo anno corrente**, **anno precedente**, **ultimo mese
  disponibile**, più 12 sensori mensili (disattivati di default).
- Importa tutta la storia mensile come **statistiche esterne** (`consumi_sii:luce_<pod>`,
  `consumi_sii:gas_<pdr>`), selezionabili nella **dashboard Energia** come consumo
  dalla rete o come gas.
- Unisce le misure di contratti e gestori diversi sullo stesso punto, preferendo la
  lettura più recente e, a parità di data, la rettifica.
- Salva i cookie rinnovati dal portale, così la sessione dura il più possibile.
- Riconosce la sessione scaduta e avvia la **riautenticazione** di Home Assistant.
- Diagnostica scaricabile senza cookie né codici completi.

L'integrazione esegue solo richieste di lettura (GET).

## Installazione

Marketplace/HACS → repository personalizzato `https://github.com/EnrCol/ha-consumi-sii`,
categoria **Integrazione**; installa e riavvia Home Assistant. In alternativa copia
`custom_components/consumi_sii` nella cartella `custom_components`.

## Configurazione

1. Accedi a [consumienergia.it/portaleConsumi](https://www.consumienergia.it/portaleConsumi/)
   con SPID o CIE, fino a vedere le forniture.
2. Strumenti sviluppatore (**F12**) → **Rete** → ricarica (**F5**) → filtro `Service.json`.
3. Apri una richiesta (es. `fornitureElettricheService.json`) → **Intestazioni richiesta**
   → copia l'intero valore di **`Cookie`** (va bene anche la riga `Cookie: …`).
4. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → Consumi luce e gas (SII)**
   e incolla il valore.

> ⚠️ Non inserire mai credenziali SPID o CIE. Il cookie vale come una password: resta
> nella configurazione e nei backup di Home Assistant, non pubblicarlo.

**Perché non c'è un accesso assistito come in [ha-contarina](https://github.com/EnrCol/ha-contarina)?**
Il cookie di sessione del portale (`JSESSIONID`) è `HttpOnly`: un preferito del browser
non può leggerlo, quindi non si può trasferire ad Home Assistant con un clic. Un'alternativa
allo studio è un preferito che legge i dati dalla pagina autenticata e li invia ad Home
Assistant senza trasferire alcuna credenziale.

Quando la sessione scade, il portale risponde `503 API_INVALID_RESPONSE` (non 401).
L'integrazione controlla che la home pubblica del portale sia raggiungibile: se lo è,
chiede un cookie nuovo; altrimenti lo tratta come disservizio e riprova più tardi.

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
