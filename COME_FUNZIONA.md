# Decision Studio — Come funziona, passo per passo

Documento tecnico di tutto ciò che è stato aggiunto alla repository originale.
Per ogni componente: **cosa fa**, **in che ordine**, e — soprattutto — **su quali
assunzioni si regge**.

Le assunzioni sono la parte che conta. Il sistema produce numeri, e ogni numero
poggia su una scelta che qualcuno ha fatto a mano. Sono elencate esplicitamente
perché possano essere contestate.

---

# Indice

1. [Il flusso completo](#1-il-flusso-completo)
2. [Inquadramento decisionale](#2-inquadramento-decisionale)
3. [Estrazione dei claim](#3-estrazione-dei-claim)
4. [Deduplicazione semantica](#4-deduplicazione-semantica)
5. [Inferenza causale](#5-inferenza-causale)
6. [Ri-valutazione cieca](#6-ri-valutazione-cieca)
7. [Grounding delle evidenze](#7-grounding-delle-evidenze)
8. [Propagazione delle credenze](#8-propagazione-delle-credenze)
9. [Revisione umana](#9-revisione-umana)
10. [Authoring manuale](#10-authoring-manuale)
11. [Generazione delle teorie](#11-generazione-delle-teorie)
12. [Avversario](#12-avversario)
13. [Vista esterna](#13-vista-esterna)
14. [Debate fra teorie](#14-debate-fra-teorie)
15. [Tripwire](#15-tripwire)
16. [Esperimenti](#16-esperimenti)
17. [Monte Carlo](#17-monte-carlo)
18. [Domande di chiarimento](#18-domande-di-chiarimento)
19. [Invalidazione a cascata](#19-invalidazione-a-cascata)
20. [Tutte le assunzioni in un posto](#20-tutte-le-assunzioni-in-un-posto)

**Numeri:** 10 migrazioni · 77 endpoint · 17 moduli in `reasoning/` ·
458 test backend · 161 test frontend.

---

## 1. Il flusso completo

```
  documenti caricati
        │
        ▼
  ┌─────────────────┐
  │ INQUADRAMENTO   │  15 domande, 10 obbligatorie
  │ (gate)          │  → senza questo, la generazione è bloccata
  └────────┬────────┘
           ▼
  estrazione claim → dedup semantica → inferenza causale
           │                                  │
           │                          ri-valutazione cieca
           │                                  │
           │                          grounding evidenze
           ▼                                  │
  ┌─────────────────────────────────────────────┐
  │           GRAFO CAUSALE                     │
  │  propagazione credenze + Monte Carlo        │
  └────────┬────────────────────────────────────┘
           │
     ┌─────┴──────┐
     ▼            ▼
  REVISIONE   AUTHORING        ← il giudizio umano entra qui
  (togli)     (aggiungi)         e ha la precedenza
     └─────┬──────┘
           ▼
     grafo efficace  ────►  TEORIE
                              │
        ┌─────────────────────┼──────────────┬────────────┐
        ▼                     ▼              ▼            ▼
    AVVERSARIO          VISTA ESTERNA     DEBATE     ESPERIMENTI
    (costa rank)        (base rate)     (bivio)     (sintetico/campo)
        │                     │              │            │
        └─────────────────────┴──────┬───────┴────────────┘
                                     ▼
                                 TRIPWIRE
                            (impegno con data)
                                     │
                              ...osservi...
                                     │
                    l'unico punto in cui entra
                    informazione nuova sul mondo
                                     │
                                     ▼
                              rigenerazione
```

---

## 2. Inquadramento decisionale

`decision_studio/reasoning/framing.py`, `frame_service.py`, `domains.py`

> ### ⚠️ Due sistemi di domande distinti
>
> È l'equivoco più facile da fare, quindi va detto subito.
>
> | | **Inquadramento** | **Chiarimento** |
> |---|---|---|
> | File | `framing.py` + `domains.py` | `clarifications.py` |
> | Generate da LLM? | **No** (tranne il pacchetto per domini non previsti) | **Sì** |
> | Quando | *Prima* di qualsiasi generazione | *Dopo* che esistono le teorie |
> | Perché | Devono esistere prima che ci sia qualcosa da analizzare, e le obbligatorie devono essere note in anticipo per poter **bloccare** | Nascono dall'incertezza osservata nelle teorie: quali risposte cambierebbero una conclusione |
> | Bloccano? | Sì, le 10 obbligatorie | No, mai |
>
> Il catalogo di inquadramento è fisso anche perché le risposte restino
> confrontabili fra progetti: se ogni progetto ricevesse domande diverse,
> nessun confronto sarebbe possibile.
>
> **L'unica eccezione**: quando il dominio non è fra i sei previsti, un LLM
> *propone* un pacchetto di domande. Proposte, non poste: l'utente le accetta,
> e nessuna diventa mai obbligatoria.

### Cosa fa

Quindici domande in cinque sezioni. Dieci sono obbligatorie e **bloccano** la
generazione delle teorie: `FrameIncompleteError` → HTTP 409 con l'elenco delle
mancanti.

| Sezione | Domande |
|---|---|
| Ruolo | ruolo, autorità, chi va convinto |
| Decisione | cosa si decide, opzioni, scadenza, reversibilità |
| Criteri | successo, vincoli, quale errore preferisci |
| Convinzioni | cosa credi già, cosa ti farebbe cambiare idea, casi simili |
| Fonti | tipi di fonte, chi le ha scritte |

### Passo per passo

1. `GET /frame` restituisce il catalogo con le risposte già date
2. `PATCH /frame` valida ogni risposta contro il tipo dichiarato e fa merge
   — **la sottomissione parziale è permessa**
3. `missing_required()` ricalcola cosa manca
4. Se la risposta a `decision` c'è, diventa `project.decision_objective`
5. `render_frame()` produce il testo che **precede** le evidenze nel prompt

### Assunzioni

| # | Assunzione | Rischio se falsa |
|---|---|---|
| A1 | Le 15 domande sono quelle giuste | Si raccolgono le risposte sbagliate. Mitigato: ogni domanda dichiara in `feeds` cosa alimenta; una che non guida niente va cancellata |
| A2 | 10 su 15 obbligatorie è il punto giusto | Troppe → l'utente scrive qualsiasi cosa per passare. Troppo poche → il gate non protegge |
| A3 | Un catalogo fisso batte il coaching conversazionale | Il coaching si adatta meglio; il catalogo è confrontabile fra progetti e può bloccare. **Scelta deliberata, non ovvia** |
| A4 | Il frame prima delle evidenze cambia l'output | Non misurato. Plausibile ma non verificato |

---

## 3. Estrazione dei claim

`decision_studio/llm/prompts/claim_extraction.py`

### Cosa fa

Estrae affermazioni dal testo. Per ognuna chiede **quattro** cose invece di due:

- `confidence` — quanto **fermamente la fonte** lo afferma
- `prior` — quanto è **probabilmente vero**
- `source_interest` — chi lo dice ci guadagna?
- `source_role` — chi lo dice, in parole

### Perché la separazione

Il codice originale chiedeva "intrinsic confidence" e la usava come probabilità.
Sono cose diverse e spesso **opposte**:

| Testo | Fermezza | Verità reale |
|---|---|---|
| *"Il fornitore consegnerà sicuramente"* — brochure fornitore | 0.90 | ~0.40 |
| *"È possibile che il freeze sia slittato"* — capo ing., interno | 0.40 | ~0.80 |

Il prior era **anti-correlato con la verità**.

### L'aggiustamento

`reasoning/source_interest.py` applica un delta esplicito e **loggato**:

```python
against_interest  → +0.15    # ammette qualcosa che gli costa
disinterested     →  0.00
interested        → -0.10    # ci guadagna a essere creduto
unknown           →  0.00
```

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| B1 | Il modello sa distinguere fermezza da verità | Se sbaglia, il prior è rumore. **Mai verificato** |
| B2 | +0.15 / −0.10 sono le magnitudini giuste | Numeri scelti a mano |
| B3 | L'asimmetria è corretta | Si assume che chi ha un interesse spesso dica comunque il vero, mentre una confessione raramente sia falsa. Difendibile, non misurato |
| B4 | Chi asserisce è desumibile dal testo | Spesso non lo è → `unknown` → nessun aggiustamento. Fallimento benigno |

---

## 4. Deduplicazione semantica

`decision_studio/pipeline/claim_dedup.py`

### Cosa fa

Unisce claim che dicono la stessa cosa in documenti diversi.

```
1. ordina per prior decrescente        ← sopravvive il meglio sostenuto
2. per ogni claim: coseno vs i leader dei gruppi già formati
3. se ≥ 0.86 → unisci
4. bonus corroborazione: +0.06 per fonte extra, max +0.15
5. le frasi unite vanno in corroborated_by
```

### Perché il coseno e non i token

Tre report, un fatto:

- *"L'onboarding ha richiesto undici settimane"*
- *"La messa a regime è durata tre mesi più del previsto"*
- *"Abbiamo sottostimato di 7 settimane"*

**Jaccard sui token = 0.00.** Nessuna parola in comune. Coseno ≈ 0.85.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| C1 | 0.86 è la soglia giusta | **Non tarata.** Scelta conservativa: un'unione sbagliata perde informazione irrecuperabilmente, una mancata lascia lo stato precedente |
| C2 | +0.06 per fonte, cap +0.15 | Numeri scelti a mano. Il cap esiste perché senza si reintroduce il conteggio multiplo |
| C3 | Frasi-fonte distinte = fonti indipendenti | **Falsa in generale.** Tre report che citano lo stesso originale contano tre volte |
| C4 | Senza embedding non si unisce | Deliberato: "non so" ≠ "identico" |

---

## 5. Inferenza causale

`decision_studio/pipeline/causal_inferrer.py`, `graph/edge_weight.py`

### Cosa fa

Per ogni coppia di claim chiede se il primo causa il secondo. Chiede **due**
numeri:

- `effect` — quanto passa **se** il nesso è reale
- `link_confidence` — quanto è certo che il nesso **esista**

```python
strength = clamp(effect × link_confidence, 0.10, 0.95)
```

### Perché due numeri

Un solo numero rispondeva a due domande. *"90% di probabilità di 1 cm di neve"* e
*"30% di probabilità di 40 cm"* sono situazioni opposte che diventano lo stesso
"rischio neve medio".

| Edge | Prima | Ora |
|---|---|---|
| Piccolo ma certo | 0.5 | 0.25 × 0.95 |
| Grande ma speculativo | 0.5 | 0.85 × 0.30 |

Il prodotto resta simile — corretto, la propagazione non deve cambiare. Ciò che
si guadagna è tutto quello che legge le componenti: il pannello, le domande di
chiarimento, e il rumore di Monte Carlo.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| D1 | Il modello risponde meglio a due domande che a una | Plausibile ma non misurato |
| D2 | Il prodotto è la combinazione giusta | Deriva dal Noisy-OR. Se il nesso è reale al 50% e trasmette 0.8, il contributo atteso è 0.4 |
| D3 | Floor 0.10 / ceiling 0.95 | Il floor evita che un edge sparisca; il ceiling nega la certezza. Scelti a mano |
| D4 | `strength` denormalizzato resta coerente | **Fragile**: scrivere `effect` senza ricalcolare `strength` rompe il grafo. Solo la convenzione lo impedisce |

---

## 6. Ri-valutazione cieca

`decision_studio/pipeline/blind_rescorer.py`

### Cosa fa

Rivaluta ogni edge con un chiamata che non sa a quale argomento serve.

```
1. author_effect/author_confidence ← salva i punteggi originali
2. mette tutti gli edge in un pool
3. mescola (seed fisso 20260725)
4. batch da 8, temperatura 0.1
5. il valutatore vede: CAUSA / EFFETTO / MECCANISMO
   NON vede: id, teoria di appartenenza, punteggio originale
6. il divario autore−cieco = inflazione, riportata
```

### Perché

La stessa chiamata proponeva l'edge, scriveva il meccanismo e lo valutava. Stesso
nesso, due scritture: quella prolissa 0.80, quella concisa 0.55. **0.25 di forza
causale comprata con il numero di parole.**

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| E1 | Il valutatore cieco è meno distorto | Plausibile, non misurato |
| E2 | Acceca la proprietà, non la retorica | **Vera e riconosciuta.** Il valutatore legge ancora il meccanismo: la prosa elegante vince ancora. Servirebbe una valutazione a due stadi, al doppio delle chiamate |
| E3 | Il seed fisso garantisce riproducibilità | Vero per l'ordine, non per il modello |
| E4 | Batch da 8 non introduce effetti di contesto | **Dubbia.** Gli item potrebbero influenzarsi a vicenda |

---

## 7. Grounding delle evidenze

`decision_studio/pipeline/evidence_grounder.py`, `graph/belief_propagation.py`

### Il cambiamento chiave

```python
def _evidence_modulation(evidence_score, has_contradiction=False):
    score = clamp01(evidence_score)
    if has_contradiction:
        return max(0.05, score ** 1.5)   # c'è un motivo per dubitare
    return max(0.30, score ** 1.5)       # il silenzio non è smentita
```

| | Prima | Ora |
|---|---|---|
| Nessuna evidenza (fatto interno) | 0.000 | **0.300** |
| Contraddetta da 3 fonti | 0.000 | 0.050 |
| Evidenza forte | 0.854 | 0.854 |

Prima un fatto interno non cercabile e una tesi smentita valevano lo stesso zero.
Nelle decisioni strategiche la maggior parte dei nessi è interna: il codice
originale cancellava silenziosamente la parte più importante del grafo.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| F1 | 0.30 è il floor giusto | Scelto a mano |
| F2 | L'assenza allarga l'incertezza, non abbassa la credenza | **Epistemicamente difendibile.** L'implementazione però alza solo il floor: non allarga davvero l'intervallo |
| F3 | `has_contradiction` è affidabile | Dipende dalla classificazione delle evidenze in fase di grounding |

**Latenza documentata:** `_compute_consensus` divide per *tutte* le evidenze,
incluse le neutre. 4 a favore e 6 neutre → 0.4 → "contested" senza nulla contro.
Lasciata com'è: cambiarla sposta ogni etichetta in ogni progetto esistente.

---

## 8. Propagazione delle credenze

`decision_studio/graph/belief_propagation.py`

```
1. ordinamento topologico (i cicli sono già stati rotti)
2. nodo radice:  belief = prior     ← non confidence
3. nodo interno: Noisy-OR sui genitori
       contributo = belief(genitore) × strength × modulazione_evidenze
       belief = 1 − Π(1 − contributo)
4. gate AND: prodotto invece di Noisy-OR
5. edge inibitori: moltiplicano (1 − contributo)
```

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| G1 | I meccanismi causali sono indipendenti | **Falsa nelle decisioni strategiche**, dove tutto è intrecciato. È l'assunzione del Noisy-OR e non è stata rimossa |
| G2 | Il grafo può essere reso aciclico | `_break_cycles` cancella l'arco più debole di ogni ciclo. Nei sistemi causali il loop è spesso il punto. **Ancora silenzioso** |
| G3 | Un belief è una probabilità | Per un evento unico non esiste una lettura frequentista. **La debolezza più profonda del sistema** |

---

## 9. Revisione umana

`decision_studio/reasoning/review.py`, `effective_graph.py`

### Cosa fa

Ogni operazione, in una transazione:

```
1. aggiorna le colonne di revisione sull'elemento
2. scrive una riga immutabile in graph_operation (before/after)
3. incrementa project.graph_revision
4. invalida teorie e debate  ← mark_reasoning_stale()
```

### Il grafo efficace

```python
claim efficace  ⟺  is_active AND status ∉ {rejected, not_relevant}
edge efficace   ⟺  idem AND entrambi gli estremi efficaci
strength        ⟺  strength_override se presente, altrimenti strength
```

**Il ragionamento vede solo il grafo efficace. Lo schermo mostra tutto**, in
opacità ridotta. Rifiutare non cancella la storia.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| H1 | Il giudizio umano batte l'inferenza AI | Assunzione fondante di tutto il sistema |
| H2 | Un solo `review_status` basta | **Limite noto.** `business_critical` cancella `needs_evidence` |
| H3 | Un edge con un estremo rimosso non è un nesso | Deriva dalla semantica causale |
| H4 | `graph_operation` cresce senza limite | Nessuna politica di archiviazione |

---

## 10. Authoring manuale

`decision_studio/reasoning/authoring.py`

### Cosa fa

Aggiunge claim ed edge che i documenti non contenevano. Chiude un'asimmetria: la
revisione era autoritativa per **togliere** e muta per **aggiungere**.

### Il ricalcolo, e cosa NON viene rifatto

| Stadio | Rifatto? | Perché |
|---|---|---|
| Inferenza causale | **Solo le coppie col nuovo claim** | Rifarla su tutto rigenererebbe i nessi già rifiutati: accettare una correzione umana ne annullerebbe tutte le altre |
| Ri-valutazione cieca | **Saltata sugli elementi utente** | Corregge un modello che valuta la propria proposta. Qui quel bias non c'è |
| Grounding evidenze | Solo i nuovi edge | Idem |
| DAG + propagazione | **Tutto** | Un nodo cambia topologia, cicli e ogni credenza a valle. Calcolo puro, gratis |

`RecomputePlan` è restituito in risposta: **vedi il costo prima di pagarlo.**

### Un dettaglio non ovvio

L'inferrer pota le coppie per similarità di embedding, ma un claim aggiunto a
mano non ne ha. Il fallback usa un vettore segnaposto condiviso: la similarità
diventa 1.0 e la coppia **viene considerata**. Scartarla silenziosamente
significherebbe che un claim aggiunto a mano non acquisisce mai nessun nesso.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| I1 | Un claim utente è `ASSUMPTION` | Epistemicamente corretto: un'asserzione senza evidenza è un'assunzione |
| I2 | `confidence 0.8 / prior 0.5` | Lo affermi con fermezza, la fermezza non è verità |
| I3 | Non serve rivalutare ciecamente l'utente | Deliberato: il giudizio umano è autoritativo per progetto |
| I4 | Considerare una coppia senza embedding è meglio che scartarla | Costa una chiamata in più. Il fallimento benigno è preferito |

---

## 11. Generazione delle teorie

`decision_studio/reasoning/theories.py`, `context_builder.py`, `validation.py`

### Passo per passo

```
1. GATE: frame incompleto → FrameIncompleteError (409)
2. carica il grafo efficace
3. seleziona il sottografo se troppo grande
4. assegna i token di riferimento: C1, E1, V1...
5. costruisce il prompt: FRAME → VISTA ESTERNA → GRAFO
6. chiama l'LLM (cache disabilitata)
7. VALIDA: ogni riferimento deve risolvere
8. deduplica per sovrapposizione dei percorsi
9. confronta con le versioni precedenti
10. persiste
```

### Perché i token e non gli UUID

`C3` invece di `a4f2...`. Più corto, ma soprattutto: **un token inventato non
risolve**. La fabbricazione diventa strutturalmente rilevabile invece di dover
essere controllata.

### Perché la cache è disabilitata

La cache semantica confronta per similarità a 0.92. Una modifica a un edge sposta
appena un prompt lungo → **cache hit** → teorie costruite sul grafo pre-modifica.
Esattamente il fallimento che il sistema esiste per prevenire.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| J1 | I token impediscono la fabbricazione | Vera per i riferimenti, non per la narrativa |
| J2 | Sovrapposizione archi ≥ 0.8 = duplicato | Scelta a mano |
| J3 | Matching versioni con Jaccard ≥ 0.6 | Può unire teorie che l'utente considera distinte |
| J4 | 60 claim / 120 edge è il taglio giusto | **Non tarato su progetti reali** |
| J5 | I pesi di selezione sono ragionevoli | Codificano un giudizio: i segnali umani dominano quelli strutturali |

---

## 12. Avversario

`decision_studio/reasoning/adversary.py`

### Cosa fa

Chiamata separata, temperatura 0.7, che **non vede mai** titolo, sintesi o
raccomandazione. Solo decisione e catena causale.

```python
objection_load  = media delle severità vive      # non somma
adjusted_score  = confidence × (1 − 0.5 × load)
contested       = load ≥ 0.45
```

L'ordinamento usa `adjusted_score`. **Un'obiezione che non cambia niente è
decorazione.**

### Perché media e non somma

Tre obiezioni blande non devono superare una fatale. E la somma dipenderebbe da
quanto è prolisso l'avversario.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| K1 | Senza la prosa attacca il ragionamento | Plausibile; non verificato che non attacchi comunque lo stile |
| K2 | `OBJECTION_WEIGHT = 0.5` | Scelto a mano. Demota, non annienta: anche l'avversario è un modello |
| K3 | Soglia contested 0.45 | Scelta a mano |
| K4 | Le severità sono comparabili fra teorie | **Dubbia.** Chiamate separate potrebbero calibrare diversamente |

---

## 13. Vista esterna

`decision_studio/reasoning/outside_view.py`

### Cosa fa

```
1. legge la risposta su "casi simili"
2. estrae conteggi espliciti → reference_case
3. abbina le teorie alle classi di riferimento
4. delta = confidence − base_rate
5. |delta| ≥ 0.20 → segnala
```

### I rifiuti espliciti

- *"Le integrazioni di solito slittano"* → **nessun denominatore, non estrae
  niente.** Un numero inventato verrebbe mostrato all'utente come suo ricordo
- Una teoria che il modello non riesce ad abbinare **resta senza confronto**,
  invece di essere forzata sulla classe più vicina

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| L1 | Il ricordo dell'utente è una base rate valida | **Debole.** La memoria è selettiva, e n=2 non è una statistica. È comunque l'unico ancoraggio empirico disponibile |
| L2 | Confidence e base rate sono comparabili | **La più discutibile del sistema.** "Questa spiegazione regge" e "l'esito si è verificato" non sono la stessa quantità. Mitigato: si confrontano solo quando il modello dice che la teoria è *su* quell'esito |
| L3 | Soglia 0.20 | Scelta a mano |

---

## 14. Debate fra teorie

`decision_studio/reasoning/debate.py`, `debate_service.py`

### Passo per passo

```
1. seleziona le prime 4 teorie per adjusted_score → 6 coppie
2. PER OGNI COPPIA, SENZA LLM:
       jaccard = |archi_A ∩ archi_B| / |archi_A ∪ archi_B|
       ≥ 0.70 → same_story    ← il modello NON viene chiamato
       ≤ 0.20 → orthogonal
       altrove → competing
3. solo per le coppie non-same_story: chiama l'LLM
       → crux, discriminatore, evidence_favours, both_possible
4. persiste; le coppie precedenti diventano stale
```

### Perché sugli archi e non sui claim

Due teorie sullo stesso esito condividono per costruzione il claim finale, e
spesso anche la causa radice. Contare i claim farebbe sembrare quasi ogni coppia
la stessa storia. **Ciò che distingue una spiegazione causale è il percorso.**

### I tre esiti, e dove portano

| Relazione | Significato | Dove porta |
|---|---|---|
| `same_story` | Una teoria, due formulazioni | Una va marcata superseded |
| `orthogonal` | Cose diverse, **entrambe possibili** | Scenario combinato: se valgono entrambe il rischio supera ciascuna |
| `competing` + discriminante | Bivio risolvibile | **Tripwire su entrambe** |
| `competing` senza discriminante | Non decidibile in tempo | Scegli l'opzione robusta a entrambe |

### La promozione è esplicita

Il discriminante arriva **già in forma di tripwire** — sarebbe banale crearlo da
solo. Non lo fa: ovunque nel sistema il modello propone e l'utente conferma.
Sarebbe stata l'unica eccezione, e le eccezioni sono il modo in cui uno strumento
smette di essere affidabile.

Il tripwire va su **entrambe** le teorie, direzione `falsifies`: l'osservazione
non testa una spiegazione, risolve un bivio da cui discendono azioni opposte.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| M1 | Soglie 0.70 / 0.20 | Scelte a mano |
| M2 | Il confronto sugli archi è quello giusto | Difendibile; un percorso è fatto di archi |
| M3 | Le prime 4 teorie bastano | Le coppie crescono quadraticamente; il valore marginale cala |
| M4 | Il modello trova un discriminante reale | **Il punto debole.** Potrebbe produrre osservazioni compatibili con entrambe. Il prompt lo vieta, niente lo verifica |
| M5 | Un debate non muove le confidence | **Deliberato.** Scoprire una divergenza non è evidenza |

---

## 15. Tripwire

`decision_studio/reasoning/adversary.py`

Osservazioni concrete con data. Il sostituto dell'esperimento: non puoi
randomizzare, ma puoi impegnarti in anticipo su cosa ti farebbe cambiare idea.

Quando un tripwire `falsifies` scatta → la teoria diventa stale.

**È l'unico punto del sistema dove entra informazione nuova sul mondo.** Tutto il
resto rimastica i documenti caricati.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| N1 | Il modello produce osservazioni davvero controllabili | Il prompt insiste; nessuna verifica |
| N2 | L'utente andrà a guardare | **Nessun promemoria implementato.** `check_by` è salvato, niente avvisa |
| N3 | La falsificazione batte la conferma | Popperiano, difendibile |

---

## 16. Esperimenti

`decision_studio/reasoning/experiments.py`

### Sintetico

Simula gli stakeholder che devono essere convinti. Risponde a *"sopravvive alla
riunione, e cosa obietteranno"*.

**Non alza mai la confidenza.** Vincolato nel codice, con test dedicato. Cinque
stakeholder simulati, quattro favorevoli, confidenza che sale sarebbe una misura
della compiacenza del modello presentata come evidenza.

Le obiezioni vengono promosse nel registro avversariale, dove **costano rank**.
L'accordo simulato non vale nulla; l'obiezione simulata vale.

### Sul campo

Un test vero, eseguibile entro la scadenza. Se non esiste, lo dice — ed è un
risultato: significa che decidi a giudizio.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| O1 | Il modello prevede le reazioni umane | **Molto dubbia.** Per questo non tocca le confidence |
| O2 | Le personas dal frame sono migliori di quelle inventate | Difendibile |
| O3 | `SIMULATED_OBJECTION_SEVERITY = 0.35` | Sotto la soglia contested: un solo dissenziente simulato non basta |

---

## 17. Monte Carlo

`decision_studio/graph/stability.py`

```
1. compila il grafo una volta
2. per 200 run: perturba ogni edge, ri-propaga
3. sigma per edge = base × (0.25 + 0.75 × (1 − link_confidence))
4. numeri casuali comuni: stesso jitter per baseline e scenari
5. riporta p10/p50/p90 e p_first
```

Sostituisce `compute_belief_intervals`, che dichiarava di ri-propagare e **non lo
faceva**: gli intervalli si restringevano con la profondità (0.160 → 0.055 su 4
salti), cioè il sistema dichiarava più certezza più ci si allontanava dalle
evidenze.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| P1 | `sigma = 0.12` | **Affermato, non misurato.** Codifica "questi numeri sono buoni a ±0.12" |
| P2 | Rumore gaussiano additivo sul peso operativo | Non su effetto e confidenza separatamente: la distribuzione congiunta non è identificata da nulla |
| P3 | 200 run bastano | Sufficienti a distinguere 52/48 da 70/30 |
| P4 | I numeri casuali comuni sono corretti | Vero per gli archi condivisi. Per quelli che **differiscono** si usano estrazioni indipendenti: quell'arco è l'intervento, e condividerne il rumore cancellerebbe proprio l'incertezza in esame |

---

## 18. Domande di chiarimento

`decision_studio/reasoning/clarifications.py`

Genera domande la cui risposta cambierebbe una teoria. Deduplicazione lessicale
(fingerprint + Jaccard ≥ 0.7).

**Rispondere non modifica mai il grafo.** Se la risposta contraddice un elemento,
viene *proposta* una revisione.

### Assunzioni

| # | Assunzione | Rischio |
|---|---|---|
| Q1 | La dedup lessicale basta | **Falsa per le parafrasi.** Qui, a differenza dei claim, gli embedding non ci sono |
| Q2 | Il rilevamento di contraddizione a parole chiave | **Molto grezzo.** Negazioni in inglese e cinese |

---

## 19. Invalidazione a cascata

`reasoning/review.py :: mark_reasoning_stale()`

```python
async def mark_reasoning_stale(session, project_id, reason):
    theories = await mark_theories_stale(...)
    debates  = await mark_debates_stale(...)
```

**Un solo punto.** L'alternativa — ogni chiamante ricorda di invalidare ogni cosa
derivata — **è già fallita una volta**: l'authoring invalidava le teorie e
lasciava i debate con numeri di sovrapposizione calcolati su claim ormai
cambiati. La prossima cosa derivata va aggiunta lì, non in ogni call site.

| Elemento | Stale quando | Perché |
|---|---|---|
| Teoria | grafo cambia, risposta data, tripwire scatta | Dedotta da un grafo che si è mosso |
| Debate | grafo cambia, nuovo run | **Contiene numeri ora sbagliati** |

Differenza importante: una teoria stale è *superata*; un debate stale è
*quantitativamente falso*.

---

## 20. Tutte le assunzioni in un posto

### Le tre più profonde

**1. Un belief è una probabilità.** (G3) Per un evento unico non esiste lettura
frequentista. Mitigato dalle bande verbali, non risolto.

**2. I meccanismi causali sono indipendenti.** (G1) Assunzione del Noisy-OR,
falsa nei sistemi strategici dove tutto è intrecciato.

**3. Confidence e base rate sono comparabili.** (L2) "Questa spiegazione regge" e
"l'esito si è verificato" non sono la stessa quantità.

### Ogni soglia scelta a mano

| Costante | Valore | Dove |
|---|---|---|
| `DEDUP_THRESHOLD` | 0.86 | dedup claim |
| `CORROBORATION_BONUS` / cap | 0.06 / 0.15 | dedup claim |
| `MIN/MAX_STRENGTH` | 0.10 / 0.95 | peso edge |
| `EVIDENCE_FLOOR` | 0.30 | propagazione |
| `INTEREST_ADJUSTMENT` | +0.15 / −0.10 | prior |
| `DEFAULT_SIGMA` | 0.12 | Monte Carlo |
| `MIN_JITTER_FACTOR` | 0.25 | Monte Carlo |
| `OBJECTION_WEIGHT` | 0.5 | avversario |
| `CONTESTED_THRESHOLD` | 0.45 | avversario |
| `SIMULATED_OBJECTION_SEVERITY` | 0.35 | esperimenti |
| `MATERIAL_DIVERGENCE` | 0.20 | vista esterna |
| `SAME_STORY` / `ORTHOGONAL` | 0.70 / 0.20 | debate |
| `MATCH_EDGE_OVERLAP` | 0.6 | versioning teorie |
| `DUPLICATE_EDGE_OVERLAP` | 0.8 | dedup teorie |
| `DUPLICATE_QUESTION_OVERLAP` | 0.7 | dedup domande |

**Nessuna è tarata su dati reali.** Sono scelte ragionate, non misurate. Se il
sistema va in produzione, questa tabella è la lista di ciò che va validato.

### Il rischio complessivo

Il sistema **sembra** rigoroso: numeri separati, simulazioni, percentuali, bande.
Sotto ci sono stime di un modello linguistico e quindici soglie scelte a mano.

Le difese costruite: bande verbali invece di decimali, Monte Carlo che dice
quando una classifica non regge, esperimenti sintetici che non toccano le
confidence, tripwire che espongono le previsioni alla realtà, e il debate che sa
dire *"questa domanda non è rispondibile in tempo"*.

**L'antidoto vero resta la calibrazione**, che richiede dati di esito che nessuno
ha ancora. Fino ad allora il sistema è più onesto su *quanto* è incerto, ma
nessuno ha verificato se le sue probabilità corrispondono al mondo.
