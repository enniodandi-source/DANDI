# Email Consolidation Pilot 📧

Script di automazione per il consolidamento delle caselle email dei dipendenti in un sistema di ticketing centralizzato.

## Panoramica

Questo script automatizza il processo di:
1. **Lettura periodica** delle caselle email di account di test (IMAP)
2. **Identificazione** dei messaggi non ancora elaborati
3. **Inoltro** degli email al sistema di ticketing centrale (SMTP)
4. **Tracciamento** degli ID dei messaggi per evitare duplicati

## Architettura e Flusso

```
┌─────────────────────────────────────────────────────────────────┐
│                    EMAIL CONSOLIDATION FLOW                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Account Test 1    Account Test 2    Account Test 3             │
│  (IMAP 993)        (IMAP 993)        (IMAP 993)                 │
│        │                 │                 │                     │
│        └─────────────────┴─────────────────┘                     │
│                          │                                       │
│        ┌─────────────────▼─────────────────┐                    │
│        │  Email Consolidator Script        │                    │
│        │  - Legge da IMAP                  │                    │
│        │  - Calcola hash messaggi          │                    │
│        │  - Controlla state.json           │                    │
│        │  - Invia via SMTP                 │                    │
│        └─────────────────┬─────────────────┘                    │
│                          │                                       │
│                    [state.json]◄───────────┐                    │
│                   (tracciamento IDs)       │                    │
│                                            │                    │
│                                    ┌───────┴────────┐           │
│                                    │                │           │
│                            (SMTP 587 con STARTTLS)│           │
│                                    │                │           │
│                            System di Ticketing      │           │
│                            (indirizzo centrale)     │           │
│                                                      │           │
└─────────────────────────────────────────────────────┘
```

## Funzionamento Dettagliato

### 1. **Inizializzazione**
```python
consolidator = EmailConsolidator()
```

Il consolidatore carica due file:
- **`config.json`**: Contiene le credenziali degli account di test e del sistema centrale
- **`state.json`**: Memoria persistente degli ID dei messaggi già processati

### 2. **Lettura da IMAP**
```python
messages = self._fetch_emails_from_imap(email, password, imap_host, imap_port)
```

Per ogni account di test:
- Si connette al server IMAP con SSL sulla porta 993
- Seleziona la cartella INBOX
- Recupera tutti i messaggi
- **Per ogni messaggio calcola un hash SHA256** (impronta univoca)
- Confronta l'hash con `state.json` per capire se è già stato processato
- Se nuovo, lo aggiunge alla lista da elaborare

**Perché l'hash?** Se la stessa email arriva 2 volte (per errore di connessione, riavvio dello script, etc.), lo script riconoscerà che è la stessa e non la processerà di nuovo.

### 3. **Inoltro al Sistema Centrale**
```python
success = self._forward_to_central_system(raw_message, source_email, central_email, ...)
```

Per ogni messaggio nuovo:
- **Parsa il messaggio originale** (From, Subject, Body, Date)
- **Crea un nuovo messaggio di inoltro** con:
  - Header personalizzati per tracciamento (`X-Forwarded-From`, `X-Consolidation-Date`)
  - Subject modificato con tag `[CONSOLIDATED from email@originale]`
  - Corpo che include i dettagli originali
- Si connette al server SMTP con STARTTLS sulla porta 587
- Si autentica con le credenziali del sistema di ticketing
- **Invia il messaggio**

### 4. **Tracciamento dello Stato**
```python
self._mark_message_processed(message_hash)
self._save_state()
```

Una volta che il messaggio è stato inoltrato con successo:
- L'hash del messaggio viene aggiunto alla lista in memoria
- Lo `state.json` viene salvato su disco

**Questo garantisce che:** Se lo script si riavvia, non riprocessa i vecchi messaggi.

## Setup

### Prerequisiti
- Python 3.7+
- Accesso ai server IMAP dei test account
- Accesso al server SMTP del sistema di ticketing

### Installazione

1. **Clona il repo e naviga alla cartella:**
   ```bash
   cd /path/to/project
   ```

2. **Copia il file di configurazione di esempio:**
   ```bash
   cp config.json.example config.json
   ```

3. **Modifica `config.json` con le credenziali reali:**
   ```json
   {
     "central_system": {
       "email": "ticketing@company.com",
       "smtp_host": "smtp.company.com",
       "smtp_port": 587,
       "smtp_user": "ticketing@company.com",
       "smtp_password": "your_password"
     },
     "accounts": [
       {
         "email": "test1@provider.com",
         "password": "password1",
         "imap_host": "imap.provider.com",
         "imap_port": 993
       }
     ]
   }
   ```

4. **Esegui lo script:**
   ```bash
   python email_consolidator.py
   ```

## File di Configurazione (config.json)

### Sezione `central_system`
Credenziali del sistema di ticketing centrale:
- `email`: indirizzo email del destinatario centrale
- `smtp_host`: server SMTP (es. `smtp.company.com`)
- `smtp_port`: porta SMTP (default 587 per STARTTLS)
- `smtp_user`: username per autenticazione SMTP
- `smtp_password`: password per autenticazione SMTP

### Sezione `accounts` (array)
Lista degli account di test da consolidare. Ogni account ha:
- `email`: indirizzo email dell'account
- `password`: password dell'account
- `imap_host`: server IMAP (es. `imap.gmail.com`, `imap.provider.com`)
- `imap_port`: porta IMAP (default 993 per SSL)

