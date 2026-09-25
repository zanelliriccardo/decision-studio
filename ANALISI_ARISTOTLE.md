# Decision Studio vs Aristotle — analisi delle feature mancanti

Basata sui contenuti della pagina prodotto che mi hai passato: Enterprise Value,
For Learners, Platform, Methodology, Applications.

---

## Cosa ho implementato ora

**Esperimenti sintetici e sul campo** (migrazione 008, 4 endpoint, 22 test).

Era il buco che avevo dichiarato principale, e la loro metodologia lo conferma:
*Problem Framing → Theory Generation → **Experiment***, con "synthetic
experiments" e "field experiment design" esplicitati.

### Come funziona

**Sintetico**: costruisce la stanza che la decisione deve superare. Le persona
sono ricavate da chi *tu* hai detto che va convinto nel questionario — inventarle
da zero simulerebbe una riunione che non esiste. Ogni stakeholder ha uno *stake*
reale (cosa ci guadagna o ci perde), e il prompt impone che almeno uno sia
probabilmente contrario: una stanza di sostenitori non testa niente.

**Sul campo**: propone un test vero, eseguibile entro la scadenza, con costo e
durata onesti. Se non esiste un test significativo nell'orizzonte, lo dice — ed è
un risultato utile, non un fallimento: significa che la decisione va presa a
giudizio, e tu devi saperlo.

### La differenza che ho introdotto rispetto a un'implementazione ingenua

**Un esperimento sintetico non alza mai la confidenza di una teoria.** È vincolato
nel codice, non solo documentato, e c'è un test che lo verifica.

Il motivo: cinque stakeholder simulati, quattro favorevoli, confidenza che sale —
sarebbe una misura della *compiacenza del modello* presentata a un dirigente come
evidenza. Nessuno ha osservato niente del mondo.

Quello che l'esperimento sintetico fa invece è promuovere le obiezioni degli
stakeholder nel registro avversariale esistente, dove **costano posizione** e tu
puoi giudicarle infondate. L'accordo simulato non vale nulla; l'obiezione simulata
vale, perché è economica da ottenere e costosa da incontrare impreparati.

Una singola persona contraria non basta a marcare una teoria contestata
(`SIMULATED_OBJECTION_SEVERITY = 0.35`, sotto la soglia). Diverse sì.

---

## Feature che Aristotle ha e Decision Studio no

### 1. Costruzione manuale del grafo — *il buco più grave rimasto*

> "Visual Causal Mapping: Build interactive maps connecting business factors with
> **drag-and-drop tools**"

Decision Studio genera il grafo dai documenti. Tu puoi rifiutare, disattivare, annotare,
sovrascrivere la forza — ma **non puoi aggiungere un nodo o un nesso che l'AI non
ha trovato.**

È un'asimmetria seria: la revisione umana è autoritativa per *togliere* e muta per
*aggiungere*. Se sai che c'è un fattore che nei documenti non compare — e nelle
decisioni strategiche è la norma, perché le cose importanti spesso non sono
scritte — non hai modo di metterlo nel modello.

Costo: medio. Serve un editor sul grafo, endpoint di creazione, e integrare gli
elementi manuali nella propagazione con provenance `user` invece di `ai`.
Concettualmente si innesta bene su `graph_operation`, che già registra le
operazioni reversibili.

### 2. Elicitazione assistita delle probabilità

> "AI-assisted **probability elicitation**"

Da noi i numeri li assegna l'AI e tu li correggi con uno slider. Loro hanno un
*processo* per estrarre le probabilità dalla testa dell'utente.

La differenza non è cosmetica. La letteratura sull'elicitazione (confronto con
lotterie di riferimento, ancoraggio su frequenze, scomposizione) esiste proprio
perché chiedere "quanto sei sicuro da 0 a 1" produce numeri pessimi. Uno slider è
esattamente quella domanda.

Costo: basso-medio. È un protocollo guidato, non infrastruttura.

### 3. Debate strutturato fra teorie

> "Theory Analysis Tools: **Debate and compare** functions to evaluate competing
> frameworks"

