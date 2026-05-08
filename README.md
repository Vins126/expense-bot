# Expense Bot — Bot Telegram per Tracciamento Spese

Bot Telegram che trascrive messaggi vocali (o testo), estrae importo/categoria/descrizione e salva tutto su Google Sheets automaticamente.

---

## Prerequisiti

- Python 3.12+
- Credenziali già configurate nel file `.env` (BOT_TOKEN, GROQ_API_KEY, GOOGLE_CREDENTIALS_JSON, SPREADSHEET_ID, AUTHORIZED_USER_ID)

---

## Avvio in locale

```bash
cd /Users/vincenzomattioli/Documents/ClaudeTest/expense-bot

# 1. Attiva il virtualenv
source .venv/bin/activate

# 2. Avvia il bot
python3 main.py
```

Il bot è attivo finché il terminale è aperto. Per fermarlo: `Ctrl+C`.

> **Nota:** Se il Mac si spegne o va in sleep, il bot si ferma. Per averlo sempre attivo → vedi sezione Deploy su Koyeb.

---

## Come si usa

Invia al bot `@EstratiDatiSpeseBot` su Telegram:

| Input | Esempio |
|---|---|
| Messaggio vocale | *"Ho speso venti euro al supermercato"* |
| Testo libero | `ho speso 12 euro al bar` |

Il bot risponde con un riepilogo e due pulsanti: **✅ Sì** (salva) / **❌ No** (annulla).

---

## Google Sheets

Il foglio **SpeseVarie** ha due sheet:

- **Spese** — righe grezze aggiunte dal bot (Data, Importo, Categoria, Descrizione, Mese, Anno)
- **Riepilogo** — totali automatici per categoria e per mese tramite formule SUMIF

Le formule nel Riepilogo si aggiornano da sole ad ogni nuova spesa.

---

## Deploy su Koyeb (sempre attivo, gratis)

Per avere il bot sempre acceso senza tenere il Mac aperto:

### 1. Carica il codice su GitHub

```bash
cd /Users/vincenzomattioli/Documents/ClaudeTest/expense-bot
git init
git add .
git commit -m "initial commit"
# Crea repo su github.com, poi:
git remote add origin https://github.com/TUO_USERNAME/expense-bot.git
git push -u origin main
```

> Il file `.env` è nel `.gitignore` — le credenziali non vengono caricate su GitHub.

### 2. Deploy su Koyeb

1. Vai su [koyeb.com](https://www.koyeb.com) e registrati (no carta richiesta)
2. **Create App** → seleziona **GitHub** → scegli il repo `expense-bot`
3. Koyeb rileva il `Dockerfile` automaticamente
4. Nella sezione **Environment variables**, aggiungi tutte le variabili dal tuo `.env`:
   - `BOT_TOKEN`
   - `GROQ_API_KEY`
   - `GOOGLE_CREDENTIALS_JSON`
   - `SPREADSHEET_ID`
   - `AUTHORIZED_USER_ID`
5. Clicca **Deploy** — il bot parte e resta sempre acceso

---

## Struttura del progetto

```
expense-bot/
├── main.py                  # Entry point
├── config.py                # Lettura variabili d'ambiente
├── bot/
│   └── handlers.py          # Logica conversazione Telegram
├── services/
│   ├── transcribe.py        # Groq Whisper: audio → testo
│   ├── extract.py           # Groq LLaMA: testo → dati strutturati
│   └── sheets.py            # Google Sheets: salvataggio righe
├── requirements.txt
├── Dockerfile
├── .env                     # Credenziali reali (NON committare)
└── .env.example             # Template vuoto (committato)
```

---

## Risoluzione problemi

**"Terminated by other getUpdates request"** — c'è un'altra istanza del bot in esecuzione:
```bash
pkill -f "python3 main.py"
```

**Il bot non risponde** — verifica che il processo sia attivo:
```bash
ps aux | grep main.py
```

**Errore Google Sheets** — controlla che il service account abbia accesso al foglio: apri il foglio → Condividi → l'email `botexcel@botexcel-495709.iam.gserviceaccount.com` deve essere editor.