## File di Stato (state.json)

Contiene una lista di hash SHA256 di tutti i messaggi già processati:

```json
{
  "processed_message_ids": [
    "a3f2e1d4b5c6f7e8d9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d",
    "f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9",
    ...
  ]
}
```

**Nota:** Questo file viene aggiornato ogni volta che lo script completa un ciclo con successo.

## Log

Lo script genera log in due posti:
1. **Console**: output in tempo reale
2. **File**: `email_consolidator.log`

Esempio di output:
```
2026-07-13 14:25:30,123 - INFO - ======================================================================
2026-07-13 14:25:30,123 - INFO - INIZIO CICLO DI CONSOLIDAMENTO
2026-07-13 14:25:30,123 - INFO - ======================================================================
2026-07-13 14:25:30,456 - INFO - Configurazione caricata: 3 account trovati
2026-07-13 14:25:31,789 - INFO - Elaborazione account: test1@provider.com
2026-07-13 14:25:32,012 - INFO - Connessione a test1@provider.com su imap.provider.com:993
2026-07-13 14:25:33,456 - INFO - Trovati 5 messaggi in test1@provider.com
2026-07-13 14:25:34,123 - INFO - Messaggio inoltrato da test1@provider.com a ticketing@company.com
...
2026-07-13 14:26:45,678 - INFO - CICLO COMPLETATO: 12 messaggi inoltrati, 0 errori
```

## Come Adattarlo al Tuo Caso

### 1. **Cambiare i Provider Email**
Se i tuoi account usano provider diversi, modifica `config.json`:
- **Gmail**: `imap_host: "imap.gmail.com"`
- **Outlook**: `imap_host: "outlook.office365.com"`
- **Provider generico**: consulta la loro documentazione IMAP

### 2. **Filtrare Email Specifiche**
Attualmente lo script legge TUTTI i messaggi. Per leggere solo email non lette, modifica questa riga in `_fetch_emails_from_imap()`:

```python
# Da:
status, message_ids = imap.search(None, 'ALL')

# A (solo email non lette):
status, message_ids = imap.search(None, 'UNSEEN')

# Oppure per email da una certa data in poi:
status, message_ids = imap.search(None, 'SINCE "01-Jan-2026"')
```

### 3. **Modificare il Formato del Messaggio Inoltrato**
Cambia la variabile `body` in `_forward_to_central_system()` per personalizzare il formato dell'email inoltrata.

### 4. **Aggiungere Logging più Dettagliato**
Modifica il livello di logging:
```python
logging.basicConfig(
    level=logging.DEBUG  # Da INFO a DEBUG per più dettagli
)
```

### 5. **Eseguire in Loop Periodico**
Per eseguire lo script ogni ora, usa un cron job:
```bash
0 * * * * cd /path/to/project && python email_consolidator.py
```

Oppure ogni 30 minuti:
```bash
*/30 * * * * cd /path/to/project && python email_consolidator.py
```

## Gestione degli Errori

Lo script gestisce automaticamente:
- **Errori di connessione IMAP**: Registra l'errore e continua con il prossimo account
- **Errori di autenticazione SMTP**: Registra e salta quel messaggio
- **Errori di parsing**: Gestisce email malformate
- **Errori di connessione generale**: Tutto viene loggato

Consulta `email_consolidator.log` per i dettagli degli errori.

## Sicurezza

### ⚠️ Nota Importante
- **NON** committare il file `config.json` al repository (contiene password!)
- Usa un file `.gitignore` per escludere:
  ```
  config.json
  state.json
  *.log
  ```
- Considera di usare variabili d'ambiente o un vault per le password in produzione

### Miglioramenti Futuri per Produzione
- Usare autenticazione OAuth2 invece di password in chiaro
- Criptare il file di stato
- Implementare retry logic con backoff esponenziale
- Aggiungere supporto per template di email personalizzati
- Implementare un database per tracciamento più robusto (invece di JSON)

## Troubleshooting

### "FileNotFoundError: File configurazione non trovato"
Assicurati che `config.json` esista nella stessa cartella dello script:
```bash
cp config.json.example config.json
```

### "IMAP4 error: authentication failed"
Verifica che email e password siano corrette nel `config.json`. Alcuni provider richiedono password specifiche per app.

### "SMTP error: No suitable authentication method found"
Il server SMTP potrebbe non supportare STARTTLS. Contatta l'amministratore di sistema.

### Lo script non processa nessun messaggio
1. Verifica che ci siano effettivamente messaggi negli account (controlla manualmente)
2. Controlla il file `email_consolidator.log` per errori
3. Assicurati che i messaggi non siano già stati processati (cancella `state.json` per ricominciare da zero)

## Prossimi Passi

1. **Test localmente** con 2-3 account di test
2. **Monitora i log** per errori
3. **Verifica** che gli email arrivino correttamente nel sistema di ticketing
4. **Implementa cron job** per esecuzione periodica
5. **Scala gradualmente** con tutti i 10 account
6. **Monitora le performance** (tempo di esecuzione, numero di errori)
7. **Considera un middleware più robusto** per la produzione (RabbitMQ, Kafka, etc.)

## Contatti e Supporto

Per domande su questo script, consulta la documentazione del progetto o contatta il team DevOps.