Da noi le teorie sono una lista ordinata. Ognuna ha il suo avversario, ma non si
confrontano mai *fra loro*. Non c'è un "T1 contro T3, quali evidenze le
distinguono, quale osservazione le separerebbe".

È la domanda più utile in una decisione strategica: non "questa teoria è buona"
ma "se sono entrambe plausibili, cosa le distingue".

Costo: medio. Ho già le teorie con provenance e ho già l'infrastruttura
avversariale — servirebbe una chiamata che prende due teorie e produce il
discriminante.

### 4. Template di dominio

> "M&A, Executive Hiring, Capital Structure, Innovation, Market Entry,
> Organizational Restructuring"

Sei casi d'uso con presumibilmente framing preconfezionati. Il nostro questionario
è uno solo, generico. Una due diligence su un'acquisizione e una ristrutturazione
organizzativa hanno domande diverse.

Costo: basso. Il catalogo delle domande è già dati; servono varianti per dominio.

### 5. Coaching socratico

> "AI-Powered Learning Coach: instant feedback, **Socratic questioning**"

Il loro Problem Agent incalza. Il nostro questionario no: se rispondi male, prende
la risposta e va avanti.

Rivendico però il compromesso: le nostre risposte restano confrontabili fra
progetti, le obbligatorie sono note in anticipo e quindi possono *bloccare*, e ogni
domanda dichiara cosa alimenta. Un coaching conversazionale è più piacevole e più
difficile da auditare. La sintesi giusta è coaching che **popola** il frame
strutturato, non che lo sostituisce.

### 6. Libreria di casi

Materiale didattico. Serve al loro mercato — MBA, executive education — non al
tuo, se Decision Studio è per decisioni reali. **Non lo aggiungerei.**

---

## Feature che Decision Studio ha e Aristotle sembra non avere

Da mettere sul piatto, perché il confronto non è a senso unico:

1. **Provenance cliccabile.** Ogni teoria cita claim, edge ed evidenze esatti.
   Loro parlano di DAG e di visualizzazione, ma non di tracciabilità fino alla
   frase sorgente.
2. **Revisione umana autoritativa con audit e undo.** Rifiutare un nesso lo
   rimuove da ogni ragionamento futuro, con log immutabile.
3. **Monte Carlo con rumore per-edge.** Loro dicono "think probabilistically";
   non risulta che riportino stabilità del ranking sotto perturbazione.
4. **Interesse della fonte.** Distinguere l'ammissione contro il proprio interesse
   dalla rassicurazione interessata. Con documenti interni caricati è una leva
   forte, e non compare nel loro materiale.
5. **Vista esterna operativa.** Base rate estratti dall'esperienza dell'utente e
   *confrontati* con le confidenze generate.
6. **Deduplicazione semantica dei claim.**

---

## Priorità, se vuoi continuare

| # | Feature | Costo | Perché |
|---|---|---|---|
| 1 | **Editing manuale del grafo** | Medio | L'asimmetria togli/aggiungi è il difetto più grave rimasto |
| 2 | **Debate fra teorie** | Medio | La domanda più utile che oggi non si può porre |
| 3 | **Elicitazione probabilità** | Basso-medio | Lo slider è la domanda sbagliata |
| 4 | **Template di dominio** | Basso | Molto valore per poco lavoro |
| 5 | Coaching sul frame | Medio | Migliora l'ingresso, non il ragionamento |
| — | Libreria di casi | — | Mercato diverso, non lo farei |

**Farei l'editing manuale per primo.** Non perché ce l'ha Aristotle, ma perché è
incoerente con quello che Decision Studio già dichiara: se il giudizio umano è
autoritativo — e tutto l'impianto dice di sì — allora deve poter aggiungere, non
solo togliere.

---

## Nota sul posizionamento

Aristotle vende un **metodo** con dentro un software: hanno una tesi articolata su
come si dovrebbe decidere, un indice per misurare la maturità decisionale delle
organizzazioni (SDM Index), e la executive education per insegnarla.

Decision Studio è uno strumento. Il divario più grande non è nelle feature che ho
elencato sopra — quelle si colmano in poche settimane. È che loro hanno
un'opinione su come si decide, e la vendono.
