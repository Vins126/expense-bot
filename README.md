# Expense Bot

Bot Telegram per il tracciamento delle spese mensili. Invia un messaggio vocale o testuale e il bot trascrive, estrae i dati e li salva automaticamente su Google Sheets.

---

## Indice

- [Come funziona](#come-funziona)
- [Architettura](#architettura)
- [Struttura del progetto](#struttura-del-progetto)
- [Setup iniziale](#setup-iniziale)
- [Variabili d'ambiente](#variabili-dambiente)
- [Avvio in locale](#avvio-in-locale)
- [Deploy su Google Cloud](#deploy-su-google-cloud)
- [Google Sheets](#google-sheets)
- [Workflow di versionamento](#workflow-di-versionamento)
- [Risoluzione problemi](#risoluzione-problemi)

---

## Come funziona

1. L'utente invia una nota vocale o un messaggio testuale a `@EstratiDatiSpeseBot`
2. Il bot trascrive l'audio in testo (Groq Whisper)
3. Il testo viene analizzato da un LLM per estrarre: importo, categoria, descrizione e data (Groq LLaMA 3.3 70B)
4. Il bot mostra un riepilogo e chiede conferma tramite pulsanti inline (✅ Sì / ❌ No)
5. Se confermato, la spesa viene salvata nel Google Sheet in una nuova riga

**Esempi di input validi:**
- `ho speso 12 euro al bar`
- `spesa al supermercato 35,50`
- `farmacia 8 euro ieri`
- *(nota vocale con qualsiasi formulazione naturale in italiano)*

---

## Architettura

```
[Utente su Telegram]
    ↓ messaggio vocale / testo
[python-telegram-bot — long polling su GCP e2-micro]
    ↓ audio OGG
[Groq Whisper API] → testo italiano
    ↓
[Groq LLaMA 3.3 70B] → JSON { date, amount, category, description }
    ↓ preview + conferma utente
[Google Sheets API — gspread] → nuova riga nel foglio "Spese"
    ↓
[Messaggio di conferma su Telegram]
```

**Stack tecnologico:**

| Componente | Tecnologia | Piano gratuito |
|---|---|---|
| Bot | python-telegram-bot v21 (long polling) | — |
| Trascrizione | Groq Whisper | 2.000 req/giorno |
| Estrazione dati | Groq LLaMA 3.3 70B | 1.000 req/giorno |
| Storage | Google Sheets + gspread | Nessun limite pratico |
| Hosting | GCP Compute Engine e2-micro | Always Free (us-central1) |

---

## Struttura del progetto

```
expense-bot/
├── main.py                  # Entry point: avvia il bot in long polling
├── config.py                # Carica e valida le variabili d'ambiente
├── bot/
│   ├── __init__.py
│   └── handlers.py          # Handlers Telegram: voice, text, conferma/annulla
├── services/
│   ├── __init__.py
│   ├── transcribe.py        # Groq Whisper: audio OGG → testo
│   ├── extract.py           # Groq LLaMA: testo → Expense (dataclass)
│   └── sheets.py            # gspread: append riga + setup dashboard Riepilogo
├── deploy.sh                # Script per deploy automatico sulla VM GCP
├── Dockerfile               # Per build Docker (usato da GCP)
├── requirements.txt         # Dipendenze Python
├── .env.example             # Template variabili d'ambiente (senza valori reali)
├── .env                     # Variabili reali — NON committare, è in .gitignore
└── .gitignore
```

---

## Setup iniziale

Questo setup va fatto **una sola volta**. Se stai solo clonando il progetto su una nuova macchina, vai direttamente a [Avvio in locale](#avvio-in-locale).

### 1. Telegram Bot

1. Apri Telegram e cerca `@BotFather`
2. Invia `/newbot` e segui le istruzioni
3. Copia il token ricevuto → `BOT_TOKEN`
4. Per trovare il tuo Telegram user ID: cerca `@userinfobot` e invia `/start` → `AUTHORIZED_USER_ID`

### 2. Groq API

1. Vai su [console.groq.com](https://console.groq.com) e registrati (gratuito, no carta di credito)
2. Crea una API key → `GROQ_API_KEY`

### 3. Google Sheets

**Crea il foglio:**
1. Vai su [sheets.google.com](https://sheets.google.com) e crea un nuovo foglio
2. Nominalo come vuoi (es. `SpeseVarie`)
3. Copia l'ID dall'URL: `docs.google.com/spreadsheets/d/**QUESTO_ID**/edit` → `SPREADSHEET_ID`

**Crea le credenziali del service account:**
1. Vai su [Google Cloud Console](https://console.cloud.google.com)
2. Seleziona o crea un progetto
3. Abilita l'API: *API e servizi → Libreria → "Google Sheets API" → Abilita*
4. Crea service account: *API e servizi → Credenziali → Crea credenziali → Account di servizio*
5. Dai un nome (es. `expense-bot`), clicca su *Fine*
6. Apri il service account appena creato → scheda *Chiavi* → *Aggiungi chiave → JSON*
7. Scarica il file JSON

**Condividi il foglio con il service account:**
1. Apri il file JSON scaricato e copia il valore di `client_email` (es. `expense-bot@progetto.iam.gserviceaccount.com`)
2. Apri il Google Sheet → *Condividi* → incolla l'email → ruolo *Editor*

**Prepara la variabile d'ambiente:**
Il JSON delle credenziali deve essere su una sola riga. Da terminale:
```bash
cat credentials.json | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)))"
```
Copia l'output → `GOOGLE_CREDENTIALS_JSON`

### 4. Configura il file .env

```bash
cp .env.example .env
```
Apri `.env` e compila tutti i valori (vedi sezione [Variabili d'ambiente](#variabili-dambiente)).

---

## Variabili d'ambiente

| Variabile | Descrizione | Dove si trova |
|---|---|---|
| `BOT_TOKEN` | Token del bot Telegram | @BotFather su Telegram |
| `GROQ_API_KEY` | API key per Groq (Whisper + LLaMA) | console.groq.com |
| `GOOGLE_CREDENTIALS_JSON` | JSON del service account Google (su una riga) | Google Cloud Console → Service Accounts → Chiavi |
| `SPREADSHEET_ID` | ID del Google Sheet | URL del foglio |
| `AUTHORIZED_USER_ID` | Telegram user ID numerico autorizzato | @userinfobot su Telegram |

---

## Avvio in locale

```bash
# 1. Clona il progetto (se non lo hai già)
git clone https://github.com/Vins126/expense-bot.git
cd expense-bot

# 2. Crea il virtualenv e installa le dipendenze
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configura le variabili d'ambiente
cp .env.example .env
# Modifica .env con i valori reali

# 4. Avvia il bot
python3 main.py
```

Il bot è attivo finché il terminale è aperto. Per fermarlo: `Ctrl+C`.

> Il bot funziona solo se il Mac è acceso e connesso. Per averlo sempre attivo → [Deploy su Google Cloud](#deploy-su-google-cloud).

---

## Deploy su Google Cloud

Il bot gira su una VM **GCP e2-micro** nella zona `us-central1-a` (Always Free — nessun costo).

**Prerequisiti:**
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installato (`brew install --cask google-cloud-sdk`)
- Autenticato: `gcloud auth login`
- Progetto impostato: `gcloud config set project PROGETTO_ID`

### Deploy di un aggiornamento

Dopo aver modificato il codice in locale:

```bash
./deploy.sh
```

Lo script automaticamente:
1. Crea un archivio dei file sorgente (esclude `.venv`, `__pycache__`, ecc.)
2. Carica l'archivio sulla VM via `gcloud compute scp`
3. Estrae i file sulla VM
4. Riavvia il servizio `expense-bot` tramite systemd

### Comandi utili sulla VM

```bash
# SSH nella VM
gcloud compute ssh expense-bot --zone=us-central1-a --project=PROGETTO_ID

# Sulla VM — vedere i log in tempo reale
sudo journalctl -u expense-bot -f

# Sulla VM — controllare lo stato del bot
sudo systemctl status expense-bot

# Sulla VM — riavviare manualmente il bot
sudo systemctl restart expense-bot
```

### Setup della VM (solo la prima volta)

> Questo è già stato fatto. Queste istruzioni servono solo se si ricrea la VM da zero.

```bash
# 1. Crea la VM
gcloud compute instances create expense-bot \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB

# 2. Copia il codice sulla VM
tar -czf /tmp/expense-bot.tar.gz expense-bot
gcloud compute scp /tmp/expense-bot.tar.gz expense-bot:~ --zone=us-central1-a

# 3. Sulla VM: installa dipendenze e crea il servizio systemd
gcloud compute ssh expense-bot --zone=us-central1-a --command="
  sudo apt-get install -y python3-venv &&
  cd ~/expense-bot &&
  tar -xzf ~/expense-bot.tar.gz &&
  python3 -m venv .venv &&
  .venv/bin/pip install -r requirements.txt
"

# 4. Crea il file /etc/systemd/system/expense-bot.service sulla VM (vedi sotto)
# 5. sudo systemctl enable expense-bot && sudo systemctl start expense-bot
```

**File systemd** (`/etc/systemd/system/expense-bot.service`):
```ini
[Unit]
Description=Expense Tracker Telegram Bot
After=network.target

[Service]
Type=simple
User=TUO_USERNAME
WorkingDirectory=/home/TUO_USERNAME/expense-bot
ExecStart=/home/TUO_USERNAME/expense-bot/.venv/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## Google Sheets

Il foglio è composto da due sheet:

### Sheet "Spese" — dati grezzi

Popolato automaticamente dal bot ad ogni spesa confermata.

| Data | Importo (€) | Categoria | Descrizione | Mese | Anno |
|---|---|---|---|---|---|
| 08/05/2026 | 35.50 | Alimentari | Spesa supermercato | Maggio | 2026 |

### Sheet "Riepilogo" — dashboard automatica

Generato automaticamente al primo avvio del bot. Contiene formule SUMIF che si aggiornano ad ogni nuova riga nel foglio Spese:
- Totale per categoria (Alimentari, Ristoranti/Bar, Trasporti, ecc.)
- Totale per mese (Gennaio → Dicembre)

> **Nota locale Google:** le formule usano `;` come separatore (standard italiano). Se il foglio viene aperto con un account con locale inglese, le formule potrebbero non funzionare.

**Categorie riconosciute:**
`Alimentari`, `Ristoranti/Bar`, `Trasporti`, `Abbigliamento`, `Salute/Farmacia`, `Casa/Utenze`, `Intrattenimento`, `Bellezza`, `Regali`, `Altro`

---

## Workflow di versionamento

Il progetto usa **Semantic Versioning**: `vMAGGIORE.MINORE.PATCH`

| Tipo | Quando | Esempio |
|---|---|---|
| PATCH | Bugfix, correzioni | `v1.0.1` |
| MINOR | Nuova funzionalità retrocompatibile | `v1.1.0` |
| MAJOR | Cambiamento architetturale rilevante | `v2.0.0` |

### Flusso completo per una nuova versione

```bash
# 1. Lavora sulle modifiche in locale e testale

# 2. Commit delle modifiche
git add .
git commit -m "feat: descrizione della modifica"

# 3. Crea il tag della nuova versione
git tag v1.1.0

# 4. Pusha su GitHub (codice + tag)
git push
git push origin v1.1.0

# 5. Deploya sulla VM
./deploy.sh
```

### Convenzione dei messaggi di commit

```
feat: aggiunta nuova funzionalità
fix: correzione di un bug
refactor: modifica interna senza cambiare comportamento
docs: aggiornamento documentazione
```

---

## Risoluzione problemi

**Il bot non risponde ai messaggi**

Controlla che il servizio sia attivo sulla VM:
```bash
gcloud compute ssh expense-bot --zone=us-central1-a --command="sudo systemctl status expense-bot"
```
Se è fermo: `sudo systemctl start expense-bot`

**Errore "Terminated by other getUpdates request"**

C'è un'altra istanza del bot in esecuzione (es. quella locale sul Mac). Fermala:
```bash
pkill -f "python3 main.py"
```
Il bot può girare solo su un'istanza alla volta.

**Errore Google Sheets al salvataggio**

Verifica che il service account abbia accesso al foglio:
1. Apri il Google Sheet
2. Clicca *Condividi*
3. Controlla che `client_email` del service account sia presente come Editor

**Il foglio Riepilogo mostra #ERROR!**

Le formule SUMIF usano `;` (locale italiana). Se usi un account Google con locale diversa, sostituisci manualmente `;` con `,` nelle formule del foglio Riepilogo.

**Come vedere i log del bot in tempo reale**

```bash
gcloud compute ssh expense-bot --zone=us-central1-a --command="sudo journalctl -u expense-bot -f"
```
