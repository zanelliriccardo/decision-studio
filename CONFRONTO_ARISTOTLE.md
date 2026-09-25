# Decision Studio vs Aristotle (SDA Bocconi ION Management Science Lab)

**Avvertenza sulla fonte.** Ho letto solo la pagina prodotto pubblica con gli
screenshot e il diagramma di architettura. Non ho documentazione tecnica né
accesso al prodotto. Quello che segue è dedotto da otto screenshot e da un
diagramma a blocchi: prendilo come una lettura ragionata, non come un'analisi
verificata.

---

## L'architettura di Aristotle, come dichiarata

```
User Request → Orchestrator → Route
    ├── Problem Agent      Coaching → Context → Finalizing      → Problem Artifact
    ├── Theory Agent       Preference → Generate → Evaluate → Refine → Theory Artifact
    └── Experiment Agent   Select → Hypothesize → Design → Personas → Execute → Experiment Artifact
                                                              → Decision Execution
```

Flusso utente in 8 passi: descrivi la sfida → coaching sul problema → raccolta
contesto (obiettivi, vincoli, metriche di successo) → integrazione dati esterni →
generazione teorie → opzioni strategiche → design dell'esperimento.

---

## Convergenza

La sovrapposizione è notevole, e i due sistemi sono stati progettati in modo
indipendente:

| Aristotle | Decision Studio (nostro) |
|---|---|
| Problem Agent: Coaching → Context | Questionario di inquadramento (15 domande, gate) |
| "Context Gathering: obiettivi, vincoli, metriche di successo" | Sezioni *decisione*, *criteri* del questionario |
| Theory Agent: Generate | Generazione teorie dal grafo |
| Theory Agent: **Evaluate → Refine** | Avversario + rigenerazione con confronto versioni |
| Theory Agent: **Preference** | `current_belief`, `risk_appetite` nel questionario |
| Experiment Agent | Tripwire |

Che due gruppi arrivino indipendentemente a *inquadra → genera teorie → critica →
verifica* suggerisce che sia la forma giusta del problema. È il segnale più utile
di tutto il confronto.

---

## Dove Aristotle è più avanti

### 1. L'Experiment Agent — la differenza sostanziale

Questo è il punto che conta. Io avevo scritto: *"non puoi randomizzare una
decisione strategica, quindi il massimo disponibile è impegnarsi in anticipo su
cosa ti farebbe cambiare idea"*. I tripwire accettano il vincolo.

Aristotle **non accetta il vincolo**. `Select → Hypothesize → Design → Personas →
Execute` indica che genera *personas* e **esegue** l'esperimento — verosimilmente
simulando reazioni di stakeholder o clienti. È un test che dà una risposta oggi,
non fra 90 giorni.

Il mio tripwire dice *"guarda se il fornitore conferma entro il 25 agosto"*. Il
loro esperimento dice *"simuliamo ora come reagirebbe il CFO"*. Sono strumenti
diversi e complementari — ma il loro chiude il ciclo, il mio lo apre e aspetta.

**Se dovessi aggiungere una cosa sola a Decision Studio, sarebbe questa.**

### 2. Coaching conversazionale invece di questionario fisso

Il loro Problem Agent fa *coaching*: riformula il problema in dialogo. Il mio è
un catalogo fisso di 15 domande.

Il loro vantaggio: si adatta: se qualcuno descrive male il problema, l'agente lo
incalza. Il questionario fisso no.

Il mio vantaggio, che rivendico: le risposte restano **confrontabili fra
progetti**, le domande obbligatorie sono note in anticipo e quindi possono
**bloccare** la generazione, e ogni domanda dichiara cosa alimenta a valle. Un
coaching conversazionale è più piacevole e più difficile da auditare.

Non credo che uno domini l'altro. Il compromesso sensato è coaching in ingresso
che *popola* un frame strutturato.

### 3. Artifacts espliciti

Problem Artifact, Theory Artifact, Experiment Artifact. Deliverable intermedi
nominati e presumibilmente esportabili. In Decision Studio il frame, le teorie e i
tripwire esistono ma non sono confezionati come oggetti consegnabili.

---

## Dove Decision Studio è più avanti

### 1. Il grafo causale — che Aristotle sembra non avere

Negli screenshot e nell'architettura non c'è traccia di rappresentazione causale
esplicita, propagazione di credenze o grafo. Il flusso va da problema a teorie
direttamente.

Questo significa che in Decision Studio una teoria **cita gli elementi esatti** su cui
poggia: claim, edge, evidenze, con provenance cliccabile. È possibile chiedere
*"perché questa conclusione?"* e ricevere un percorso, non una spiegazione
generata a posteriori. Se il ragionamento non può essere validato empiricamente,
poterlo **auditare** è il sostituto — ed è esattamente ciò che il grafo fornisce.

### 2. Revisione umana autoritativa

L'utente può rifiutare un nesso causale e questo **sparisce da ogni ragionamento
futuro**, con log di audit e undo. Non vedo un equivalente. In un dominio dove il
giudizio umano *è* l'evidenza, questo non è un dettaglio.

### 3. Quantificazione dell'incertezza

Monte Carlo con rumore per-edge scalato dalla confidenza, che riporta *"A vince
nel 52% delle simulazioni"* invece di *"A vince"*. Sospetto che Aristotle
presenti le teorie senza barre d'errore — ma è una supposizione, e potrei
sbagliarmi.

### 4. Interesse della fonte

Distinguere l'ammissione contro il proprio interesse dalla rassicurazione
interessata. Non compare nel loro materiale, ma con documenti interni caricati è
una delle leve più forti disponibili.

---

## Cosa ruberei

1. **L'Experiment Agent con le personas.** È la risposta migliore al problema che
   avevo dichiarato irrisolvibile.
2. **Il coaching in ingresso** che popola il frame strutturato invece di
   sostituirlo.
3. **Gli artifact esportabili** — una decisione strategica finisce in una
   riunione, non in una webapp.

## Cosa non cambierei

Il grafo causale con provenance. È il motivo per cui Decision Studio può rispondere
*"perché"*, ed è la cosa più difficile da aggiungere dopo.

---

## Nota onesta sul posizionamento

Aristotle è un prodotto di ricerca di una business school, con executive
education dietro e un indice proprio (SDM Index) per misurare la maturità
decisionale delle organizzazioni. Ha una teoria del metodo decisionale e un canale
per insegnarla.

Decision Studio è uno strumento. Più forte sulla tracciabilità, più debole sul metodo.
Se l'obiettivo è competere frontalmente, il divario da colmare non è tecnico: è
che loro hanno un'opinione articolata su *come si dovrebbe decidere*, e la
vendono insieme al software.
