# Decision Studio — Supporto a decisioni strategiche

Riorientamento per decisioni dove non esistono evidenze numeriche né esperimenti
ripetibili. Il principio: se la conclusione non può essere validata dai dati, la
validazione deve venire dal **processo**.

## 1. Questionario di inquadramento (15 domande, obbligatorio)

`decision_studio/reasoning/framing.py` — catalogo fisso, non generato dall'LLM, perché
deve esistere prima di qualsiasi generazione e le risposte devono restare
confrontabili fra progetti.

| Sezione | Domande |
|---|---|
| Il tuo ruolo | ruolo, autorità, chi va convinto |
| La decisione | cosa si decide, opzioni reali, scadenza, reversibilità |
| Criteri | come sapresti di aver deciso bene, vincoli, quale errore preferisci |
| Cosa credi già | convinzione attuale, cosa ti farebbe cambiare idea, casi simili |
| Fonti | tipi di fonte caricati, chi le ha scritte e chi ci guadagna |

**10 sono obbligatorie e bloccano la generazione** (`FrameIncompleteError`, HTTP 409
con l'elenco delle mancanti). Ogni domanda dichiara in `feeds` cosa alimenta a
valle: una domanda che non guida niente va cancellata, non posta. Ogni domanda
mostra all'utente **perché** viene fatta — un questionario che sembra burocrazia
viene compilato male, e risposte sbadate sono peggio di risposte assenti.

Il frame **precede** le evidenze nel prompt: prima si sa cosa si decide, poi si
guarda il materiale. Un test lo verifica.

## 2. Tripwire — il sostituto dell'esperimento

`theory_tripwire` + `decision_studio/reasoning/adversary.py`

Non puoi randomizzare una decisione strategica. Puoi impegnarti in anticipo su
**quale osservazione ti direbbe che hai sbagliato**, e poi guardare davvero.

Ogni teoria riceve 1–3 osservazioni concrete, con direzione (falsifica/conferma),
orizzonte in giorni e data di verifica. Il prompt privilegia la falsificazione:
molte cose confermano una teoria falsa, poche ne falsificano una vera. La risposta
dell'utente a *"cosa ti farebbe cambiare idea"* entra direttamente nel prompt.

Quando un tripwire di falsificazione scatta, **la teoria diventa stale**: la cosa
che l'utente stesso aveva indicato come dirimente è successa.

## 3. Avversario con peso reale

`theory_objection` + prompt dedicato.

Chiamata separata, temperatura 0.7, che **non vede mai** titolo, sintesi o
raccomandazione della teoria — solo la decisione e la catena causale. Con il testo
persuasivo davanti criticherebbe la scrittura; senza, deve attaccare il
ragionamento. Cerca specificamente: causa comune, fonte unica, reversibilità
della conclusione, ambito, tempistica, incentivo dell'autore.

**Le obiezioni costano posizione.** `objection_load` è la media delle severità
(non la somma: tre obiezioni blande non devono superare una fatale), e
`adjusted_score = confidence × (1 − 0.5 × load)` è ciò per cui il pannello ordina.
Una teoria contestata non può più stare in cima in silenzio. L'utente può giudicare
un'obiezione infondata e questa smette di pesare.

Demota, non annienta: anche l'avversario è solo un modello linguistico.

## 4. Assenza di evidenza ≠ smentita

`_evidence_modulation` aveva pavimento 0.0, documentato come *"no evidence: zero
effectiveness"*. Un fatto interno non cercabile e una tesi smentita da tre fonti
valevano lo stesso zero.

Ora: pavimento **0.30** se non c'è contraddizione, **0.05** se c'è. Solo la
contraddizione abbassa la credenza; il silenzio allarga l'incertezza.

| | prima | ora |
|---|---|---|
| Nessuna evidenza | 0.000 | **0.300** |
| Contraddetta | 0.000 | 0.050 |
| Evidenza forte | 0.854 | 0.854 |

Inoltre `evidence.source_url` diventa nullable e arriva `author_interest`: un
report interno è una fonte di prima classe, non un risultato web con un campo
mancante.

## 5. Rimossa la falsa precisione

`decision_studio/reasoning/calibration.py` — bande verbali (very_low … very_high) al
posto dei decimali. Niente in Decision Studio è mai stato calibrato: nessuno ha
verificato che le teorie a 0.72 siano vere il 72% delle volte, e per decisioni
uniche nessuno può. Mostrare `72%` afferma una risoluzione che non esiste.

Il float resta e continua a ordinare correttamente — ordinare è ciò per cui va
bene. Un test verifica che `0.72` e `72%` non compaiano più nel pannello.

## Cosa NON ho rimosso, e perché

Non ho smantellato il Noisy-OR né lo scoring delle fonti web. Il Noisy-OR resta il
modo giusto di propagare: il problema non era la matematica ma l'elicitazione dei
parametri, già corretta separando effetto e confidenza. E le fonti web restano
utili quando ci sono — le ho **declassate da modello unico a uno dei modelli**,
non eliminate. Rimuovere codice funzionante perché non copre il caso principale
sarebbe stato distruttivo.

## Verifica

- **324 test backend** (259 + 65 nuovi), **138 frontend** (112 + 26 nuovi)
- Migrazione 006 reversibile, roundtrip pulito
- Typecheck: 32 errori contro 33 della baseline, nessuno introdotto
- Il gate ha fatto fallire 42 test preesistenti che generavano senza inquadramento
  — comportamento corretto, fixture aggiornate

Un bug vero emerso durante i test: il gate scattava prima di verificare
l'esistenza del progetto, quindi un id inesistente rispondeva *"rispondi alle
domande"* invece di 404.

## Limiti noti

1. **La vista esterna è solo una domanda.** `reference_class` raccoglie i casi
   simili ma nessun codice li usa per calibrare. È testo che finisce nel prompt.
2. **`author_interest` esiste ma non è popolato.** La colonna c'è, l'estrazione
   non la compila ancora: serve un passaggio nel claim extractor.
3. **I tripwire non hanno promemoria.** `check_by` è salvato, ma niente avvisa
   alla scadenza. Serve uno scheduler.
4. **`OBJECTION_WEIGHT = 0.5` è scelto a mano**, come le altre soglie.
5. **L'avversario non vede le evidenze**, solo la catena. Potrebbe obiettare
   qualcosa che le fonti già smentiscono.
6. **Il questionario è in inglese** nel catalogo; le stringhe UI sono tradotte ma
   le domande arrivano dal backend in inglese.
