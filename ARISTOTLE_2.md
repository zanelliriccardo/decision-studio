# Decision Studio vs Aristotle — dopo l'implementazione

Basato sui contenuti della pagina prodotto: Enterprise Value, For Learners,
Platform, Methodology, Applications.

---

## Le tre fasi dichiarate da Aristotle

| | Aristotle | Decision Studio |
|---|---|---|
| **Problem Framing** — domande guidate, ricerca contestuale, sintesi | ✅ | ✅ questionario 15 domande + **gate** |
| **Theory Generation** — teorie AI, DAG, confronto multiplo | ✅ | ✅ + provenance cliccabile |
| **Experiment** — sintetico, sul campo, validazione causale | ✅ | ✅ implementato |

Le tre fasi sono coperte.

## I quattro strumenti di piattaforma

| Loro | Noi |
|---|---|
| Curated Case Library | ❌ **Non lo farei**: serve a MBA ed executive education, non a decisioni reali |
| AI-Powered Learning Coach | ⚠️ Questionario fisso invece di coaching socratico |
| Visual Causal Mapping + drag-and-drop | ✅ Aggiunta manuale via API — **manca l'editor drag-and-drop** |
| Theory Analysis: debate and compare | ✅ Implementato, con crux e discriminante |

## I cinque valori enterprise

| Loro | Noi |
|---|---|
| Build & Persuade | ⚠️ Persuasione: esperimento sintetico anticipa le obiezioni. **Manca l'export** |
| Think Probabilistically | ✅ Monte Carlo, bande verbali, p_first |
| Quantify Intuition | ⚠️ Parziale — vedi sotto |
| **Explore Counterfactuals** | ✅ Il motore scenari c'era già |
| Strengthen Theories | ✅ Avversario, tripwire, rigenerazione |

---

## Cosa manca ancora, in ordine

### 1. Editor drag-and-drop (UI)

Il backend c'è: `POST /claims`, `POST /edges`, ricalcolo incrementale. Manca
l'interazione diretta sul grafo — trascinare da un nodo all'altro per creare un
nesso. Oggi si passa da un form.

**Costo:** medio, tutto frontend. Serve gestione del drag su SVG in ForceGraph.

### 2. Elicitazione assistita delle probabilità

> "AI-assisted probability elicitation"

È il **divario metodologico più interessante**. Da noi i numeri li assegna l'AI e
tu li correggi con uno slider — che è letteralmente la domanda "quanto sei sicuro
da 0 a 1", nota per produrre numeri pessimi.

La letteratura sull'elicitazione esiste proprio per questo: confronto con lotterie
di riferimento ("preferiresti scommettere su questo o su un'estrazione con
probabilità nota del 70%?"), ancoraggio su frequenze, scomposizione in
sotto-eventi.

Questo è ciò che rende reale il loro *"Quantify Intuition"*. Da noi l'intuizione
non viene quantificata: viene **corretta con uno slider**.

**Costo:** basso-medio. È un protocollo guidato, non infrastruttura.

### 3. Export dei deliverable

> "persuade stakeholders with data"

Loro nominano Problem/Theory/Experiment Artifact. Una decisione strategica finisce
in una riunione, non in una webapp: serve un PDF o uno slide deck con la teoria,
la catena causale, le obiezioni e i tripwire.

Nota: il repo ha già `api/routes/export.py`, quindi c'è dove innestarsi.

**Costo:** basso-medio.

### 4. Template di dominio

Sei casi d'uso dichiarati: M&A, hiring esecutivo, struttura del capitale,
innovazione, ingresso mercato, ristrutturazione. Ognuno ha domande di
inquadramento diverse — una due diligence non chiede le stesse cose di una
riorganizzazione.

Il catalogo è già dati: servono varianti.

**Costo:** basso. **Miglior rapporto valore/lavoro.**

### 5. Coaching socratico

Il loro Problem Agent incalza; il nostro questionario prende la risposta e va
avanti.

Il compromesso che rivendico: le nostre risposte restano confrontabili fra
progetti, le obbligatorie sono note in anticipo e quindi possono **bloccare**, e
ogni domanda dichiara cosa alimenta. Il coaching è più piacevole e meno
auditabile. La sintesi giusta è coaching che **popola** il frame strutturato.

**Costo:** medio.

---

## Cosa abbiamo che loro non mostrano

1. **Provenance fino alla frase sorgente.** Loro parlano di DAG e
   visualizzazione, non di tracciabilità. Una teoria da noi cita claim, archi ed
   evidenze esatti.
2. **Revisione autoritativa con audit e undo.** Rifiutare un nesso lo rimuove da
   ogni ragionamento futuro, con log immutabile.
3. **Stabilità sotto perturbazione.** "Think probabilistically" da noi significa
   anche *"A vince nel 52% delle simulazioni"*, non solo assegnare numeri.
4. **Interesse della fonte.** Ammissione contro il proprio interesse vs
   rassicurazione interessata. Con documenti interni è una leva forte.
5. **Vista esterna operativa.** Base rate estratti e *confrontati* con le
   confidenze.
6. **Deduplicazione semantica dei claim.**
7. **Il rifiuto di fingere.** L'esperimento sintetico non alza mai la confidenza;
   il debate sa dire "non decidibile in tempo"; le confidenze sono bande perché
   nessuno le ha calibrate. Non risulta che loro abbiano vincoli equivalenti — e
   questa è la differenza filosofica più marcata.

---

## Il divario che resta, e non è tecnico

Aristotle vende un **metodo** con dentro un software: una tesi articolata su come
si dovrebbe decidere, un indice per misurare la maturità decisionale delle
organizzazioni, e la executive education per insegnarla.

Decision Studio è uno strumento con opinioni forti — sulla provenance, sull'onestà
epistemica, sul giudizio umano autoritativo — ma quelle opinioni sono **implicite
nel codice**, non articolate come metodo.

Le quattro feature sopra si colmano in poche settimane. Quella distanza no.
